"""Bead tracking: a faithful port of the LabVIEW kernel `Track 1 of N bds xyz-kernel-reentrant.vi`.

Ported from MT_LabVIEW `tools/gpu/ref_numpy.py` (pinned in third_party/MANIFEST), one function per subVI. The
computation, including its quirks, must stay identical to LabVIEW (decisions 0003, 0004, 0008): do not "clean up"
the single-precision steps, the out-of-range baseline index or round-half-even.

Each stage is a slot (decision 0003): `Stages` holds the XY estimator, the radial profile and the Z estimator, so an
alternative can replace one stage and be compared against `CURRENT`.
"""
import dataclasses
from collections.abc import Callable

import numpy as np


# ----------------------------------------------------------------------------------------------------- helpers ---
def lv_round(v):
    """LabVIEW DBL -> I32 coercion / 'To Long Integer' / 'Round To Nearest': round half to even."""
    return int(np.rint(v))


def lv_i32_div(a, b):
    """I32(a / b) as the VIs do it: DBL division then To Long Integer (round half to even)."""
    return lv_round(a / b)


@dataclasses.dataclass(frozen=True)
class Params:
    """Block-diagram constants and precision modes, pinned against the LabVIEW output (see ref_numpy.py)."""
    k_half: float = 0.6        # half-length of the sub-image = I32(cross * k_half)
    arm: int = 10              # 'cross arm width'
    k_end: float = 4.0         # '# of endpoints for normalization' = I32(cross / k_end)
    n_pts: int = 5             # '# of points for parabola'
    end_quirk: bool = True     # prep avg: the "last" endpoints are indexed cross - i (i = 0 reads out of range = 0)
    sgl_avg: bool = True       # average x,y in cross: To SGL per element, sum and divide in single precision
    sgl_rad: bool = False      # radial profile accumulated in SGL (rounding order not emulated; ~1e-4 z accepted 2026-09-07)
    frame2_shifted: bool = True  # find center frame 2 applies its phase shift to the already-shifted spectrum
    z_lo: float = 2.0          # 'Bead is good?' bounds (mt_track.cu v3; agree with every good flag of the recording)
    z_hi_margin: float = 3.0


DEFAULT = Params()


# ------------------------------------------------------------------------------------------------------ XY -----
def sub_image(image, x, y, h):
    """rect coord from center.vi + IMAQ ImageToArray: [x-h, y-h, x+h, y+h], right/bottom exclusive; sub[row=y][col=x]."""
    return image[y - h:y + h, x - h:x + h]


def average_xy_in_cross(sub, xc, yc, cross, arm, sgl=True):
    """tracking-average x,y in cross.vi. 'along x' = per-column mean of the arm rows through the centre,
    'along y' = per-row mean of the arm columns. Each element is converted To SGL before 'Add Array Elements' and the
    sum is divided by the I32 arm width."""
    half = lv_i32_div(cross, 2)
    arm2 = lv_i32_div(arm, 2)
    a = sub[yc - arm2:yc - arm2 + arm, xc - half:xc - half + cross].T
    b = sub[yc - half:yc - half + cross, xc - arm2:xc - arm2 + arm]
    if sgl:
        ax = (a.astype(np.float32).sum(axis=1, dtype=np.float32) / np.float32(arm)).astype(np.float64)
        ay = (b.astype(np.float32).sum(axis=1, dtype=np.float32) / np.float32(arm)).astype(np.float64)
    else:
        ax = a.astype(np.float64).mean(axis=1)
        ay = b.astype(np.float64).mean(axis=1)
    return ax, ay


def prep_avg_profile(profile, cross, n_end, window, quirk=True):
    """tracking-prep avgx,y profiles.vi: base = (sum_{i<n} p[i] + sum_{i<n} p[cross - i]) / (2 n) with the VI's index
    `cross - i` (quirk: i = 0 is out of range -> 0); prepped = (p - base) * window."""
    first = profile[:n_end].sum()
    if quirk:
        last = sum(profile[cross - i] if cross - i < cross else 0.0 for i in range(n_end))
    else:
        last = profile[cross - n_end:].sum()
    base = (first + last) / (2 * n_end)
    return (profile - base) * window


def fit_parabola(corr, n_pts):
    """tracking-fit parabola to avg profile.vi: least-squares order-2 fit around the argmax; vertex -(a1 / a2) / 2."""
    k = int(np.argmax(corr))
    lo = k - int(np.floor(n_pts / 2))
    xs = np.arange(lo, lo + n_pts, dtype=np.float64)
    a2, a1, _ = np.polyfit(xs, corr[lo:lo + n_pts], 2)
    return -(a1 / a2) / 2


