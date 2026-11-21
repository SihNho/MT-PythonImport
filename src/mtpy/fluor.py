"""Offline fluorescence analysis for MT-TIRF (plan 10a; owner 2026-11-21). numpy / scipy, on recorded data.

- Which spot under a bead is the bead's molecule (U25): with the dye a little above the surface, its TIRF intensity
  follows the bead's height when the bead is pulled and released; `correlation_map` gives, per pixel, the
  correlation of intensity with the bead's z over time (the bead's own molecule ~ high |r|, surface dyes ~ 0).
- Depth from the PSF shape (astigmatism, as 3D STORM): `widths` fits a spot's x / y widths;
  `astig_calibration` fits z against sx - sy from a z scan of surface dyes; `z_from_widths` reads z back.

    r = fluor.box_correlation("tra001.h5", box=0, bead_id=3, reference_bead=1)
"""
import h5py
import numpy as np
from scipy import optimize


def correlation_map(stack, signal):
    """Pearson r per pixel between the stack (n x h x w) and the signal (n), frames with a NaN signal left out."""
    s = np.asarray(signal, dtype=np.float64)
    x = np.asarray(stack, dtype=np.float64).reshape(len(s), -1)
    ok = np.isfinite(s)
    x, s = x[ok], s[ok]
    if len(s) < 3:
        raise ValueError(f"only {len(s)} frames with a signal; the correlation needs at least 3")
    xc, sc = x - x.mean(axis=0), s - s.mean()
    den = np.sqrt((xc ** 2).sum(axis=0) * (sc ** 2).sum())
    with np.errstate(invalid="ignore", divide="ignore"):
        r = (xc * sc[:, None]).sum(axis=0) / den
    return r.reshape(np.shape(stack)[1:])


def bead_z(path, bead_id, t=None, reference_bead=None):
    """A bead's z (um) from a run file's /mt, lost frames (-1) as NaN, minus the reference bead's z when given (the
    extension, independent of the focus); with `t` (host times, s from t0) interpolated onto them (NaN outside)."""
    with h5py.File(path, "r") as f:
        ids = list(f["beads/bead_id"][()])
        th, z = f["mt/t_host"][()], f["mt/z_um"][()].astype(np.float64)
        lost = f["mt/bead_lost"][()].astype(bool)
    z[lost] = np.nan

    def col(b):
        if b not in ids:
            raise KeyError(f"bead {b} is not in {path} (beads {ids})")
        return z[:, ids.index(b)]
    v = col(bead_id) - (col(reference_bead) if reference_bead is not None else 0.0)
    if t is None:
        return th, v
    ok = np.isfinite(v)
    return np.interp(t, th[ok], v[ok], left=np.nan, right=np.nan)


def box_correlation(path, box, bead_id, reference_bead=None):
    """correlation_map of one stored bead box (/fluorescence/boxes[:, box]) with that bead's z at the EMCCD frame
    times. Needs a run file recorded with the bead-box storage (api.emccd.set_storage)."""
    with h5py.File(path, "r") as f:
        stack, t = f["fluorescence/boxes"][:, box], f["fluorescence/t_host"][()]
    return correlation_map(stack, bead_z(path, bead_id, t, reference_bead))


def widths(spot, background=None):
    """Centre (x, y) and widths (sx, sy, px) of one spot: a least-squares fit of an elliptical Gaussian with its axes
    on the camera's (the astigmatic lens is aligned to them) plus a constant background, started from the intensity
    moments. A given `background` is held fixed. Returns {"x", "y", "sx", "sy", "amplitude", "signal" (2 pi A sx
    sy), "background"}; NaN when there is no signal or the fit leaves the window."""
    b = np.asarray(spot, dtype=np.float64)
    bg = float(np.median(np.r_[b[0], b[-1], b[1:-1, 0], b[1:-1, -1]])) if background is None else float(background)
    nan = {"x": np.nan, "y": np.nan, "sx": np.nan, "sy": np.nan, "amplitude": np.nan, "signal": 0.0, "background": bg}
    w = np.clip(b - bg, 0.0, None)
    tot = w.sum()
    if tot <= 0:
        return nan
    yy, xx = np.indices(b.shape)
    x, y = (w * xx).sum() / tot, (w * yy).sum() / tot
    sx, sy = np.sqrt((w * (xx - x) ** 2).sum() / tot), np.sqrt((w * (yy - y) ** 2).sum() / tot)

    def resid(p):
        g = p[0] * np.exp(-(xx - p[1]) ** 2 / (2 * p[3] ** 2) - (yy - p[2]) ** 2 / (2 * p[4] ** 2))
        return (g + (p[5] if background is None else bg) - b).ravel()
    p0 = [w.max(), x, y, max(sx, 0.5), max(sy, 0.5)] + ([bg] if background is None else [])
    r = optimize.least_squares(resid, p0)
    a, x, y, sx, sy = r.x[0], r.x[1], r.x[2], abs(r.x[3]), abs(r.x[4])
    h, wd = b.shape
    if not r.success or a <= 0 or not (0 <= x <= wd - 1 and 0 <= y <= h - 1) or max(sx, sy) > max(h, wd):
        return nan
    bg = float(r.x[5]) if background is None else bg
    return {"x": float(x), "y": float(y), "sx": float(sx), "sy": float(sy), "amplitude": float(a),
            "signal": float(2 * np.pi * a * sx * sy), "background": bg}


def astig_calibration(z_um, sx, sy, degree=3):
    """z as a polynomial of d = sx - sy, from a z scan (surface dyes, piezo steps): {"degree", "coef", "d_range",
    "z_range", "rms_um"}. Use only the part of the scan where d changes monotonically with z."""
    z, d = np.asarray(z_um, dtype=np.float64), np.asarray(sx, dtype=np.float64) - np.asarray(sy, dtype=np.float64)
    ok = np.isfinite(z) & np.isfinite(d)
    z, d = z[ok], d[ok]
    if len(z) <= degree:
        raise ValueError(f"{len(z)} usable scan points; degree {degree} needs more than {degree}")
    if not (np.all(np.diff(d[np.argsort(z)]) > 0) or np.all(np.diff(d[np.argsort(z)]) < 0)):
        raise ValueError("sx - sy is not monotonic over the scan; narrow the z range to the monotonic part")
    coef = np.polyfit(d, z, degree)
    return {"degree": degree, "coef": coef.tolist(), "d_range": [float(d.min()), float(d.max())],
            "z_range": [float(z.min()), float(z.max())], "rms_um": float(np.sqrt(np.mean((np.polyval(coef, d) - z) ** 2)))}


def z_from_widths(cal, sx, sy):
    """z (um) from the widths with a calibration of astig_calibration; NaN outside its d range."""
    d = np.asarray(sx, dtype=np.float64) - np.asarray(sy, dtype=np.float64)
    z = np.polyval(cal["coef"], d)
    lo, hi = cal["d_range"]
    return np.where((d >= lo) & (d <= hi), z, np.nan)
