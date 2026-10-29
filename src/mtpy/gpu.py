"""CUDA executor of the whole tracking kernel (decision 0002 / 0003: the executor is a swappable slot; 0024: the three
Z methods of track.Z_METHODS), through numba.cuda (no cupy, no C). One frame copy, one kernel launch, one thread
block per bead: cross profiles (SGL sums as the VI), centre by the three-pass parabola on direct DFTs, radial profile
(float64 atomics into the radius bins, then the VI's SGL rounding), the band-passed mirrored profile, the squared
differences to every LUT slice in parallel over the slices, and the chosen Z estimator with its sums over the profile
reduced across the block. The same steps and constants as `fast.py`; tests/test_gpu.py holds the two together.
shortcut: shared memory is sized by the constants below (cross <= 128, LUT <= 512 slices), raise them if a LUT exceeds.
shortcut: pixel reads are clamped to the frame (the CPU slices an out-of-frame window into garbage); the bead is
flagged bad by the same position test as on the CPU.
"""
import math

import numba
import numpy as np
from numba import cuda

from mtpy import fast
from mtpy.track import DEFAULT, GOLDEN, N_ITER, QUAD_WEIGHTS, Z_METHODS

TPB = 128
MAX_N, MAX_L, MAX_S = 128, 128, 512


@cuda.jit(device=True)
def _clamp(v, lo, hi):
    """numba.cuda has no two-argument min / max."""
    return lo if v < lo else (hi if v > hi else v)  # noqa: FURB136


@cuda.jit(device=True)
def _rint(x):
    """np.rint: half to even."""
    r = math.floor(x)
    d = x - r
    if d > 0.5 or (d == 0.5 and int(r) % 2 == 1):
        r += 1.0
    return r


@cuda.jit(device=True)
def _block_sum(red, v):
    """Sum of v over the block, returned to every thread (all threads must call)."""
    t = cuda.threadIdx.x
    red[t] = v
    cuda.syncthreads()
    s = TPB // 2
    while s > 0:
        if t < s:
            red[t] += red[t + s]
        cuda.syncthreads()
        s //= 2
    total = red[0]
    cuda.syncthreads()
    return total


@cuda.jit(device=True)
def _catmull(R, z, r):
    S = R.shape[0]
    i = int(math.floor(z))  # noqa: RUF046  (math.floor is a float on the GPU)
    t = z - i
    p0 = R[_clamp(i - 1, 0, S - 1), r]
    p1 = R[_clamp(i, 0, S - 1), r]
    p2 = R[_clamp(i + 1, 0, S - 1), r]
    p3 = R[_clamp(i + 2, 0, S - 1), r]
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


@cuda.jit(device=True)
def _angle_ratio(a, b):
    """arg(a / b) without the division: atan2 of a * conj(b)."""
    return math.atan2(a.imag * b.real - a.real * b.imag, a.real * b.real + a.imag * b.imag)


@cuda.jit(device=True)
def _ssd_at(prep, real, L, z, red):
    v = 0.0
    for r in range(cuda.threadIdx.x, L, TPB):
        e = _catmull(real, z, r) - prep[r]
        v += e * e
    return _block_sum(red, v)


@cuda.jit(device=True)
def _theta_at(cork, cork_cal, L, z, red):
    num = den = 0.0
    for r in range(cuda.threadIdx.x, L, TPB):
        c = _catmull(cork_cal, z, r)
        w = abs(cork[r]) * abs(c)
        num += w * _angle_ratio(cork[r], c)
        den += w
    return _block_sum(red, num) / _block_sum(red, den)