def find_avg_profile_center(profile, window_h, start, half, n_pts=5, frame2_shifted=True):
    """tracking-find avg profile center.vi (Croquette's 3-frame discretization removal):
      F = FFT(profile) * window_h ; F2 = F * F
      frame 0: P1 = parabola(|IFFT(F2)| rotated by half) ; r1 = round(P1) ; d1 = P1 - r1
      frame 1: G1 = shift(F2, d1) ; out1 = parabola(G1) - r1
      frame 2: G2 = shift(G1 or F2, out1) ; out2 = parabola(G2) - r1
      result = P1 + out1 + out2 ; shift = (result - half) / 2 ; new centre = start + shift
    shift(S, d)[i] = S[i] * exp(j k d a_i), k = 2 pi / cross, a_i = i for i <= half else i - cross (Polar form)."""
    cross = 2 * half
    F = np.fft.fft(profile) * window_h
    F2 = F * F
    k = 2 * np.pi / cross
    i = np.arange(cross)
    a = np.where(i > half, i - cross, i).astype(np.float64)

    def corr(S):
        return np.roll(np.abs(np.fft.ifft(S)), half)

    def shift(S, d):
        return np.abs(S) * np.exp(1j * (np.angle(S) + k * d * a))

    P1 = fit_parabola(corr(F2), n_pts)
    r1 = lv_round(P1)
    G1 = shift(F2, P1 - r1)
    out1 = fit_parabola(corr(G1), n_pts) - r1
    G2 = shift(G1 if frame2_shifted else F2, out1)
    out2 = fit_parabola(corr(G2), n_pts) - r1
    sh = (P1 + out1 + out2 - half) / 2
    return start + sh, sh


def xy_croquette(sub, h, x_in, y_in, cross, win_rs, win_h, p):
    """XY stage of the current method. Returns (x, y) in image pixels and (sx, sy), the shifts inside the sub-image."""
    half = lv_i32_div(cross, 2)
    n_end = lv_i32_div(cross, p.k_end)
    ax, ay = average_xy_in_cross(sub, h, h, cross, p.arm, p.sgl_avg)
    px = prep_avg_profile(ax, cross, n_end, win_rs, p.end_quirk)
    py = prep_avg_profile(ay, cross, n_end, win_rs, p.end_quirk)
    x, sx = find_avg_profile_center(px, win_h, x_in, half, p.n_pts, p.frame2_shifted)
    y, sy = find_avg_profile_center(py, win_h, y_in, half, p.n_pts, p.frame2_shifted)
    return x, y, sx, sy


# ------------------------------------------------------------------------------------------------------- Z -----
def radial_profile(sub, xc, yc, half, sgl=False):
    """tracking-calculate radial profile-openv2.vi. Window rows/cols start at ceil(y)-half / ceil(x)-half;
    cy = half + (y - ceil y), cx = half + (x - ceil x). For row i: dy = cy - i, c = sqrt(half^2 - dy^2),
    N = I32(ceil(2c)), j0 = I32(ceil(cx - c)); for j = j0 .. j0+N-1: r = sqrt((cx-j)^2 + dy^2), rf = floor r,
    fr = r - rf; sum[rf] += (1-fr) p, w[rf] += 1-fr, sum[rf+1] += fr p, w[rf+1] += fr (out-of-range indices ignored);
    profile = sum / w, held in single precision."""
    cross = 2 * half
    x0 = int(np.ceil(xc)) - half
    y0 = int(np.ceil(yc)) - half
    cx = half + (xc - np.ceil(xc))
    cy = half + (yc - np.ceil(yc))
    win = sub[y0:y0 + cross, x0:x0 + cross].astype(np.float64)
    if not sgl:
        i = np.arange(cross)[:, None]
        dy = cy - i
        c = np.sqrt(half * half - dy * dy)
        N = np.ceil(2 * c).astype(int)
        j0 = np.ceil(cx - c).astype(int)
        kk = np.arange(cross)[None, :]
        j = j0 + kk
        m = (kk < N) & (j >= 0) & (j < cross)
        ii, jj = np.nonzero(m)
        jv = j[ii, jj]
        r = np.sqrt((cx - jv) ** 2 + (cy - ii) ** 2)
        rf = np.floor(r).astype(int)
        fr = r - rf
        pv = win[ii, jv]
        s = np.zeros(half + 2)
        w = np.zeros(half + 2)
        ok = rf < half
        np.add.at(s, rf[ok], (1 - fr[ok]) * pv[ok])
        np.add.at(w, rf[ok], 1 - fr[ok])
        ok = rf + 1 < half
        np.add.at(s, rf[ok] + 1, fr[ok] * pv[ok])
        np.add.at(w, rf[ok] + 1, fr[ok])
        with np.errstate(divide="ignore", invalid="ignore"):
            out = s[:half] / w[:half]
        return np.float32(out).astype(np.float64)
    s = np.zeros(half, dtype=np.float32)
    w = np.zeros(half, dtype=np.float32)
    for i in range(cross):
        dy = cy - i
        dy2 = dy * dy
        c = np.sqrt(half * half - dy2)
        N = int(np.ceil(2 * c))
        j0 = int(np.ceil(cx - c))
        for kk in range(N):
            j = j0 + kk
            if j < 0 or j >= cross:
                continue
            pv = win[i, j]
            r = np.sqrt((cx - j) ** 2 + dy2)
            rf = int(np.floor(r))
            fr = r - rf
            # SGL element + DBL product -> DBL add, coerced back to SGL by Replace Array Subset (one rounding)
            if rf < half:
                s[rf] = np.float32(float(s[rf]) + (1 - fr) * pv)
                w[rf] = np.float32(float(w[rf]) + (1 - fr))
            if rf + 1 < half:
                s[rf + 1] = np.float32(float(s[rf + 1]) + fr * pv)
                w[rf + 1] = np.float32(float(w[rf + 1]) + fr)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (s / w).astype(np.float64)


