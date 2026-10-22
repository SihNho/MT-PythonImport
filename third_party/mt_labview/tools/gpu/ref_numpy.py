"""ref_numpy.py - float64 NumPy reference of the bead-tracking kernel `Track 1 of N bds xyz-kernel-reentrant.vi`, one
function per subVI, written from the WIRING READ of the VIs (tools/bench/spec_wiring*.json, decoded in
docs/gpu-backend.md) with the Saleh-lab C port as a reading aid.  Rule 1a: the VI's computation, step by step.

Inputs the kernel receives from LabVIEW (and the CUDA DLL will receive unchanged): the sub-image, integer starting x/y,
cross size, the two cosine windows (make both cosine bandpass.vi) and the per-bead calibration cluster
(forget radius, z step, cosine bandpass, amplitudes, corkscrews, real, # slices) - captured by
tools/bench/capture_harness_inputs.py into tools/gpu/harness_inputs.npz.

Unknown block-diagram CONSTANTS (not readable by the ops yet) are parameters of `Params`; they are pinned by the numeric
sweep in `sweep()` against the LabVIEW reference (tools/gpu/fixture.read_reference) and then frozen in DEFAULT.
"""
import dataclasses
import numpy as np

# ----------------------------------------------------------------------------------------------------- helpers ---
def lv_round(v):
    """LabVIEW DBL -> I32 coercion / 'To Long Integer' / 'Round To Nearest': round half to even."""
    return int(np.rint(v))


def lv_i32_div(a, b):
    """I32(a / b) as the VIs do it: DBL division then To Long Integer (round half to even)."""
    return lv_round(a / b)


@dataclasses.dataclass
class Params:
    k_half: float = 0.6        # kernel: half-length of pixmap = I32(cross * k_half)                   (const w896)
    arm: int = 10              # kernel: 'cross arm width' constant                                    (const w985)
    k_end: float = 4.0         # kernel: '# of endpoints for normalization' = I32(cross / k_end)       (const w966)
    n_pts: int = 5             # find center: '# of points for parabola' constants (w275, w394, w1008)
    orient: str = "yx"         # sub-image array orientation: "yx" = [row=y][col=x] (verified; "xy" kept for tests only)
    end_quirk: bool = True     # prep avg: the "last" endpoints are indexed cross - i (i = 0 reads out of range = 0)
    sgl_avg: bool = True       # average x,y in cross: per-element To SGL, sum and divide in single precision
    sgl_rad: bool = False      # radial profile: LabVIEW holds it in SGL (rounding order not emulated: user accepted ~1e-4 z, 2026-09-07)
    frame2_shifted: bool = True  # find center frame 2 applies its phase shift to the already-shifted spectrum


DEFAULT = Params()


# ------------------------------------------------------------------------------------------------------ XY -----
def sub_image(image, x, y, h, orient):
    """rect coord from center.vi + Omars IMAQ ImageToArray: rectangle [x-h, y-h, x+h, y+h] (right/bottom exclusive)."""
    sub = image[y - h:y + h, x - h:x + h]
    return sub.T if orient == "xy" else sub


def average_xy_in_cross(sub, xc, yc, cross, arm, sgl=True):
    """tracking-average x,y in cross.vi.  half = I32(cross/2), arm2 = I32(arm/2).
    'along x' = per-row mean of sub[xc-half : +cross, yc-arm2 : +arm]  (rows get the cross length - see docs);
    'along y' = per-row mean of transpose(sub[xc-arm2 : +arm, yc-half : +cross]).
    Each element is converted To SGL before 'Add Array Elements' and the sum is divided by the I32 arm width."""
    half = lv_i32_div(cross, 2); arm2 = lv_i32_div(arm, 2)
    # sub[row = y][col = x] (verified numerically 2026-09-07: XY matches to 5e-8 px AND the radial profile centred with
    # the same convention reproduces z; the Terminals[] order of the 2D Array Subset is NOT row-then-column)
    a = sub[yc - arm2:yc - arm2 + arm, xc - half:xc - half + cross].T      # 'along x': mean over the arm rows, per column
    b = sub[yc - half:yc - half + cross, xc - arm2:xc - arm2 + arm]        # 'along y': mean over the arm columns, per row
    if sgl:
        ax = (a.astype(np.float32).sum(axis=1, dtype=np.float32) / np.float32(arm)).astype(np.float64)
        ay = (b.astype(np.float32).sum(axis=1, dtype=np.float32) / np.float32(arm)).astype(np.float64)
    else:
        ax = a.astype(np.float64).mean(axis=1); ay = b.astype(np.float64).mean(axis=1)
    return ax, ay


