r"""refbead_analyze.py - offline analysis of the reference-bead recordings made by refbead_record.py (no device).

  py tools/refbead_analyze.py <run dir> [--plan static|exposure|drift|field|magnet|rotation]   -> <run dir>/<plan>/analysis.json

XY is the current method's Croquette stage (track.xy_croquette) run on each stored crop, so the numbers are the ones the
LabVIEW tracker would give for the same pixels (cross 120 when the crop allows, else the largest that fits - noted in the
output). Z needs a LUT from the z-scan and is added when that exists. Nominal pixel 84 nm (manual "Units"), replaced by
the field plan's measured value when available.
"""
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from mtpy import calib, track

NM_PX = 84.0


def load(d, seg):
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    nb, half = len(meta["beads"]), meta["half"]
    sb = os.path.join(d, f"{seg}.beads.json")
    if os.path.exists(sb):                                  # a segment after a re-pick has its own bead list
        with open(sb, encoding="utf-8") as f:
            sj = json.load(f)
        nb, half = len(sj["beads"]), sj["half"]
    raw = np.memmap(os.path.join(d, f"{seg}.crops.u8"), np.uint8, "r")
    crops = raw.reshape(-1, nb, 2 * half, 2 * half)
    idx = np.load(os.path.join(d, f"{seg}.index.npy"))
    n = min(len(idx), len(crops))
    return crops[:n], idx[:n], meta


def cross_for(half):
    """Largest even cross whose sub-image (h = round(0.6 cross)) fits the crop with 4 px to spare; 120 is LabVIEW's."""
    c = 120
    while track.lv_round(c * 0.6) > half - 4:
        c -= 2
    return c


def xy_series(crops, step=1):
    """(frames, beads, 2) positions in crop pixels by the Croquette stage, starting each bead at the crop centre."""
    half = crops.shape[2] // 2
    cross = cross_for(half)
    h = track.lv_round(cross * 0.6)
    win_rs, win_h = calib.windows(cross)
    out = np.full((len(range(0, len(crops), step)), crops.shape[1], 2), np.nan)
    for k, f in enumerate(range(0, len(crops), step)):
        for b in range(crops.shape[1]):
            sub = crops[f, b, half - h:half + h, half - h:half + h]
            try:
                x, y, _, _ = track.xy_croquette(sub, h, half, half, cross, win_rs, win_h, track.DEFAULT)
                out[k, b] = x, y
            except (TypeError, ValueError, np.linalg.LinAlgError):   # no bead pattern (parabola off the edge)
                pass
    return out, cross


def noise(xy, nm_px=NM_PX):
    """Per bead std (nm) after removing a linear drift, sigma_y / sigma_x, and the pairwise differential noise
    std(a - b) / sqrt 2 (common-mode motion removed) - the tracking floor of one bead."""
    t = np.arange(len(xy))
    det = xy - np.polyval(np.polyfit(t, xy.reshape(len(t), -1), 1), t[:, None]).reshape(xy.shape) \
        if len(t) > 2 else xy - xy.mean(0)
    sd = det.std(0) * nm_px
    nb = xy.shape[1]
    diff = [np.std(det[:, a] - det[:, b], axis=0) / np.sqrt(2) * nm_px for a in range(nb) for b in range(a + 1, nb)]
    diff = np.array(diff)
    mean_ref = det.mean(1)                                    # average of all reference beads = the common mode
    resid = (det - mean_ref[:, None]).std(0) * nm_px
    return {"sd_x_nm": sd[:, 0].round(2).tolist(), "sd_y_nm": sd[:, 1].round(2).tolist(),
            "ratio_y_x_median": float(np.median(sd[:, 1] / sd[:, 0])),
            "diff_x_nm_median": float(np.median(diff[:, 0])) if len(diff) else None,
            "diff_y_nm_median": float(np.median(diff[:, 1])) if len(diff) else None,
            "common_x_nm": float(mean_ref[:, 0].std() * nm_px), "common_y_nm": float(mean_ref[:, 1].std() * nm_px),
            "resid_vs_mean_x_nm_median": float(np.median(resid[:, 0])),
            "resid_vs_mean_y_nm_median": float(np.median(resid[:, 1])),
            "drift_x_nm": float(np.ptp(xy[:, :, 0].mean(1)) * nm_px), "drift_y_nm": float(np.ptp(xy[:, :, 1].mean(1)) * nm_px)}