def prep_i_of_r(radprof, half, forget, cosband):
    """Tracking-prep I of r.vi: mirrored = reverse(profile[1:]) ++ profile (r = 0 at index half-1);
    corkscrew = IFFT(FFT(mirrored) * cosband)[half + forget - 1:]; prepped = Re(corkscrew)."""
    mir = np.concatenate([radprof[1:][::-1], radprof]).astype(complex)
    n = min(len(mir), len(cosband))                    # LabVIEW Multiply on arrays of unequal length -> the shorter
    cork = np.fft.ifft(np.fft.fft(mir)[:n] * cosband[:n])[half + forget - 1:]
    return np.real(cork), cork


def fit_prep_to_cal(prep, real_stack):
    """Tracking-fit prepped I of r to cal.vi: index of the slice with the least sum of squared differences."""
    return int(np.argmin(((real_stack - prep[None, :]) ** 2).sum(axis=1)))


def phase_in_neighborhood(cork, index, ampl_stack, cork_stack, n=5):
    """tracking-calculate phase in neighborhood.vi: slices index-2 .. index+2 (start clamped at 0, mt_track.cu v3 D1);
    w = |c_live| * ampl_cal; theta = arg(c_live / c_cal); phase = sum(w theta) / sum(w)."""
    lo = max(index - 2, 0)
    w = np.abs(cork)[None, :] * ampl_stack[lo:lo + n]
    th = np.angle(cork[None, :] / cork_stack[lo:lo + n])
    return (w * th).sum(axis=1) / w.sum(axis=1)


QUAD_WEIGHTS = np.array([2.0, 4.0, 5.0, 4.0, 2.0])   # the VI's 'Weight' constant


def quad_fit_phase(phases, index, n=5):
    """tracking- quadratic fit to phase nghbrd.vi: weighted order-2 fit of y = i - floor(n/2) over x = phase,
    evaluated at x = 0 -> index + P(0)."""
    xs = np.asarray(phases, dtype=np.float64)
    ys = np.arange(n) - np.floor(n / 2)
    X = np.vstack([xs ** 2, xs, np.ones(n)]).T
    W = np.diag(QUAD_WEIGHTS[:n])
    return index + np.linalg.solve(X.T @ W @ X, X.T @ W @ ys)[2]


def z_phase(rad, half, cal, p):
    """Z stage of the current method. Returns (z_index, slice index); z = z_index * z_step."""
    prep, cork = prep_i_of_r(rad, half, int(cal["forget_radius"]), cal["cosband"])
    idx = fit_prep_to_cal(prep, cal["real"])
    if idx + 2 >= len(cal["real"]):                    # LabVIEW at the stack's upper edge: the fit fails, P(0) = 0
        return float(idx), idx
    return quad_fit_phase(phase_in_neighborhood(cork, idx, cal["ampl"], cal["cork"]), idx), idx


def catmull(R, z):
    """Catmull-Rom interpolation of a stack R (S, n) along its first axis at the fractional index z (ends clamped)."""
    S = len(R)
    i = int(np.floor(z))
    t = z - i
    p0, p1, p2, p3 = (R[min(max(i + k, 0), S - 1)] for k in (-1, 0, 1, 2))
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


GOLDEN = (np.sqrt(5) - 1) / 2
N_ITER = 30                                            # golden section / bisection steps within +-1 slice: 1e-6 slice