def prep_avg_profile(profile, cross, n_end, window, quirk=True):
    """tracking-prep avgx,y profiles.vi: base = (sum_{i<n} p[i] + sum_{i<n} p[cross - i]) / (2 n) with the VI's
    index `cross - i` (quirk: i = 0 is out of range -> 0); prepped = (p - base) * window."""
    first = profile[:n_end].sum()
    if quirk:
        last = sum(profile[cross - i] if cross - i < cross else 0.0 for i in range(n_end))
    else:
        last = profile[cross - n_end:].sum()
    base = (first + last) / (2 * n_end)
    return (profile - base) * window


def fit_parabola(corr, n_pts):
    """tracking-fit parabola to avg profile.vi: start = argmax - I32(floor(n/2)); X = start + i, Y = corr[start:start+n];
    General Polynomial Fit (order 2) -> coefficients a0 + a1 x + a2 x^2; result = -(a1 / a2) / 2."""
    k = int(np.argmax(corr))
    lo = k - int(np.floor(n_pts / 2))
    xs = np.arange(lo, lo + n_pts, dtype=np.float64); ys = corr[lo:lo + n_pts]
    a2, a1, a0 = np.polyfit(xs, ys, 2)                       # least squares; the VI's GPF is least squares too (SVD)
    return -(a1 / a2) / 2


def find_avg_profile_center(profile, window_h, start, half, n_pts=5, frame2_shifted=True):
    """tracking-find avg profile center.vi (3-frame Stacked Sequence = Croquette's discretization removal):
      F  = FFT(profile) * window_h ;  F2 = F * F ;  k = 2*pi / (2*half)
      frame 0: c0 = |IFFT(F2)| rotated by half ; P1 = parabola(c0) ; r1 = round(P1) ; d1 = P1 - r1
      frame 1: G1 = shift(F2, d1) ; c1 = |IFFT(G1)| rotated ; P2 = parabola(c1) ; out1 = P2 - r1
      frame 2: G2 = shift(G1 or F2, out1) ; c2 = |IFFT(G2)| rotated ; P3 = parabola(c2) ; out2 = P3 - r1
      result = P1 + out1 + out2 ; shift = (result - half) / 2 ; new centre = start + shift
    shift(S, d)[i] = S[i] * exp(j * k * d * a_i),  a_i = i for i <= half else i - cross  (Polar form in the VI)."""
    cross = 2 * half
    F = np.fft.fft(profile) * window_h
    F2 = F * F
    k = 2 * np.pi / cross
    i = np.arange(cross); a = np.where(i > half, i - cross, i).astype(np.float64)

    def corr(S):
        return np.roll(np.abs(np.fft.ifft(S)), half)          # Rotate 1D Array by n=half: last n elements first

    def shift(S, d):
        r = np.abs(S); th = np.angle(S) + k * d * a
        return r * np.exp(1j * th)

    P1 = fit_parabola(corr(F2), n_pts)
    r1 = lv_round(P1); d1 = P1 - r1
    G1 = shift(F2, d1)
    P2 = fit_parabola(corr(G1), n_pts); out1 = P2 - r1
    G2 = shift(G1 if frame2_shifted else F2, out1)
    P3 = fit_parabola(corr(G2), n_pts); out2 = P3 - r1
    result = P1 + out1 + out2
    sh = (result - half) / 2
    return start + sh, sh, (P1, P2, P3)