@cuda.jit(device=True)
def _z_quad(cork, L, idx, ampl, cork_cal, qw, red):
    S = cork_cal.shape[0]
    if idx + 2 >= S:
        return float(idx)
    lo = idx - 2 if idx > 2 else 0
    ph = cuda.local.array(5, numba.float64)
    for q in range(5):
        num = den = 0.0
        for r in range(cuda.threadIdx.x, L, TPB):
            wq = abs(cork[r]) * ampl[lo + q, r]
            num += wq * _angle_ratio(cork[r], cork_cal[lo + q, r])
            den += wq
        ph[q] = _block_sum(red, num) / _block_sum(red, den)
    A = cuda.local.array((3, 3), numba.float64)
    bb = cuda.local.array(3, numba.float64)
    for i in range(3):
        bb[i] = 0.0
        for j in range(3):
            A[i, j] = 0.0
    for q in range(5):
        y = q - 2.0
        for i in range(3):
            ri = ph[q] * ph[q] if i == 0 else (ph[q] if i == 1 else 1.0)
            bb[i] += qw[q] * ri * y
            for j in range(3):
                rj = ph[q] * ph[q] if j == 0 else (ph[q] if j == 1 else 1.0)
                A[i, j] += qw[q] * ri * rj
    for col in range(3):                               # fast._solve3: partial pivoting, back substitution
        piv = col
        for r in range(col + 1, 3):
            if abs(A[r, col]) > abs(A[piv, col]):
                piv = r
        if piv != col:
            for j in range(3):
                A[col, j], A[piv, j] = A[piv, j], A[col, j]
            bb[col], bb[piv] = bb[piv], bb[col]
        for r in range(col + 1, 3):
            f = A[r, col] / A[col, col]
            for j in range(col, 3):
                A[r, j] -= f * A[col, j]
            bb[r] -= f * bb[col]
    return idx + bb[2] / A[2, 2]


@cuda.jit(device=True)
def _z_spline(prep, L, idx, real, red):
    lo = _clamp(idx - 1.0, 0.0, real.shape[0] - 1.0)
    hi = _clamp(idx + 1.0, 0.0, real.shape[0] - 1.0)
    c, d = hi - GOLDEN * (hi - lo), lo + GOLDEN * (hi - lo)
    fc, fd = _ssd_at(prep, real, L, c, red), _ssd_at(prep, real, L, d, red)
    for _ in range(N_ITER):
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - GOLDEN * (hi - lo)
            fc = _ssd_at(prep, real, L, c, red)
        else:
            lo, c, fc = c, d, fd
            d = lo + GOLDEN * (hi - lo)
            fd = _ssd_at(prep, real, L, d, red)
    return (lo + hi) / 2


@cuda.jit(device=True)
def _z_phase_spline(cork, L, idx, ampl, cork_cal, qw, red):
    lo = _clamp(idx - 1.0, 0.0, cork_cal.shape[0] - 1.0)
    hi = _clamp(idx + 1.0, 0.0, cork_cal.shape[0] - 1.0)
    tlo, thi = _theta_at(cork, cork_cal, L, lo, red), _theta_at(cork, cork_cal, L, hi, red)
    if tlo * thi > 0:
        return _z_quad(cork, L, idx, ampl, cork_cal, qw, red)
    for _ in range(N_ITER):
        mid = (lo + hi) / 2
        tm = _theta_at(cork, cork_cal, L, mid, red)
        if tm * tlo > 0:
            lo, tlo = mid, tm
        else:
            hi, thi = mid, tm
    return (lo + hi) / 2


@cuda.jit(device=True)
def _parabola(c, n, n_pts):
    """fast._parabola on the rolled magnitude c[0:n]."""
    k, best = 0, c[0]
    for i in range(1, n):
        if c[i] > best:
            best, k = c[i], i
    m = n_pts // 2
    if k - m < 0 or k + m >= n:
        return math.nan
    s2 = s4 = sy = sty = st2y = 0.0
    for t in range(-m, m + 1):
        y = c[k + t]
        s2 += t * t
        s4 += t * t * t * t
        sy += y
        sty += t * y
        st2y += t * t * y
    a2 = (n_pts * st2y - s2 * sy) / (n_pts * s4 - s2 * s2)
    return k - (sty / s2) / (2 * a2)


@cuda.jit(device=True)
def _idft_mag(G, mag, cross, half, tw):
    """|IDFT(G[ax])| rolled by half into mag[ax], both axes over the block."""
    for q in range(cuda.threadIdx.x, 2 * cross, TPB):
        ax, m = q // cross, q % cross
        sr = si = 0.0
        j = 0
        for k in range(cross):                         # j = (k * m) % cross without the 64-bit modulo
            w = tw[j]
            sr += G[ax, k].real * w.real - G[ax, k].imag * w.imag
            si += G[ax, k].real * w.imag + G[ax, k].imag * w.real
            j += m
            if j >= cross:
                j -= cross
        mag[ax, (m + half) % cross] = math.sqrt(sr * sr + si * si) / cross


