"""numba executor of the current tracking method (decision 0002): all beads of one frame in one call, beads in
parallel, without the GIL. Same steps and constants as `track.py`, which stays the reference; the test
tests/test_fast.py holds the two together. FFTs come from rocket-fft (numba bindings of NumPy's own pocketfft).
"""
import numba
import numpy as np
import rocket_fft  # noqa: F401  (registers np.fft for numba)

from mtpy.track import DEFAULT, QUAD_WEIGHTS, lv_i32_div, lv_round


@numba.njit(cache=True, nogil=True)
def _parabola(c, n_pts):
    """Vertex of the least-squares parabola through n_pts points around the argmax (closed form, centred abscissa)."""
    k = np.argmax(c)
    m = n_pts // 2
    if k - m < 0 or k + m >= c.size:
        return np.nan
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


@numba.njit(cache=True, nogil=True)
def _center(profile, win_h, half, n_pts, frame2_shifted):
    cross = 2 * half
    F = np.fft.fft(profile.astype(np.complex128)) * win_h
    F2 = F * F
    kk = 2 * np.pi / cross
    a = np.empty(cross)
    for i in range(cross):
        a[i] = i - cross if i > half else i

    P1 = _parabola(np.roll(np.abs(np.fft.ifft(F2)), half), n_pts)
    r1 = np.rint(P1)
    G1 = np.abs(F2) * np.exp(1j * (np.angle(F2) + kk * (P1 - r1) * a))
    out1 = _parabola(np.roll(np.abs(np.fft.ifft(G1)), half), n_pts) - r1
    S = G1 if frame2_shifted else F2
    G2 = np.abs(S) * np.exp(1j * (np.angle(S) + kk * out1 * a))
    out2 = _parabola(np.roll(np.abs(np.fft.ifft(G2)), half), n_pts) - r1
    return (P1 + out1 + out2 - half) / 2


@numba.njit(cache=True, nogil=True)
def _prep(profile, cross, n_end, window, quirk):
    first = 0.0
    for i in range(n_end):
        first += profile[i]
    last = 0.0
    for i in range(n_end):
        if quirk:
            if i > 0:                                  # index cross - 0 is out of range in the VI -> 0
                last += profile[cross - i]
        else:
            last += profile[cross - n_end + i]
    return (profile - (first + last) / (2 * n_end)) * window


@numba.njit(cache=True, nogil=True)
def _radial(sub, xc, yc, half):
    """Same pixel set and the same summation order as track.radial_profile (two passes, like its two np.add.at)."""
    cross = 2 * half
    x0 = int(np.ceil(xc)) - half
    y0 = int(np.ceil(yc)) - half
    cx = half + (xc - np.ceil(xc))
    cy = half + (yc - np.ceil(yc))
    s = np.zeros(half)
    w = np.zeros(half)
    for pas in range(2):
        for i in range(cross):
            dy = cy - i
            c = np.sqrt(half * half - dy * dy)
            N = int(np.ceil(2 * c))
            j0 = int(np.ceil(cx - c))
            for kk in range(min(N, cross)):
                j = j0 + kk
                if j < 0 or j >= cross:
                    continue
                r = np.sqrt((cx - j) ** 2 + (cy - i) ** 2)
                rf = int(np.floor(r))
                fr = r - rf
                p = sub[y0 + i, x0 + j]
                if pas == 0 and rf < half:
                    s[rf] += (1 - fr) * p
                    w[rf] += 1 - fr
                elif pas == 1 and rf + 1 < half:
                    s[rf + 1] += fr * p
                    w[rf + 1] += fr
    return (s / w).astype(np.float32).astype(np.float64)


@numba.njit(cache=True, nogil=True)
def _solve3(A, b):
    """Gaussian elimination with partial pivoting for the 3 x 3 normal equations."""
    A = A.copy()
    b = b.copy()
    for col in range(3):
        piv = col + np.argmax(np.abs(A[col:, col]))
        if piv != col:
            for j in range(3):
                A[col, j], A[piv, j] = A[piv, j], A[col, j]
            b[col], b[piv] = b[piv], b[col]
        for r in range(col + 1, 3):
            f = A[r, col] / A[col, col]
            for j in range(col, 3):
                A[r, j] -= f * A[col, j]
            b[r] -= f * b[col]
    x = np.zeros(3)
    for r in range(2, -1, -1):
        acc = b[r]
        for j in range(r + 1, 3):
            acc -= A[r, j] * x[j]
        x[r] = acc / A[r, r]
    return x


