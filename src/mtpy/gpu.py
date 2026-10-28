"""CUDA executor of the Z stage (decision 0002 / 0003: the executor is a swappable slot) with the three Z methods of
track.Z_METHODS, through numba.cuda (no cupy, no C). One thread block per bead: the mirrored profile's band-pass
(a direct DFT, the profile is 119 points), the squared differences to every LUT slice in parallel over the slices,
then the chosen estimator on one thread. XY and the radial profile stay on the CPU (`fast.FastKernel`), whose output
profile is the kernel's input; `GpuKernel` chains the two with FastKernel's `track` signature.
shortcut: shared memory is sized by the constants below (cross <= 256, LUT <= 512 slices), raise them if a LUT exceeds.
"""
import math

import numba
import numpy as np
from numba import cuda

from mtpy import fast
from mtpy.track import DEFAULT, GOLDEN, N_ITER, QUAD_WEIGHTS, Z_METHODS

TPB = 128
MAX_N, MAX_L, MAX_S = 256, 128, 512


@cuda.jit(device=True)
def _clamp(v, lo, hi):
    """numba.cuda has no two-argument min / max."""
    return lo if v < lo else (hi if v > hi else v)  # noqa: FURB136


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
def _ssd_at(prep, real, L, z):
    d = 0.0
    for r in range(L):
        e = _catmull(real, z, r) - prep[r]
        d += e * e
    return d


@cuda.jit(device=True)
def _theta_at(cork, cork_cal, L, z):
    num = den = 0.0
    for r in range(L):
        c = _catmull(cork_cal, z, r)
        w = abs(cork[r]) * abs(c)
        num += w * _angle_ratio(cork[r], c)
        den += w
    return num / den


@cuda.jit(device=True)
def _z_quad(cork, L, idx, ampl, cork_cal, qw):
    S = cork_cal.shape[0]
    if idx + 2 >= S:
        return float(idx)
    lo = idx - 2 if idx > 2 else 0
    ph = cuda.local.array(5, numba.float64)
    for q in range(5):
        num = den = 0.0
        for r in range(L):
            wq = abs(cork[r]) * ampl[lo + q, r]
            num += wq * _angle_ratio(cork[r], cork_cal[lo + q, r])
            den += wq
        ph[q] = num / den
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
def _z_spline(prep, L, idx, real):
    lo = _clamp(idx - 1.0, 0.0, real.shape[0] - 1.0)
    hi = _clamp(idx + 1.0, 0.0, real.shape[0] - 1.0)
    c, d = hi - GOLDEN * (hi - lo), lo + GOLDEN * (hi - lo)
    fc, fd = _ssd_at(prep, real, L, c), _ssd_at(prep, real, L, d)
    for _ in range(N_ITER):
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - GOLDEN * (hi - lo)
            fc = _ssd_at(prep, real, L, c)
        else:
            lo, c, fc = c, d, fd
            d = lo + GOLDEN * (hi - lo)
            fd = _ssd_at(prep, real, L, d)
    return (lo + hi) / 2


@cuda.jit(device=True)
def _z_phase_spline(cork, L, idx, ampl, cork_cal, qw):
    lo = _clamp(idx - 1.0, 0.0, cork_cal.shape[0] - 1.0)
    hi = _clamp(idx + 1.0, 0.0, cork_cal.shape[0] - 1.0)
    tlo, thi = _theta_at(cork, cork_cal, L, lo), _theta_at(cork, cork_cal, L, hi)
    if tlo * thi > 0:
        return _z_quad(cork, L, idx, ampl, cork_cal, qw)
    for _ in range(N_ITER):
        mid = (lo + hi) / 2
        tm = _theta_at(cork, cork_cal, L, mid)
        if tm * tlo > 0:
            lo, tlo = mid, tm
        else:
            hi, thi = mid, tm
    return (lo + hi) / 2