def allan(x, rate, taus=(0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100, 300)):
    """Overlapping-free Allan deviation of one series (nm) at the given averaging times (s)."""
    out = {}
    for tau in taus:
        m = round(tau * rate)
        n = len(x) // m if m else 0
        if m < 1 or n < 3:
            continue
        a = x[:n * m].reshape(n, m).mean(1)
        out[str(tau)] = float(np.sqrt(0.5 * np.mean(np.diff(a) ** 2)))
    return out


def radial_of(img, x, y, rmax=60):
    """Mean radial profile (grey per integer radius) and the ring radius vs angle (8 sectors) of one bead image."""
    yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
    r = np.hypot(yy - y, xx - x)
    th = np.arctan2(yy - y, xx - x)
    ri = r.astype(int)
    m = ri <= rmax
    prof = np.bincount(ri[m], img[m].astype(float), rmax + 1) / np.maximum(np.bincount(ri[m], None, rmax + 1), 1)
    sect = []
    for s in range(8):
        lo = -np.pi + s * np.pi / 4
        ms = m & (th >= lo) & (th < lo + np.pi / 4)
        p = np.bincount(ri[ms], img[ms].astype(float), rmax + 1) / np.maximum(np.bincount(ri[ms], None, rmax + 1), 1)
        sect.append(p)
    return prof, np.array(sect)


def ellipticity(sect, r_lo=8, r_hi=40):
    """Elongation of the first bright ring: radius of the profile maximum in each of 8 sectors -> (max-min)/mean and
    the angle (deg) of the longest sector pair."""
    rr = np.array([r_lo + int(np.argmax(p[r_lo:r_hi])) for p in sect], dtype=float)
    pair = rr[:4] + rr[4:]                                    # opposite sectors
    return float((pair.max() - pair.min()) / pair.mean()), float(-180 + 45 * int(np.argmax(pair)) + 22.5), rr.tolist()


def summarise_static(d, segs):
    res = {}
    for seg in segs:
        crops, idx, _ = load(d, seg)
        xy, cross = xy_series(crops)
        ok = np.isnan(xy).any(2).mean(0) < 0.01                 # beads tracked in >= 99 % of the frames
        np.save(os.path.join(d, f"{seg}.xy.npy"), xy)
        xy = xy[:, ok]
        xy = np.where(np.isnan(xy), np.nanmedian(xy, 0), xy)
        rate = (len(idx) - 1) / (idx[-1, 1] - idx[0, 1])
        gaps = int(np.sum(np.diff(idx[:, 0]) - 1))
        if not ok.any():
            res[seg] = {"frames": len(idx), "error": "no bead tracked"}
            continue
        res[seg] = {"frames": len(idx), "rate_hz": round(rate, 3), "gaps": gaps, "cross": cross, **noise(xy),
                    "beads_used": np.flatnonzero(ok).tolist(), "mean_grey": float(crops[::50].mean())}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--plan", required=True)
    a = ap.parse_args()
    d = os.path.join(a.run, a.plan)
    segs = sorted(f[:-9] for f in os.listdir(d) if f.endswith(".crops.u8"))
    res = {"plan": a.plan, "segments": summarise_static(d, segs)} if segs else {"plan": a.plan}
    if a.plan == "drift":
        xy = np.load(os.path.join(d, "drift.xy.npy"))
        rate = res["segments"]["drift"]["rate_hz"]
        res["allan_x_nm"] = allan(xy[:, :, 0].mean(1) * NM_PX, rate)
        res["allan_diff_x_nm"] = allan((xy[:, 0, 0] - xy[:, 1, 0]) / np.sqrt(2) * NM_PX, rate)
    with open(os.path.join(d, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1)[:3000])


if __name__ == "__main__":
    sys.exit(main())
