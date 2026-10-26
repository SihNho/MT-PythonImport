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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo
sys.path.insert(0, os.path.join(ROOT, "src"))
from mtpy import calib, track

NM_PX = 84.0
V6 = r"G:\Codes\LabVIEW_Codes\MinLab\zz_LabView VI\AAA_UNIST\2. Tracking\V6_ParallelLoop"


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


def xy_series(crops, step=1, cross=None, follow=False):
    """(frames, beads, 2) positions in crop pixels by the Croquette stage. Each bead starts at the crop centre; with
    `follow` every frame starts from the previous frame's position (as the LabVIEW tracker does), so a drift up to
    half - h px stays trackable. A bead whose window would leave the crop is nan from then on."""
    half = crops.shape[2] // 2
    cross = cross or cross_for(half)
    h = track.lv_round(cross * 0.6)
    win_rs, win_h = calib.windows(cross)
    out = np.full((len(range(0, len(crops), step)), crops.shape[1], 2), np.nan)
    start = np.full((crops.shape[1], 2), half)
    for k, f in enumerate(range(0, len(crops), step)):
        for b in range(crops.shape[1]):
            cx, cy = (track.lv_round(v) for v in start[b])
            if not (h <= cx <= 2 * half - h and h <= cy <= 2 * half - h):
                continue
            sub = crops[f, b, cy - h:cy + h, cx - h:cx + h]
            try:
                x, y, _, _ = track.xy_croquette(sub, h, cx, cy, cross, win_rs, win_h, track.DEFAULT)
                out[k, b] = x, y
                if follow:
                    start[b] = x, y
            except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):   # no bead pattern (parabola off the edge)
                pass
    return out, cross


def noise(xy, nm_px=NM_PX):
    """Per bead std (nm) after removing a linear drift, sigma_y / sigma_x, and the pairwise differential noise
    std(a - b) / sqrt 2 (common-mode motion removed) - the tracking floor of one bead."""
    t = np.arange(len(xy))
    det = xy - np.polyval(np.polyfit(t, xy.reshape(len(t), -1), 1), t[:, None]).reshape(xy.shape) \
        if len(t) > 2 else xy - xy.mean(0)
    sd = det.std(0) * nm_px
    fixed = np.hypot(*sd.T) <= 3 * np.median(np.hypot(*sd.T))   # loose beads (Brownian) leave the statistics
    det, nb = det[:, fixed], int(fixed.sum())
    diff = [np.std(det[:, a] - det[:, b], axis=0) / np.sqrt(2) * nm_px for a in range(nb) for b in range(a + 1, nb)]
    diff = np.array(diff)
    mean_ref = det.mean(1)                                    # average of all reference beads = the common mode
    resid = (det - mean_ref[:, None]).std(0) * nm_px
    return {"sd_x_nm": sd[:, 0].round(2).tolist(), "sd_y_nm": sd[:, 1].round(2).tolist(),
            "fixed": fixed.tolist(), "ratio_y_x_median": float(np.median(sd[fixed, 1] / sd[fixed, 0])),
            "diff_x_nm_median": float(np.median(diff[:, 0])) if len(diff) else None,
            "diff_y_nm_median": float(np.median(diff[:, 1])) if len(diff) else None,
            "common_x_nm": float(mean_ref[:, 0].std() * nm_px), "common_y_nm": float(mean_ref[:, 1].std() * nm_px),
            "resid_vs_mean_x_nm_median": float(np.median(resid[:, 0])),
            "resid_vs_mean_y_nm_median": float(np.median(resid[:, 1])),
            "drift_x_nm": float(np.ptp(xy[:, fixed, 0].mean(1)) * nm_px),
            "drift_y_nm": float(np.ptp(xy[:, fixed, 1].mean(1)) * nm_px)}


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