# ------------------------------------------------------------------------------------------------------- Z -----
def radial_profile(sub, xc, yc, half, sgl=False):
    """tracking-calculate radial profile-openv2.vi.  cross = 2*half; window rows/cols start at ceil(y)-half / ceil(x)-half;
    cy = half + (y - ceil y), cx = half + (x - ceil x).  For row i: dy = cy - i, c = sqrt(half^2 - dy^2),
    N = I32(ceil(2c)), j0 = I32(ceil(cx - c)); for j = j0 .. j0+N-1: r = sqrt((cx-j)^2 + dy^2), rf = floor r, fr = r - rf;
    sum[rf] += (1-fr)*p, w[rf] += 1-fr, sum[rf+1] += fr*p, w[rf+1] += fr (out-of-range indices are ignored);
    profile = DBL(sum / w)."""
    cross = 2 * half
    x0 = int(np.ceil(xc)) - half; y0 = int(np.ceil(yc)) - half
    cx = half + (xc - np.ceil(xc)); cy = half + (yc - np.ceil(yc))
    win = sub[y0:y0 + cross, x0:x0 + cross].astype(np.float64)
    if not sgl:                                              # vectorised double-precision version (same pixel set)
        i = np.arange(cross)[:, None]; dy = cy - i; c = np.sqrt(half * half - dy * dy)
        N = np.ceil(2 * c).astype(int); j0 = np.ceil(cx - c).astype(int)
        kk = np.arange(cross)[None, :]; j = j0 + kk; m = (kk < N) & (j >= 0) & (j < cross)
        ii, jj = np.nonzero(m); jv = j[ii, jj]
        r = np.sqrt((cx - jv) ** 2 + (cy - ii) ** 2); rf = np.floor(r).astype(int); fr = r - rf; p = win[ii, jv]
        s = np.zeros(half + 2); w = np.zeros(half + 2)
        ok = rf < half; np.add.at(s, rf[ok], (1 - fr[ok]) * p[ok]); np.add.at(w, rf[ok], 1 - fr[ok])
        ok = rf + 1 < half; np.add.at(s, rf[ok] + 1, fr[ok] * p[ok]); np.add.at(w, rf[ok] + 1, fr[ok])
        with np.errstate(divide="ignore", invalid="ignore"):
            out = s[:half] / w[:half]
        return np.float32(out).astype(np.float64)            # LabVIEW's profile is single precision (verified 2026-09-07)
    dt = np.float32 if sgl else np.float64
    s = np.zeros(half, dtype=dt); w = np.zeros(half, dtype=dt)
    for i in range(cross):
        dy = cy - i; dy2 = dy * dy
        c = np.sqrt(half * half - dy2)
        N = int(np.ceil(2 * c)); j0 = int(np.ceil(cx - c))
        row = win[i]
        for kk in range(N):
            j = j0 + kk
            if j < 0 or j >= cross:
                continue                                   # Index Array out of range -> 0 * weights (contributes nothing)
            p = row[j]
            dx = cx - j
            r = np.sqrt(dx * dx + dy2)
            rf = int(np.floor(r)); fr = r - rf
            # LabVIEW: SGL array element + DBL product -> DBL add, coerced to SGL by Replace Array Subset (one rounding)
            if rf < half:
                s[rf] = dt(float(s[rf]) + (1 - fr) * p); w[rf] = dt(float(w[rf]) + (1 - fr))
            if rf + 1 < half:
                s[rf + 1] = dt(float(s[rf + 1]) + fr * p); w[rf + 1] = dt(float(w[rf + 1]) + fr)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (s / w).astype(np.float64)                     # SGL / SGL -> SGL, then To DBL