def z_spline(rad, half, cal, p):
    """Z stage 'spline' (2026-10-28 bench): the prepped real LUT interpolated along z (Catmull-Rom), the sum of squared
    differences to the live profile minimised by golden section within +-1 slice of the best slice."""
    prep, _ = prep_i_of_r(rad, half, int(cal["forget_radius"]), cal["cosband"])
    R = cal["real"]
    idx = fit_prep_to_cal(prep, R)

    def ssd(z):
        return float(((catmull(R, z) - prep) ** 2).sum())

    lo, hi = max(idx - 1.0, 0.0), min(idx + 1.0, len(R) - 1.0)
    c, d = hi - GOLDEN * (hi - lo), lo + GOLDEN * (hi - lo)
    fc, fd = ssd(c), ssd(d)
    for _ in range(N_ITER):
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - GOLDEN * (hi - lo)
            fc = ssd(c)
        else:
            lo, c, fc = c, d, fd
            d = lo + GOLDEN * (hi - lo)
            fd = ssd(d)
    return (lo + hi) / 2, idx


def z_phase_spline(rad, half, cal, p):
    """Z stage 'phase_spline' (2026-10-29 bench): the current method's phase criterion on a continuous LUT. The complex
    LUT is interpolated along z and theta(z) = sum(w arg(c_live / c_lut(z))) / sum(w) is brought to 0 by bisection
    within +-1 slice of the best slice; without a sign change there it falls back to the 5-point quadratic fit."""
    prep, cork = prep_i_of_r(rad, half, int(cal["forget_radius"]), cal["cosband"])
    C = cal["cork"]
    idx = fit_prep_to_cal(prep, cal["real"])

    def theta(z):
        c = catmull(C, z)
        w = np.abs(cork) * np.abs(c)
        return float((w * np.angle(cork / c)).sum() / w.sum())

    lo, hi = max(idx - 1.0, 0.0), min(idx + 1.0, len(C) - 1.0)
    tlo, thi = theta(lo), theta(hi)
    if tlo * thi > 0:
        return z_phase(rad, half, cal, p)
    for _ in range(N_ITER):
        mid = (lo + hi) / 2
        tm = theta(mid)
        if tm * tlo > 0:
            lo, tlo = mid, tm
        else:
            hi, thi = mid, tm
    return (lo + hi) / 2, idx


Z_METHODS = {"current": z_phase, "spline": z_spline, "phase_spline": z_phase_spline}


def radial_current(sub, xc, yc, half, p):
    return radial_profile(sub, xc, yc, half, p.sgl_rad)


# -------------------------------------------------------------------------------------------------- kernel -----
@dataclasses.dataclass(frozen=True)
class Stages:
    """The swappable stages (decision 0003). Each keeps the signature of the current one."""
    xy: Callable = xy_croquette
    radial: Callable = radial_current
    z: Callable = z_phase


CURRENT = Stages()


def track_bead(image, x_in, y_in, cross, win_rs, win_h, cal, p=DEFAULT, stages=CURRENT):
    """One bead, one frame = the kernel VI's good-bead case. x_in, y_in: the I32 start position.
    cal: dict(forget_radius, z_step, cosband, ampl, cork, real). Returns (x, y, z, slice index, good)."""
    h = lv_round(cross * p.k_half)
    half = lv_i32_div(cross, 2)
    sub = sub_image(image, x_in, y_in, h)
    x, y, sx, sy = stages.xy(sub, h, x_in, y_in, cross, win_rs, win_h, p)
    zi, idx = stages.z(stages.radial(sub, h + sx, h + sy, half, p), half, cal, p)
    H, W = image.shape
    S = len(cal["real"])
    good = not (zi > S - p.z_hi_margin or zi < p.z_lo or x < h or x > W - h or y < h or y > H - h)
    return x, y, zi * float(cal["z_step"]), idx, good


class Tracker:
    """Frame-to-frame state of the main VI: each frame starts from the previous output; a bead flagged bad is output
    as -1 on the next frame, and after any -1 every bead restarts from its calibration position."""

    def __init__(self, xy0, cross, win_rs, win_h, cals, p=DEFAULT, stages=CURRENT):
        self.xy0 = np.asarray(xy0, dtype=np.float64)
        self.cross, self.win_rs, self.win_h, self.cals, self.p, self.stages = cross, win_rs, win_h, cals, p, stages
        self.xy = self.xy0.copy()
        self.good = np.ones(len(cals), dtype=bool)
        self.lost = False

    def step(self, image):
        """Track all beads on one frame. Returns xyz (n, 3), -1.0 for a bead that was flagged bad last frame."""
        if self.lost:
            self.xy = self.xy0.copy()
            self.good[:] = True
        xyz = np.full((len(self.cals), 3), -1.0)
        good = np.zeros(len(self.cals), dtype=bool)
        for b, cal in enumerate(self.cals):
            if not self.good[b]:
                continue
            x, y, z, _, good[b] = track_bead(image, lv_round(self.xy[b, 0]), lv_round(self.xy[b, 1]), self.cross,
                                             self.win_rs, self.win_h, cal, self.p, self.stages)
            xyz[b] = x, y, z
        self.lost = bool((xyz == -1.0).any())
        self.xy = xyz[:, :2].copy()
        self.good = good
        return xyz