@numba.njit(cache=True, nogil=True)
def _z(rad, half, forget, cosband, real, ampl, cork_cal, qw):
    nmir = 2 * half - 1
    mir = np.empty(nmir, dtype=np.complex128)
    for i in range(half - 1):
        mir[i] = rad[half - 1 - i]
    mir[half - 1:] = rad
    n = min(nmir, cosband.size)
    cork = np.fft.ifft(np.fft.fft(mir)[:n] * cosband[:n])[half + forget - 1:]
    prep = cork.real
    S = real.shape[0]
    best, idx = np.inf, 0
    for s in range(S):
        d = 0.0
        for r in range(prep.size):
            e = real[s, r] - prep[r]
            d += e * e
        if d < best:
            best, idx = d, s
    if idx + 2 >= S:                                   # LabVIEW at the stack's upper edge: P(0) = 0
        return float(idx), idx
    lo = max(idx - 2, 0)
    ph = np.empty(5)
    for q in range(5):
        num = den = 0.0
        for r in range(cork.size):
            wq = np.abs(cork[r]) * ampl[lo + q, r]
            num += wq * np.angle(cork[r] / cork_cal[lo + q, r])
            den += wq
        ph[q] = num / den
    A = np.zeros((3, 3))
    bb = np.zeros(3)
    for q in range(5):
        row = (ph[q] * ph[q], ph[q], 1.0)
        y = q - 2.0
        for i in range(3):
            bb[i] += qw[q] * row[i] * y
            for j in range(3):
                A[i, j] += qw[q] * row[i] * row[j]
    return idx + _solve3(A, bb)[2], idx


@numba.njit(cache=True, nogil=True, parallel=True)
def _track(image, xin, yin, good_in, cross, h, arm, n_end, n_pts, quirk, frame2_shifted, z_lo, z_hi_margin,
           win_rs, win_h, forget, zstep, cosband, real, ampl, cork, nlen, qw, out, idx_out, good_out):
    half = cross // 2
    arm2 = int(np.rint(arm / 2))
    H, W = image.shape
    for b in numba.prange(xin.size):
        if not good_in[b]:
            out[b, :] = -1.0
            idx_out[b] = -1
            good_out[b] = False
            continue
        sub = image[yin[b] - h:yin[b] + h, xin[b] - h:xin[b] + h]
        ax = np.empty(cross)
        ay = np.empty(cross)
        for i in range(cross):                         # To SGL per element, SGL sum, SGL divide (integer pixels: exact)
            sx_ = np.float32(0.0)
            sy_ = np.float32(0.0)
            for t in range(arm):
                sx_ += np.float32(sub[h - arm2 + t, h - half + i])
                sy_ += np.float32(sub[h - half + i, h - arm2 + t])
            ax[i] = sx_ / np.float32(arm)
            ay[i] = sy_ / np.float32(arm)
        sx = _center(_prep(ax, cross, n_end, win_rs, quirk), win_h, half, n_pts, frame2_shifted)
        sy = _center(_prep(ay, cross, n_end, win_rs, quirk), win_h, half, n_pts, frame2_shifted)
        x = xin[b] + sx
        y = yin[b] + sy
        L = nlen[b]
        zi, idx = _z(_radial(sub, h + sx, h + sy, half), half, forget[b], cosband[b], real[b, :, :L], ampl[b, :, :L],
                     cork[b, :, :L], qw)
        S = real.shape[1]
        bad = zi > S - z_hi_margin or zi < z_lo or x < h or x > W - h or y < h or y > H - h or np.isnan(zi + x + y)
        out[b, 0], out[b, 1], out[b, 2] = x, y, zi * zstep[b]
        idx_out[b] = idx
        good_out[b] = not bad


class FastKernel:
    """All beads of a frame at once. The calibration clusters are packed once; `track` is then one numba call."""

    def __init__(self, cross, win_rs, win_h, cals, p=DEFAULT):
        nb = len(cals)
        S = len(cals[0]["real"])
        L = max(c["real"].shape[1] for c in cals)
        self.real = np.zeros((nb, S, L))
        self.ampl = np.zeros((nb, S, L))
        self.cork = np.ones((nb, S, L), dtype=np.complex128)
        for b, c in enumerate(cals):
            n = c["real"].shape[1]
            self.real[b, :, :n], self.ampl[b, :, :n], self.cork[b, :, :n] = c["real"], c["ampl"], c["cork"]
        self.nlen = np.array([c["real"].shape[1] for c in cals], dtype=np.int64)
        self.forget = np.array([int(c["forget_radius"]) for c in cals], dtype=np.int64)
        self.zstep = np.array([float(c["z_step"]) for c in cals])
        self.cosband = np.array([np.asarray(c["cosband"], dtype=np.complex128) for c in cals])
        self.win_rs, self.win_h = np.asarray(win_rs, dtype=np.float64), np.asarray(win_h, dtype=np.complex128)
        self.cross, self.p = cross, p
        self.h = lv_round(cross * p.k_half)
        self.n_end = lv_i32_div(cross, p.k_end)
        if p.sgl_avg is not True or p.sgl_rad:
            raise ValueError("FastKernel implements the default precision modes only")

    def track(self, image, xin, yin, good_in):
        """image: the camera frame as it comes (uint8 or float64); xin, yin: I32 start positions; returns (xyz (nb, 3), slice index (nb,), good (nb,))."""
        nb = len(xin)
        out = np.empty((nb, 3))
        idx = np.empty(nb, dtype=np.int64)
        good = np.empty(nb, dtype=np.bool_)
        p = self.p
        _track(image, np.asarray(xin, dtype=np.int64), np.asarray(yin, dtype=np.int64),
               np.asarray(good_in, dtype=np.bool_), self.cross, self.h, p.arm, self.n_end, p.n_pts, p.end_quirk,
               p.frame2_shifted, p.z_lo, p.z_hi_margin, self.win_rs, self.win_h, self.forget, self.zstep,
               self.cosband, self.real, self.ampl, self.cork, self.nlen, QUAD_WEIGHTS, out, idx, good)
        return out, idx, good