@cuda.jit(device=True)
def _shift(S, G, cross, half, kk, sc, col):
    """G[ax, k] = S exp(i kk * sc[ax, col] * a_k), a_k = k - cross for k > half: fast._center's
    |S| exp(i (arg S + ...)) without the atan2 and the modulus (rounding only)."""
    for q in range(cuda.threadIdx.x, 2 * cross, TPB):
        ax, k = q // cross, q % cross
        a = k - cross if k > half else k
        ph = kk * sc[ax, col] * a
        G[ax, k] = S[ax, k] * (math.cos(ph) + 1j * math.sin(ph))


@cuda.jit
def _track_kernel(image, inp, cross, h, arm, arm2, n_end, n_pts, quirk, frame2_shifted, win_rs, win_h, tw, tw2,
                  forget, cosband, real, ampl, cork_cal, nlen, qw, method, res):
    b = cuda.blockIdx.x
    t = cuda.threadIdx.x
    prof = cuda.shared.array((2, MAX_N), numba.float64)   # cross profiles, then the mirrored profile in prof[0]
    F = cuda.shared.array((2, MAX_N), numba.complex128)   # F * F per axis, then the band-passed spectrum in F[0]
    G = cuda.shared.array((2, MAX_N), numba.complex128)
    mag = cuda.shared.array((2, MAX_N), numba.float64)
    sc = cuda.shared.array((2, 4), numba.float64)         # per axis: P1, r1, out1, out2
    sw = cuda.shared.array((2, MAX_N), numba.float64)     # radial sums and weights
    cork = cuda.shared.array(MAX_L, numba.complex128)
    prep = cuda.shared.array(MAX_L, numba.float64)
    d = cuda.shared.array(MAX_S, numba.float64)
    red = cuda.shared.array(TPB, numba.float64)
    xb, yb = inp[b, 0], inp[b, 1]
    if inp[b, 2] == 0:
        if t == 0:
            for j in range(4):
                res[b, j] = -1.0
        return
    half = cross // 2
    H, W = image.shape
    oy, ox = yb - h, xb - h                     # the CPU's sub-image origin in the frame
    # --- cross profiles: To SGL per element, SGL sum, SGL divide (fast._track) ---
    for q in range(t, 2 * cross, TPB):
        ax, i = q // cross, q % cross
        s = numba.float32(0.0)
        for u in range(arm):
            r = (h - arm2 + u) if ax == 0 else (h - half + i)
            c = (h - half + i) if ax == 0 else (h - arm2 + u)
            s = numba.float32(s + numba.float32(image[_clamp(oy + r, 0, H - 1), _clamp(ox + c, 0, W - 1)]))
        prof[ax, i] = numba.float32(s / numba.float32(arm))
    cuda.syncthreads()
    # --- fast._prep: end means, window (each thread recomputes the mean of its axis; one write) ---
    for q in range(t, 2 * cross, TPB):
        ax, i = q // cross, q % cross
        first = last = 0.0
        for u in range(n_end):
            first += prof[ax, u]
            if quirk:
                if u > 0:
                    last += prof[ax, cross - u]
            else:
                last += prof[ax, cross - n_end + u]
        G[ax, i] = (prof[ax, i] - (first + last) / (2 * n_end)) * win_rs[i]   # staged in G: prof is still being read
    cuda.syncthreads()
    # --- fast._center: F2 = (DFT(p) * win_h)^2, three parabola passes ---
    for q in range(t, 2 * cross, TPB):
        ax, k = q // cross, q % cross
        sr = si = 0.0
        j = 0
        for i in range(cross):
            w = tw[j]
            sr += G[ax, i].real * w.real
            si -= G[ax, i].real * w.imag
            j += k
            if j >= cross:
                j -= cross
        f = (sr + 1j * si) * win_h[k]
        F[ax, k] = f * f
    cuda.syncthreads()
    kk = 2.0 * math.pi / cross
    _idft_mag(F, mag, cross, half, tw)
    cuda.syncthreads()
    if t < 2:
        sc[t, 0] = _parabola(mag[t], cross, n_pts)
        sc[t, 1] = _rint(sc[t, 0])
        sc[t, 2] = sc[t, 0] - sc[t, 1]                 # P1 - r1 drives the first shift
    cuda.syncthreads()
    _shift(F, G, cross, half, kk, sc, 2)
    cuda.syncthreads()
    _idft_mag(G, mag, cross, half, tw)
    cuda.syncthreads()
    if t < 2:
        sc[t, 2] = _parabola(mag[t], cross, n_pts) - sc[t, 1]   # out1
    cuda.syncthreads()
    if frame2_shifted:
        _shift(G, G, cross, half, kk, sc, 2)           # in place: each element reads and writes its own k
    else:
        _shift(F, G, cross, half, kk, sc, 2)
    cuda.syncthreads()
    _idft_mag(G, mag, cross, half, tw)
    cuda.syncthreads()
    if t < 2:
        sc[t, 3] = _parabola(mag[t], cross, n_pts) - sc[t, 1]   # out2
    cuda.syncthreads()
    sx = (sc[0, 0] + sc[0, 2] + sc[0, 3] - half) / 2
    sy = (sc[1, 0] + sc[1, 2] + sc[1, 3] - half) / 2
    # --- fast._radial at (h + sx, h + sy): the VI's pixel set, bins by atomics, SGL rounding ---
    xc, yc = h + sx, h + sy
    x0 = int(math.ceil(xc)) - half  # noqa: RUF046
    y0 = int(math.ceil(yc)) - half  # noqa: RUF046
    cx = half + (xc - math.ceil(xc))
    cy = half + (yc - math.ceil(yc))
    for i in range(t, half, TPB):
        sw[0, i] = sw[1, i] = 0.0
    for i in range(t, cross, TPB):                     # per row: first column j0 and the count N (fast._radial)
        dy = cy - i
        c = math.sqrt(half * half - dy * dy)
        N = int(math.ceil(2 * c))  # noqa: RUF046
        mag[0, i] = math.ceil(cx - c)
        mag[1, i] = N if N < cross else cross  # noqa: FURB136
    cuda.syncthreads()
    for q in range(t, cross * cross, TPB):
        i, j = q // cross, q % cross
        j0 = int(mag[0, i])
        if j < j0 or j >= j0 + int(mag[1, i]):
            continue
        r = math.sqrt((cx - j) ** 2 + (cy - i) ** 2)
        rf = int(math.floor(r))  # noqa: RUF046
        fr = r - rf
        p = numba.float64(image[_clamp(oy + y0 + i, 0, H - 1), _clamp(ox + x0 + j, 0, W - 1)])
        if rf < half:
            cuda.atomic.add(sw, (0, rf), (1 - fr) * p)
            cuda.atomic.add(sw, (1, rf), 1 - fr)
        if rf + 1 < half:
            cuda.atomic.add(sw, (0, rf + 1), fr * p)
            cuda.atomic.add(sw, (1, rf + 1), fr)
    cuda.syncthreads()
    nmir = 2 * half - 1
    for i in range(t, nmir, TPB):                      # mirrored profile: reverse(rad[1:]) ++ rad, rad = SGL(s / w)
        rr = half - 1 - i if i < half - 1 else i - (half - 1)
        prof[0, i] = numba.float64(numba.float32(sw[0, rr] / sw[1, rr]))
    cuda.syncthreads()
    # --- fast._prep_z: band pass (direct DFT, n points), corkscrew = IDFT[half + forget - 1 :], best slice ---
    n = nmir if nmir < cosband.shape[1] else cosband.shape[1]  # noqa: FURB136
    L = nlen[b]
    S = real.shape[1]
    for k in range(t, n, TPB):
        sr = si = 0.0
        j = 0
        for i in range(n):
            w = tw2[j]
            sr += prof[0, i] * w.real
            si -= prof[0, i] * w.imag
            j += k
            if j >= n:
                j -= n
        F[0, k] = (sr + 1j * si) * cosband[b, k]
    cuda.syncthreads()
    for r in range(t, L, TPB):
        m = r + half + forget[b] - 1
        sr = si = 0.0
        j = 0
        for k in range(n):
            w = tw2[j]
            sr += F[0, k].real * w.real - F[0, k].imag * w.imag
            si += F[0, k].real * w.imag + F[0, k].imag * w.real
            j += m
            if j >= n:
                j -= n
        cork[r] = sr / n + 1j * (si / n)
        prep[r] = sr / n
    cuda.syncthreads()
    for s in range(t, S, TPB):                         # distance to every LUT slice
        acc = 0.0
        for r in range(L):
            e = real[b, s, r] - prep[r]
            acc += e * e
        d[s] = acc
    cuda.syncthreads()
    best, idx = d[0], 0                                # every thread: the same scan, the same answer
    for s in range(1, S):
        if d[s] < best:
            best, idx = d[s], s
    # --- the estimator: uniform control flow, sums reduced over the block ---
    if method == 1:
        zi = _z_spline(prep, L, idx, real[b], red)
    elif method == 2:
        zi = _z_phase_spline(cork, L, idx, ampl[b], cork_cal[b], qw, red)
    else:
        zi = _z_quad(cork, L, idx, ampl[b], cork_cal[b], qw, red)
    if t == 0:
        res[b, 0], res[b, 1], res[b, 2], res[b, 3] = xb + sx, yb + sy, zi, float(idx)