def stretch(img, x, y, r_lo=15, r_hi=55, n_th=180):
    """Elongation of the outer pattern: on circles r_lo..r_hi around the centre, the cos 2theta / sin 2theta part of
    the intensity vs angle, relative to the radial modulation. Returns (amplitude, long-axis angle deg, per-radius
    amplitude). A round pattern gives ~0; a pattern stretched along angle a peaks there."""
    th = np.linspace(-np.pi, np.pi, n_th, endpoint=False)
    rs = np.arange(r_lo, r_hi + 1)
    xs, ys = x + rs[:, None] * np.cos(th), y + rs[:, None] * np.sin(th)
    x0, y0 = np.floor(xs).astype(int), np.floor(ys).astype(int)
    fx, fy = xs - x0, ys - y0
    v = (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy) + img[y0 + 1, x0] * (1 - fx) * fy
         + img[y0 + 1, x0 + 1] * fx * fy)
    mod = v.mean(1).std()                                   # radial ring modulation (grey)
    c2 = (v * np.cos(2 * th)).mean(1) * 2
    s2 = (v * np.sin(2 * th)).mean(1) * 2
    # the sign of the ring (bright / dark) flips with r, so combine the radii as a 2theta vector weighted by the
    # local ring slope sign: use the amplitude only, and the angle of the strongest radius
    amp = np.hypot(c2, s2)
    k = int(np.argmax(amp))
    return float(amp.mean() / mod), float(np.degrees(np.arctan2(s2[k], c2[k])) / 2), (amp / mod).round(4).tolist()


def summarise_static(d, segs, nm_px=NM_PX, step=1):
    res = {}
    for seg in segs:
        crops, idx, _ = load(d, seg)
        xy, cross = xy_series(crops, step, *((60, True) if step > 1 else (None, False)))   # long run: follow the drift
        ok = np.isnan(xy).any(2).mean(0) < 0.01                 # beads tracked in >= 99 % of the frames
        np.save(os.path.join(d, f"{seg}.xy.npy"), xy)
        xy = xy[:, ok]
        xy = np.where(np.isnan(xy), np.nanmedian(xy, 0), xy)
        rate = (len(idx) - 1) / (idx[-1, 1] - idx[0, 1]) / step   # rate of the analysed series
        gaps = int(np.sum(np.diff(idx[:, 0]) - 1))
        if not ok.any():
            res[seg] = {"frames": len(idx), "error": "no bead tracked"}
            continue
        res[seg] = {"frames": len(idx), "rate_hz": round(rate, 3), "gaps": gaps, "cross": cross, **noise(xy, nm_px),
                    "beads_used": np.flatnonzero(ok).tolist(), "mean_grey": float(crops[::50].mean())}
    return res


def marks(d):
    """{mark name: buffer number at the mark} from events.jsonl."""
    out = {}
    with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("do") == "mark":
                out[e["name"]] = e["buffer"]
    return out