def prep_i_of_r(radprof, half, forget, cosband):
    """Tracking-prep I of r.vi: mirrored = reverse(profile[1:]) ++ profile (length 2*half-1, r = 0 at index half-1);
    corkscrew = IFFT(FFT(mirrored) * cosband)[half + forget - 1 :]  (r = forget .. half-1); prepped = Re(corkscrew)."""
    mir = np.concatenate([radprof[1:][::-1], radprof]).astype(complex)
    n = min(len(mir), len(cosband))                              # LabVIEW Multiply on arrays of unequal length -> shorter
    out = np.fft.ifft(np.fft.fft(mir)[:n] * cosband[:n])
    cork = out[half + forget - 1:]
    return np.real(cork), cork


def fit_prep_to_cal(prep, real_stack):
    """Tracking-fit prepped I of r to cal.vi: index of the slice with the least sum of squared differences."""
    d = ((real_stack - prep[None, :]) ** 2).sum(axis=1)
    return int(np.argmin(d))


def phase_in_neighborhood(cork, index, ampl_stack, cork_stack, n=5):
    """tracking-calculate phase in neighborhood.vi: slices index-2 .. index+2; w = |c_live| * ampl_cal;
    theta = arg(c_live / c_cal); phase = sum(w theta) / sum(w)."""
    lo = index - 2
    w = np.abs(cork)[None, :] * ampl_stack[lo:lo + n]
    th = np.angle(cork[None, :] / cork_stack[lo:lo + n])
    return (w * th).sum(axis=1) / w.sum(axis=1)


QUAD_WEIGHTS = np.array([2.0, 4.0, 5.0, 4.0, 2.0])   # the VI's 'Weight' constant (identified 2026-09-07 from 10 probes, 1.5e-9)


def quad_fit_phase(phases, index, n=5):
    """tracking- quadratic fit to phase nghbrd.vi: WEIGHTED General Polynomial Fit (order 2, weights [2,4,5,4,2] on the
    squared residuals) of y = i - floor(n/2) over x = phase, evaluated at x = 0 (Polynomial Evaluation) -> index + P(0)."""
    xs = np.asarray(phases, dtype=np.float64); ys = np.arange(n) - np.floor(n / 2)
    X = np.vstack([xs ** 2, xs, np.ones(n)]).T; W = np.diag(QUAD_WEIGHTS[:n])
    c = np.linalg.solve(X.T @ W @ X, X.T @ W @ ys)
    return index + c[2]


# -------------------------------------------------------------------------------------------------- kernel -----
def track_bead(image, x_in, y_in, cross, win_rs, win_h, cal, p=DEFAULT):
    """One bead, one frame = the kernel VI's good-bead case.  x_in/y_in: the I32 the kernel receives (the harness
    coerces the DBL x,y with round-half-even).  cal: dict(forget_radius, z_step, cosband, ampl, cork, real, n_slices).
    Returns dict(x, y, z, index, z_index, intermediates)."""
    h = lv_round(cross * p.k_half)
    half = lv_i32_div(cross, 2)
    n_end = lv_i32_div(cross, p.k_end)
    sub = sub_image(image, x_in, y_in, h, p.orient)
    ax, ay = average_xy_in_cross(sub, h, h, cross, p.arm, p.sgl_avg)
    px = prep_avg_profile(ax, cross, n_end, win_rs, p.end_quirk)
    py = prep_avg_profile(ay, cross, n_end, win_rs, p.end_quirk)
    x_new, sx, Px = find_avg_profile_center(px, win_h, x_in, half, p.n_pts, p.frame2_shifted)
    y_new, sy, Py = find_avg_profile_center(py, win_h, y_in, half, p.n_pts, p.frame2_shifted)
    rad = radial_profile(sub, h + sx, h + sy, half, p.sgl_rad)
    forget = int(cal["forget_radius"])
    prep, cork = prep_i_of_r(rad, half, forget, cal["cosband"])
    idx = fit_prep_to_cal(prep, cal["real"])
    ph = phase_in_neighborhood(cork, idx, cal["ampl"], cal["cork"])
    zi = quad_fit_phase(ph, idx)
    return {"x": x_new, "y": y_new, "z": zi * float(cal["z_step"]), "index": idx, "z_index": zi,
            "ax": ax, "ay": ay, "px": px, "py": py, "rad": rad, "prep": prep, "phases": ph, "P": (Px, Py)}