class GpuKernel(fast.FastKernel):
    """FastKernel's `track(image, xin, yin, good_in)` with every stage on the GPU; the same results."""

    def __init__(self, cross, win_rs, win_h, cals, p=DEFAULT, z_method="current"):
        super().__init__(cross, win_rs, win_h, cals, p, z_method)
        if cross > MAX_N or self.real.shape[2] > MAX_L or self.real.shape[1] > MAX_S:
            raise ValueError("cross or LUT larger than mtpy.gpu's shared-memory constants")
        self.S = self.real.shape[1]
        n = min(2 * (cross // 2) - 1, self.cosband.shape[1])
        self.tw_d = cuda.to_device(np.exp(2j * np.pi * np.arange(cross) / cross))
        self.tw2_d = cuda.to_device(np.exp(2j * np.pi * np.arange(n) / n))
        self.win_rs_d, self.win_h_d = cuda.to_device(self.win_rs), cuda.to_device(self.win_h)
        self.forget_d, self.nlen_d = cuda.to_device(self.forget), cuda.to_device(self.nlen)
        self.cosband_d, self.real_d = cuda.to_device(self.cosband), cuda.to_device(self.real)
        self.ampl_d, self.cork_d = cuda.to_device(self.ampl), cuda.to_device(self.cork)
        self.qw_d = cuda.to_device(QUAD_WEIGHTS)
        self.nb = len(cals)
        # one stream, pinned staging buffers, one synchronisation per frame (each CUDA call costs ~0.1 ms under WDDM)
        self.stream = cuda.stream()
        self.inp_h = cuda.pinned_array((self.nb, 3), dtype=np.int64)       # xin, yin, good
        self.inp_d = cuda.device_array((self.nb, 3), dtype=np.int64)
        self.res_h = cuda.pinned_array((self.nb, 4))                       # x, y, z index, slice index
        self.res_d = cuda.device_array((self.nb, 4))
        self.img_d = self.img_h = None

    def track(self, image, xin, yin, good_in):
        if self.img_d is None or self.img_d.shape != image.shape or self.img_d.dtype != image.dtype:
            self.img_d = cuda.device_array(image.shape, dtype=image.dtype)
            self.img_h = cuda.pinned_array(image.shape, dtype=image.dtype)   # pinned staging: DMA instead of a pageable copy
        np.copyto(self.img_h, image)
        self.inp_h[:, 0], self.inp_h[:, 1], self.inp_h[:, 2] = xin, yin, good_in
        self.img_d.copy_to_device(self.img_h, stream=self.stream)
        self.inp_d.copy_to_device(self.inp_h, stream=self.stream)
        p = self.p
        _track_kernel[self.nb, TPB, self.stream](self.img_d, self.inp_d, self.cross, self.h, p.arm,
                                                 int(np.rint(p.arm / 2)), self.n_end, p.n_pts, p.end_quirk,
                                                 p.frame2_shifted, self.win_rs_d, self.win_h_d, self.tw_d, self.tw2_d,
                                                 self.forget_d, self.cosband_d, self.real_d, self.ampl_d, self.cork_d,
                                                 self.nlen_d, self.qw_d, self.z_method, self.res_d)
        self.res_d.copy_to_host(self.res_h, stream=self.stream)
        self.stream.synchronize()
        res = self.res_h
        live = np.asarray(good_in, dtype=bool)
        x, y, zi = res[:, 0], res[:, 1], res[:, 2]
        out = np.full((self.nb, 3), -1.0)
        out[live, 0], out[live, 1], out[live, 2] = x[live], y[live], zi[live] * self.zstep[live]
        idx = res[:, 3].astype(np.int64)
        H, W = image.shape
        h = self.h
        bad = ((zi > self.S - p.z_hi_margin) | (zi < p.z_lo) | (x < h) | (x > W - h) | (y < h) | (y > H - h)
               | np.isnan(zi + x + y))
        return out, idx, live & ~bad


__all__ = ["Z_METHODS", "GpuKernel"]