def bead_profile(sub_full, half_crop, cross=120):
    """XY (Croquette) then the radial profile of one crop -> (x, y, profile of length cross/2), crop pixels."""
    h = track.lv_round(cross * 0.6)
    win_rs, win_h = calib.windows(cross)
    sub = sub_full[half_crop - h:half_crop + h, half_crop - h:half_crop + h]
    x, y, sx, sy = track.xy_croquette(sub, h, half_crop, half_crop, cross, win_rs, win_h, track.DEFAULT)
    return x, y, track.radial_profile(sub, h + sx, h + sy, cross // 2)


def build_lut(d, seg, low=0, high=25, forget=20, z_step_um=0.1):
    """LUT from a z-scan segment: per slice and bead, the mean radial profile of the slice's frames, mirrored like
    the .cal stack (L = cross - 1). LOW / HIGH / forget default to the LabVIEW .cal of 2026-09-07 (0 / 25 / 18-23)."""
    crops, idx, _ = load(d, seg)
    mk = marks(d)
    ks = sorted(int(n.split("_z")[-1][:-6]) for n in mk if n.startswith(seg + "_z") and n.endswith("_start"))
    half_crop = crops.shape[2] // 2
    nb = crops.shape[1]
    stack = np.full((nb, len(ks), 119), np.nan)
    within = np.full((nb, len(ks)), np.nan)
    for si, k in enumerate(ks):
        b0, b1 = mk[f"{seg}_z{k}_start"], mk[f"{seg}_z{k}_end"]
        fr = np.flatnonzero((idx[:, 0] > b0) & (idx[:, 0] <= b1))
        for b in range(nb):
            profs = []
            for f in fr:
                try:
                    profs.append(bead_profile(crops[f, b], half_crop)[2])
                except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                    pass
            if profs:
                pr = np.nanmean(profs, 0)
                stack[b, si] = np.concatenate([pr[1:][::-1], pr])
                within[b, si] = len(profs)
    np.savez(os.path.join(d, f"{seg}.lut.npz"), stack=stack, z_um=np.array(ks) * z_step_um, low=low, high=high,
             forget=forget, z_step_um=z_step_um, n_frames=within)
    return stack, np.array(ks) * z_step_um


def lut_clusters(d, seg="zscan"):
    z = np.load(os.path.join(d, f"{seg}.lut.npz"))
    return [None if np.isnan(st).any() else calib.prep_bead(st, int(z["low"]), int(z["high"]), int(z["forget"]),
                                                            float(z["z_step_um"]), 120) for st in z["stack"]]


def z_series(crops, cals, step=1):
    """(frames, beads) z in um with the given per-bead LUT clusters (None -> nan)."""
    half_crop = crops.shape[2] // 2
    out = np.full((len(range(0, len(crops), step)), crops.shape[1]), np.nan)
    for k, f in enumerate(range(0, len(crops), step)):
        for b, cal in enumerate(cals):
            if cal is None:
                continue
            try:
                _, _, rad = bead_profile(crops[f, b], half_crop)
                zi, _ = track.z_phase(rad, 60, cal, track.DEFAULT)
                out[k, b] = zi * cal["z_step"]
            except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                pass
    return out


def spots(img):
    """Bead centres (px) in one averaged full frame, refined by the Croquette stage (cross 120)."""
    sys.path.insert(0, os.path.join(V6, "tools", "bench", "lean_bench"))
    import p64_beadmap  # shortcut: the V6 finder, as refbead_record.find_beads
    out = []
    for b in p64_beadmap.find(img)["spots"]:
        x0, y0 = int(b["x"]), int(b["y"])
        if not (80 <= x0 < img.shape[1] - 80 and 80 <= y0 < img.shape[0] - 80):
            continue
        try:
            x, y, _ = bead_profile(img[y0 - 80:y0 + 80, x0 - 80:x0 + 80].astype(np.float64), 80)
            out.append((x0 - 80 + x, y0 - 80 + y))
        except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
            pass
    return np.array(out)


def match(a, b, tol):
    """Pairs (i, j) of nearest points of a and b closer than tol px."""
    return [(i, int(np.argmin(np.hypot(*(b - p).T)))) for i, p in enumerate(a)
            if len(b) and np.min(np.hypot(*(b - p).T)) < tol]


def shift_px(a, b):
    """Integer image shift b - a (x, y) by phase correlation of two frames."""
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = np.fft.ifft2(fb * np.conj(fa) / (np.abs(fb * np.conj(fa)) + 1e-9)).real
    y, x = np.unravel_index(np.argmax(r), r.shape)
    return np.array([x - r.shape[1] if x > r.shape[1] // 2 else x, y - r.shape[0] if y > r.shape[0] // 2 else y])


def displacement(fa, fb, bg):
    """Median sub-pixel bead displacement b - a (px) and the bead count: global shift by phase correlation of the
    background-free frames (the fixed illumination pattern would lock it at 0), then each bead of a matched to b
    within 5 px of the shifted position."""
    s0 = shift_px(fa - bg, fb - bg)
    pa, pb = spots(fa), spots(fb)
    dd = np.array([pb[j] - pa[i] for i, j in match(pa + s0, pb, 5.0)])
    return (np.median(dd, 0), len(dd)) if len(dd) else (None, 0)


def field(d):
    """Pixel scale per axis from the single-axis scale line (each move against the frame just before it), the return
    error of every move pair, and the ring elongation of every bead at every 3 x 3 position."""
    def mean_frame(name):
        return np.load(os.path.join(d, f"{name}.full.npy")).astype(np.float64).mean(0)
    res = {"scale": {}, "ellipticity": {}}
    grid = [mean_frame(f[:-9]) for f in os.listdir(d) if f.startswith("f_") and f.endswith(".full.npy")]
    bg = np.median(grid, 0)                                 # beads sit elsewhere at each grid position
    v, n = displacement(mean_frame("f_start"), mean_frame("f_0_0"), bg)
    res["grid_return_px"] = None if v is None else v.round(3).tolist()
    prev = "f_0_0"
    for axis in ("X", "Y"):
        rows = []
        for um in (5, 10, 20, 35):
            a, b, c = mean_frame(prev), mean_frame(f"sc_{axis}{um}"), mean_frame(f"sc_{axis}{um}_back")
            v, n = displacement(a, b, bg)
            vb, _ = displacement(a, c, bg)
            rows.append({"um": um, "n": n, "d_px": None if v is None else v.round(3).tolist(),
                         "nm_per_px": None if v is None else float(um * 1000 / np.hypot(*v)),
                         "return_px": None if vb is None else vb.round(3).tolist()})
            prev = f"sc_{axis}{um}_back"
        res["scale"][axis] = rows
    for f in sorted(os.listdir(d)):
        if f.startswith("f_") and f.endswith(".full.npy") and f != "f_start.full.npy":
            img = mean_frame(f[:-9])
            el = []
            for x, y in spots(img):
                e, ang, _ = stretch(img - bg, x, y)
                el.append([round(float(x), 1), round(float(y), 1), round(e, 4), round(ang, 1)])
            res["ellipticity"][f[:-9]] = el
    return res


def mark_list(d):
    """[(name, buffer, t)] of every mark in order (names may repeat, e.g. the way up and down of a ramp)."""
    with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as f:
        ev = [json.loads(line) for line in f]
    return [(e["name"], e["buffer"], e["t"]) for e in ev if e.get("do") == "mark"]


def holds(d, seg, hold_s, step, cals, nm_px):
    """Per marked hold: mean x, y (nm, relative to the first hold), z (um), crop mean grey, and the radial-profile
    change versus the first hold (rms of the difference / rms of the first profile's modulation)."""
    crops, idx, _ = load(d, seg)
    rate = (len(idx) - 1) / (idx[-1, 1] - idx[0, 1])
    half_crop = crops.shape[2] // 2
    out, ref = [], None
    for name, b0, _ in mark_list(d):
        fr = np.flatnonzero((idx[:, 0] > b0) & (idx[:, 0] <= b0 + hold_s * rate))[::step]
        xy, z, prof = [], [], []
        for f in fr:
            row_xy, row_z, row_p = [], [], []
            for b, cal in enumerate(cals):
                try:
                    x, y, rad = bead_profile(crops[f, b], half_crop)
                    zi = track.z_phase(rad, 60, cal, track.DEFAULT)[0] * cal["z_step"] if cal else np.nan
                except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                    x = y = zi = np.nan
                    rad = np.full(60, np.nan)
                row_xy.append((x, y))
                row_z.append(zi)
                row_p.append(rad)
            xy.append(row_xy)
            z.append(row_z)
            prof.append(row_p)
        xy, z, prof = np.nanmean(xy, 0), np.nanmean(z, 0), np.nanmean(prof, 0)
        grey = crops[fr].reshape(len(fr), crops.shape[1], -1).mean((0, 2))
        if ref is None:
            ref = (xy, z, prof)
        mod = np.nanstd(ref[2][:, 5:], 1)
        out.append({"name": name, "frames": len(fr), "dx_nm": ((xy[:, 0] - ref[0][:, 0]) * nm_px).round(1).tolist(),
                    "dy_nm": ((xy[:, 1] - ref[0][:, 1]) * nm_px).round(1).tolist(),
                    "dz_nm": ((z - ref[1]) * 1000).round(1).tolist(), "grey": grey.round(2).tolist(),
                    "profile_change": (np.sqrt(np.nanmean((prof[:, 5:] - ref[2][:, 5:]) ** 2, 1)) / mod).round(4).tolist()})
    return out


def rotation(d, cals, nm_px, step=2):
    """Per magnet position: fixed-bead x, y, z during the rotor moves vs at rest, and the 1st / 2nd harmonic of the
    common (bead-mean) signal in the rotor angle. The angle is taken linear in time over each move (the sender's
    t0..t1, which includes the port open and read-backs: shortcut, upgrade with the rotor POS samples if needed)."""
    with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as f:
        ev = [json.loads(line) for line in f]
    moves = [(e["t0"], e["t1"], int(e["gate"].split()[1])) for e in ev if e.get("device") == "rotor" and "rc" in e]
    out = {}
    for seg in sorted(f[:-9] for f in os.listdir(d) if f.endswith(".crops.u8")):
        crops, idx, _ = load(d, seg)
        sel = np.arange(0, len(crops), step)
        xy, _ = xy_series(crops[sel], step=1)
        z = z_series(crops[sel], cals, step=1)
        t = idx[sel, 1]
        sig = np.concatenate([xy * nm_px, z[:, :, None] * 1000], 2)       # (frames, beads, 3) nm
        good = [b for b in range(sig.shape[1]) if b not in (3, 5)]
        cm = np.nanmean(sig[:, good], 1)
        ang = np.full(len(t), np.nan)
        moving = np.zeros(len(t), bool)
        acc = 0.0
        for t0, t1, pulses in moves:
            m = (t >= t0) & (t <= t1)
            if m.any():
                moving |= m
                ang[m] = acc + (t[m] - t0) / (t1 - t0) * pulses * 0.72
            acc += pulses * 0.72
        r = {"frames": len(t), "rest_sd_nm": np.nanstd(cm[~moving], 0).round(2).tolist(),
             "moving_sd_nm": np.nanstd(cm[moving], 0).round(2).tolist() if moving.any() else None}
        if moving.sum() > 20:
            th = np.radians(ang[moving])
            X = np.vstack([np.ones_like(th), np.cos(th), np.sin(th), np.cos(2 * th), np.sin(2 * th)]).T
            for k, nm in enumerate(("x", "y", "z")):
                c = np.linalg.lstsq(X, cm[moving, k] - np.nanmean(cm[moving, k]), rcond=None)[0]
                r[f"h1_{nm}_nm"], r[f"h2_{nm}_nm"] = round(float(np.hypot(c[1], c[2])), 2), round(float(np.hypot(c[3], c[4])), 2)
        out[seg] = r
    return out


# image displacement per um of stage move, measured by the field plan (px / um): X move, Y move
PX_PER_UM_X, PX_PER_UM_Y = np.array([4.883, 0.194]), np.array([0.202, -4.983])


def zscan_field(d, grid_um=(35.0, 28.0), step=3):
    """Does the field position bias z? For every bead seen at the centre and at another 3 x 3 position (matched by the
    measured stage-to-image map, 15 px), track that position's z-scan with (a) its own LUT and (b) the bead's LUT made
    at the centre. Returns the rms deviation from the commanded z (offset removed) in nm for both, per position."""
    seg_of = {(i, j): f"zf_{i}_{j}" for i in (-1, 0, 1) for j in (-1, 0, 1)}
    luts, beads = {}, {}
    for k, seg in seg_of.items():
        build_lut(d, seg)
        z = np.load(os.path.join(d, f"{seg}.lut.npz"))
        luts[k] = [None if np.isnan(st).any() else calib.prep_bead(st, int(z["low"]), int(z["high"]),
                   int(z["forget"]), float(z["z_step_um"]), 120) for st in z["stack"]]
        with open(os.path.join(d, f"{seg}.beads.json"), encoding="utf-8") as f:
            beads[k] = np.array([(b["x"], b["y"]) for b in json.load(f)["beads"]], float)
    mk = marks(d)
    out = {}
    for (i, j), seg in seg_of.items():
        if (i, j) == (0, 0):
            continue
        shift = i * grid_um[0] * PX_PER_UM_X + j * grid_um[1] * PX_PER_UM_Y
        crops, idx, _ = load(d, seg)
        half_crop = crops.shape[2] // 2
        rows = []
        for bc, pc in enumerate(beads[(0, 0)]):
            dist = np.hypot(*(beads[(i, j)] - (pc + shift)).T)
            if not len(dist) or dist.min() > 15 or luts[(0, 0)][bc] is None:
                continue
            bp = int(np.argmin(dist))
            if luts[(i, j)][bp] is None:
                continue
            cmd, own, cen = [], [], []
            for kz in range(-50, 51, 2):
                b0, b1 = mk[f"{seg}_z{kz}_start"], mk[f"{seg}_z{kz}_end"]
                for f in np.flatnonzero((idx[:, 0] > b0) & (idx[:, 0] <= b1))[::step]:
                    try:
                        _, _, rad = bead_profile(crops[f, bp], half_crop)
                        zo = track.z_phase(rad, 60, luts[(i, j)][bp], track.DEFAULT)[0] * 0.1
                        zc = track.z_phase(rad, 60, luts[(0, 0)][bc], track.DEFAULT)[0] * 0.1
                    except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                        continue
                    cmd.append(kz * 0.1)
                    own.append(zo)
                    cen.append(zc)
            cmd, own, cen = map(np.array, (cmd, own, cen))
            m = np.abs(cmd) <= 4.0                          # leave the 1 um ends, where the LUT itself is weak
            dev = {nm: float(np.sqrt(np.mean(((v - cmd) - np.mean(v[m] - cmd[m]))[m] ** 2)) * 1000)
                   for nm, v in (("own", own), ("centre", cen))}
            slope = float(np.polyfit(cmd[m], cen[m], 1)[0])
            rows.append({"bead_centre": bc, "bead_here": bp, "match_px": round(float(dist.min()), 1),
                         "rms_own_nm": round(dev["own"], 1), "rms_centre_lut_nm": round(dev["centre"], 1),
                         "slope_centre_lut": round(slope, 4)})
        out[seg] = rows
    return out


def zstep(d, seg="zscan", steps=(1, 2, 3, 5), test_step=2):
    """LUT slice spacing (owner 2026-10-27): LUTs with every m-th slice of the 100 nm scan (100 / 200 / 300 / 500 nm)
    are built from the FIRST half of each slice's frames and tested on the SECOND half of every slice, so slices
    between LUT slices are out of sample. Also the radius of the first bright ring vs z (the pattern size)."""
    crops, idx, _ = load(d, seg)
    mk = marks(d)
    ks = list(range(-50, 51))
    half_crop = crops.shape[2] // 2
    nb = crops.shape[1]
    first, second = np.full((nb, len(ks), 60), np.nan), []
    for si, k in enumerate(ks):
        fr = np.flatnonzero((idx[:, 0] > mk[f"{seg}_z{k}_start"]) & (idx[:, 0] <= mk[f"{seg}_z{k}_end"]))
        n2 = len(fr) // 2
        for b in range(nb):
            pa = []
            for f in fr[:n2]:
                try:
                    pa.append(bead_profile(crops[f, b], half_crop)[2])
                except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                    pass
            if pa:
                first[b, si] = np.nanmean(pa, 0)
            for f in fr[n2::test_step]:
                try:
                    second.append((b, k, bead_profile(crops[f, b], half_crop)[2]))
                except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                    pass
    res = {"lut_step": {}}
    for m in steps:
        rows = {}
        for b in range(nb):
            st = first[b, ::m]
            if np.isnan(st).any():
                continue
            cal = calib.prep_bead(np.concatenate([st[:, 1:][:, ::-1], st], 1), 0, 25, 20, 0.1 * m, 120)
            cmd, z, on = [], [], []
            for bb, k, rad in second:
                if bb != b:
                    continue
                try:
                    zi = track.z_phase(rad, 60, cal, track.DEFAULT)[0]
                except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                    continue
                cmd.append(k * 0.1)
                z.append(-5.0 + zi * 0.1 * m)
                on.append((k + 50) % m == 0)
            cmd, z, on = map(np.array, (cmd, z, on))
            sel = np.abs(cmd) <= 4.0
            err = (z - cmd)[sel]
            err = err - np.median(err)
            slices = np.unique(cmd[sel])
            mean_err = np.array([np.mean(err[cmd[sel] == c]) for c in slices]) * 1000
            on_s = np.array([on[sel][cmd[sel] == c][0] for c in slices])
            noise = np.median([np.std(err[cmd[sel] == c]) for c in slices]) * 1000
            rows[b] = {"rms_nm": round(float(np.sqrt(np.mean(err ** 2)) * 1000), 1),
                       "bias_on_lut_slices_nm": round(float(np.sqrt(np.mean(mean_err[on_s] ** 2))), 1),
                       "bias_between_slices_nm": round(float(np.sqrt(np.mean(mean_err[~on_s] ** 2))), 1) if (~on_s).any() else None,
                       "noise_nm": round(float(noise), 1),
                       "slope": round(float(np.polyfit(cmd[sel], z[sel], 1)[0]), 4)}
        res["lut_step"][f"{100 * m} nm"] = rows
    ring = {}
    for b in range(nb):
        r = []
        for si in range(len(ks)):
            p = first[b, si]
            if np.isnan(p).any():
                r.append(np.nan)
                continue
            j = 5 + int(np.argmax(p[5:35]))
            a_, b_, c_ = p[j - 1], p[j], p[j + 1]
            r.append(j + 0.5 * (a_ - c_) / (a_ - 2 * b_ + c_))
        r = np.array(r)
        z = np.array(ks) * 0.1
        m_ = (np.abs(z) <= 4) & ~np.isnan(r)
        ring[b] = {"radius_px_at_z": {f"{zz:.1f}": round(float(rr), 2) for zz, rr in zip(z[::10], r[::10])},
                   "slope_px_per_um": round(float(np.polyfit(z[m_], r[m_], 1)[0]), 3) if m_.sum() > 3 else None}
    res["ring"] = ring
    return res


def search(d):
    """Usable reference beads per grid snapshot of the search plan (the recorder's own pick rules)."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import refbead_record
    out = {}
    for f in sorted(os.listdir(d)):
        if f.startswith("g_") and f.endswith(".full.npy"):
            img = np.load(os.path.join(d, f))[0]
            beads, found = refbead_record.find_beads(img)
            i, j = (int(v) for v in f[2:-9].split("_"))
            out[f[:-9]] = {"at_um": [i * 300.0, j * 300.0], "beads": len(beads), "spots": len(found["spots"])}
    return out


def zfine(d, seg, cals, step=1):
    """Real focus displacement for sub-unit commands: per slice (way up and way down) the mean tracked z of the fixed
    beads (100 nm LUT of the same session), against the commanded z. Compares a straight line (the piezo follows
    the decimal command) with the staircase of whole 0.1 um units (it is rounded)."""
    crops, idx, _ = load(d, seg)
    with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as f:
        ev = [json.loads(line) for line in f]
    st = {e["name"][:-6]: (e["buffer"], e["z_units"]) for e in ev if e.get("do") == "mark" and e["name"].startswith(seg)
          and e["name"].endswith("_start")}
    en = {e["name"][:-4]: e["buffer"] for e in ev if e.get("do") == "mark" and e["name"].startswith(seg)
          and e["name"].endswith("_end")}
    rows = []
    for name, (b0, zu) in st.items():
        fr = np.flatnonzero((idx[:, 0] > b0) & (idx[:, 0] <= en[name]))[::step]
        z = z_series(crops[fr], cals)
        rows.append((name.split("_")[-1][:2], zu, *np.nanmean(z, 0)))
    way = np.array([r[0] == "up" for r in rows])
    cmd = np.array([r[1] for r in rows]) * 0.1                                    # um
    z = np.array([r[2:] for r in rows], float)
    beads = [b for b in range(z.shape[1]) if np.isfinite(z[:, b]).mean() > 0.9]
    zc = np.nanmean(z[:, beads], 1)
    res = {"beads": beads, "n_slices": len(rows)}
    for nm, m in (("up", way), ("down", ~way)):
        c, y = cmd[m], zc[m]
        ok = np.isfinite(y)
        c, y = c[ok], y[ok]
        lin = np.polyfit(c, y, 1)
        stair = np.round(c * 10 + 1e-9) / 10                                     # whole units, half up
        st_fit = np.polyfit(stair, y, 1)
        res[nm] = {"slope": round(float(lin[0]), 4),
                   "rms_line_nm": round(float(np.std(y - np.polyval(lin, c)) * 1000), 2),
                   "rms_staircase_nm": round(float(np.std(y - np.polyval(st_fit, stair)) * 1000), 2)}
    np.save(os.path.join(d, f"{seg}.slices.npy"), np.column_stack([way, cmd, zc]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--nm-px", type=float, default=NM_PX, help="measured pixel size (field plan) for nm outputs")
    a = ap.parse_args()
    d = os.path.join(a.run, "zscan" if a.plan == "zstep" else a.plan)    # zstep re-analyses the z-scan
    segs = [] if a.plan == "zstep" else sorted(f[:-9] for f in os.listdir(d) if f.endswith(".crops.u8"))
    res = {"plan": a.plan}
    if segs and a.plan not in ("zscan", "zscan_field", "magnet", "rotation", "zfine_at"):
        res["segments"] = summarise_static(d, segs, a.nm_px, 5 if a.plan == "drift" else 1)
    if a.plan == "search":
        res["search"] = search(d)
    if a.plan == "zfine_at":
        build_lut(d, "zscan")
        cals = lut_clusters(d)
        res["zfine50"] = zfine(d, "zfine50", cals)
        res["zfine20"] = zfine(d, "zfine20", cals)
    if a.plan == "zstep":
        res["zstep"] = zstep(d)
        with open(os.path.join(d, "zstep.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
        print(json.dumps(res, indent=1)[:4000])
        return 0
    if a.plan == "zscan":
        _, zs = build_lut(d, "zscan")
        cals = lut_clusters(d)
        crops, idx, _ = load(d, "zscan")
        mk = marks(d)
        z = z_series(crops, cals, step=1)
        per = []                                          # tracked z vs commanded z, per slice (U34 quality map)
        for k_um in zs:
            k = round(k_um * 10)
            fr = (idx[:, 0] > mk[f"zscan_z{k}_start"]) & (idx[:, 0] <= mk[f"zscan_z{k}_end"])
            zz = z[fr]
            per.append([k_um, *np.nanmean(zz, 0).round(4).tolist(), *np.nanstd(zz, 0).round(4).tolist()])
        np.save(os.path.join(d, "zscan.z.npy"), z)
        per = np.array(per)
        nb = len(cals)
        mean_z, sd_z = per[:, 1:1 + nb], per[:, 1 + nb:]
        res["lut_beads"] = [i for i, c in enumerate(cals) if c is not None]
        res["z_vs_command"] = {"command_um": per[:, 0].tolist(), "mean_um": mean_z.tolist(), "sd_um": sd_z.tolist()}
        good = res["lut_beads"]
        res["z_sd_nm_median_per_slice"] = (np.nanmedian(sd_z[:, good], 1) * 1000).round(2).tolist()
        res["z_error_nm_median_per_slice"] = (np.nanmedian(np.abs(mean_z[:, good] - per[:, [0]] - (mean_z[:, good]
                                              - per[:, [0]]).mean(0)), 1) * 1000).round(2).tolist()
    if a.plan == "magnet":
        cals = lut_clusters(os.path.join(a.run, "zscan"))
        res["holds"] = holds(d, "ramp", 20, 5, cals, a.nm_px)
    if a.plan == "rotation":
        res["rotation"] = rotation(d, lut_clusters(os.path.join(a.run, "zscan")), a.nm_px)
    if a.plan == "zscan_field":
        res["zscan_field"] = zscan_field(d)
    if a.plan == "field":
        res.update(field(d))
    if a.plan == "drift":
        crops, idx, _ = load(d, "drift")
        sel = np.arange(0, len(crops), 150)                  # one frame per second
        z = z_series(crops[sel], lut_clusters(os.path.join(a.run, "zscan")))
        fx = np.array(res["segments"]["drift"]["fixed"])
        ok = np.array(res["segments"]["drift"]["beads_used"])[fx]
        xy5 = np.load(os.path.join(d, "drift.xy.npy"))[sel // 5]
        off = np.hypot(*(xy5 - xy5[:1]).transpose(2, 0, 1))      # px from the start; z needs the cross-120 window
        z[off > 6] = np.nan                                       # (h = 72) inside the 160 px crop: 8 px of room
        res["z_valid_minutes"] = float(np.sum(~np.isnan(z[:, ok]).all(1)) / 60)
        zc = np.nanmean(z[:, ok], 1) * 1000
        good_t = ~np.isnan(zc)
        res["z_drift_nm_per_min"] = float(np.polyfit((idx[sel, 1] - idx[0, 1])[good_t] / 60, zc[good_t], 1)[0])
        res["z_range_nm"] = float(np.nanmax(zc) - np.nanmin(zc))
        np.save(os.path.join(d, "drift.z_1hz.npy"), z)
        xy = np.load(os.path.join(d, "drift.xy.npy"))
        rate = res["segments"]["drift"]["rate_hz"]
        fx = np.array(res["segments"]["drift"]["fixed"])
        ok = np.array(res["segments"]["drift"]["beads_used"])[fx]
        for k, nm in enumerate(("x", "y")):
            res[f"allan_common_{nm}_nm"] = allan(np.nanmean(xy[:, ok, k], 1) * a.nm_px, rate)
            res[f"allan_diff_{nm}_nm"] = allan((xy[:, ok[0], k] - xy[:, ok[1], k]) / np.sqrt(2) * a.nm_px, rate)
    with open(os.path.join(d, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1)[:3000])


if __name__ == "__main__":
    sys.exit(main())