@cuda.jit
def _z_kernel(rad, half, forget, cosband, real, ampl, cork_cal, nlen, qw, method, out, idx_out):
    b = cuda.blockIdx.x
    t = cuda.threadIdx.x
    mir = cuda.shared.array(MAX_N, numba.float64)
    F = cuda.shared.array(MAX_N, numba.complex128)
    cork = cuda.shared.array(MAX_L, numba.complex128)
    prep = cuda.shared.array(MAX_L, numba.float64)
    d = cuda.shared.array(MAX_S, numba.float64)
    nmir = 2 * half - 1
    n = nmir if nmir < cosband.shape[1] else cosband.shape[1]  # noqa: FURB136
    L = nlen[b]
    S = real.shape[1]
    for i in range(t, nmir, TPB):                      # mirrored profile: reverse(rad[1:]) ++ rad
        mir[i] = rad[b, half - 1 - i] if i < half - 1 else rad[b, i - (half - 1)]
    cuda.syncthreads()
    for k in range(t, n, TPB):                         # band-passed spectrum (forward DFT of the first n points)
        sr = si = 0.0
        for i in range(n):
            a = -2.0 * math.pi * i * k / n
            sr += mir[i] * math.cos(a)
            si += mir[i] * math.sin(a)
        F[k] = (sr + 1j * si) * cosband[b, k]
    cuda.syncthreads()
    for r in range(t, L, TPB):                         # corkscrew = IDFT[half + forget - 1 :]
        m = r + half + forget[b] - 1
        sr = si = 0.0
        for k in range(n):
            a = 2.0 * math.pi * k * m / n
            sr += F[k].real * math.cos(a) - F[k].imag * math.sin(a)
            si += F[k].real * math.sin(a) + F[k].imag * math.cos(a)
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
    if t == 0:
        best, idx = d[0], 0
        for s in range(1, S):
            if d[s] < best:
                best, idx = d[s], s
        idx_out[b] = idx
        if method == 1:
            out[b] = _z_spline(prep, L, idx, real[b])
        elif method == 2:
            out[b] = _z_phase_spline(cork, L, idx, ampl[b], cork_cal[b], qw)
        else:
            out[b] = _z_quad(cork, L, idx, ampl[b], cork_cal[b], qw)


class GpuZ:
    """The Z stage for a fixed bead set on the GPU: `z(rad)` takes the radial profiles (nb, half) and returns
    (z index (nb,), slice index (nb,)); z = index * z_step as in the CPU executor."""

    def __init__(self, half, cals, z_method="current"):
        fk = fast.FastKernel(2 * half, np.zeros(2 * half), np.zeros(2 * half), cals, z_method=z_method)
        if 2 * half - 1 > MAX_N or fk.real.shape[2] > MAX_L or fk.real.shape[1] > MAX_S:
            raise ValueError("LUT larger than mtpy.gpu's shared-memory constants")
        self.half, self.method = half, fk.z_method
        self.forget, self.nlen = cuda.to_device(fk.forget), cuda.to_device(fk.nlen)
        self.cosband, self.real = cuda.to_device(fk.cosband), cuda.to_device(fk.real)
        self.ampl, self.cork = cuda.to_device(fk.ampl), cuda.to_device(fk.cork)
        self.qw = cuda.to_device(QUAD_WEIGHTS)
        self.nb = len(cals)
        self.rad_d = cuda.device_array((self.nb, half))
        self.out_d, self.idx_d = cuda.device_array(self.nb), cuda.device_array(self.nb, dtype=np.int64)

    def z(self, rad):
        self.rad_d.copy_to_device(np.ascontiguousarray(rad, dtype=np.float64))
        _z_kernel[self.nb, TPB](self.rad_d, self.half, self.forget, self.cosband, self.real, self.ampl, self.cork,
                                self.nlen, self.qw, self.method, self.out_d, self.idx_d)
        return self.out_d.copy_to_host(), self.idx_d.copy_to_host()


class GpuKernel(fast.FastKernel):
    """FastKernel with the Z stage on the GPU: same `track(image, xin, yin, good_in)` and the same results."""

    def __init__(self, cross, win_rs, win_h, cals, p=DEFAULT, z_method="current"):
        super().__init__(cross, win_rs, win_h, cals, p, z_method)
        self.gpu = GpuZ(cross // 2, cals, z_method)
        self.S = self.real.shape[1]

    def track(self, image, xin, yin, good_in):
        nb = len(xin)
        out = np.empty((nb, 3))
        idx = np.empty(nb, dtype=np.int64)
        good = np.empty(nb, dtype=np.bool_)
        rad = np.zeros((nb, self.cross // 2))
        p = self.p
        fast._track(image, np.asarray(xin, dtype=np.int64), np.asarray(yin, dtype=np.int64),
                    np.asarray(good_in, dtype=np.bool_), self.cross, self.h, p.arm, self.n_end, p.n_pts, p.end_quirk,
                    p.frame2_shifted, p.z_lo, p.z_hi_margin, self.win_rs, self.win_h, self.forget, self.zstep,
                    self.cosband, self.real, self.ampl, self.cork, self.nlen, QUAD_WEIGHTS, -1, out, idx, good, rad)
        zi, zidx = self.gpu.z(rad)
        live = np.asarray(good_in, dtype=bool)
        out[live, 2] = zi[live] * self.zstep[live]
        idx[live] = zidx[live]
        H, W = image.shape
        x, y, h = out[:, 0], out[:, 1], self.h
        bad = ((zi > self.S - p.z_hi_margin) | (zi < p.z_lo) | (x < h) | (x > W - h) | (y < h) | (y > H - h)
               | np.isnan(zi + x + y))
        good[live] = ~bad[live]
        return out, idx, good


__all__ = ["Z_METHODS", "GpuKernel", "GpuZ"]