def load_inputs(path=None):
    import os
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness_inputs.npz")
    z = np.load(path)
    nb = max(int(k[1]) for k in z.files if k.startswith("b") and k[1].isdigit()) + 1
    cals = []
    for b in range(nb):
        c = {n: z[f"b{b}_{n}"] for n in ("forget_radius", "z_step", "cosband", "ampl", "cork", "real", "n_slices")}
        if c["cork"].ndim == 3:                                   # COM delivers complex as (re, im) pairs
            c["cork"] = c["cork"][..., 0] + 1j * c["cork"][..., 1]
        if c["cosband"].ndim == 2:
            c["cosband"] = c["cosband"][:, 0] + 1j * c["cosband"][:, 1]
        cals.append(c)
    return z["realspace"], z["hilbert"], cals


def check_frame(frame, p=DEFAULT, beads=range(5), state=None, verbose=True):
    """Run all beads on one fixture frame from the reference's own inputs and report |dx|,|dy|,|dz| vs the reference."""
    from fixture import read_cal, read_image, read_reference
    ref = read_reference(); rows = ref["frames"]
    i = next(k for k, r in enumerate(rows) if r["frame"] == frame)
    row = rows[i]
    if state is None:
        if i == 0:
            xyz_in = read_cal()["xy"].reshape(-1)
            xyz_in = np.array([[x, y] for x, y in read_cal()["xy"]])
        else:
            prev = rows[i - 1]["ff"]
            lost = any(v == -1.0 for v in prev)
            xyz_in = read_cal()["xy"] if lost else np.array(prev).reshape(-1, 3)[:, :2]
    else:
        xyz_in = state
    win_rs, win_h, cals = load_inputs()
    img = read_image(frame); cross = 120
    errs = []
    for b in beads:
        x_in, y_in = lv_round(xyz_in[b][0]), lv_round(xyz_in[b][1])
        r = track_bead(img, x_in, y_in, cross, win_rs, win_h, cals[b], p)
        ex, ey, ez = abs(r["x"] - row["ff"][3 * b]), abs(r["y"] - row["ff"][3 * b + 1]), abs(r["z"] - row["ff"][3 * b + 2])
        errs.append((ex, ey, ez, r["index"], row["pos"][b]))
        if verbose:
            print(f"  frame {frame} bead {b}: x {r['x']:.6f} ref {row['ff'][3*b]:.6f} | y {r['y']:.6f} ref {row['ff'][3*b+1]:.6f} | "
                  f"z {r['z']:.6f} ref {row['ff'][3*b+2]:.6f} | idx {r['index']} ref {row['pos'][b]}")
    return errs


def sweep(frame=4):
    import itertools
    best = []
    for k_half, arm, k_end, orient, quirk, sgl in itertools.product((0.6, 0.5, 0.75, 1.0), (10, 20, 24, 30), (4.0, 2.0, 8.0), ("yx", "xy"), (True, False), (True, False)):
        p = Params(k_half=k_half, arm=arm, k_end=k_end, orient=orient, end_quirk=quirk, sgl_avg=sgl)
        try:
            e = check_frame(frame, p, verbose=False)
        except Exception as ex:
            continue
        m = max(max(a, b) for a, b, *_ in e)
        best.append((m, p))
    best.sort(key=lambda t: t[0])
    for m, p in best[:6]:
        print(f"max |dx|,|dy| = {m:.3e}  {p}")
    return best


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sweep":
        sweep()
    else:
        check_frame(4)
# ---
# labview: none
# hardware: none
# ---
