r"""refbead_params.py - offline search for calibration / tracking parameters that lower the z noise at the 50x
objective (203 nm / px), on the reference-bead z-scans of 2026-10-26/27 (no device).

  py tools/refbead_params.py cache   -> radial profiles of every z-scan frame (cross 120 and others), .npz next to the data
  py tools/refbead_params.py sweep   -> noise / accuracy table for each parameter set (printed, and params_sweep.json)

Noise = the per-frame z scatter inside one slice (0.2 s, the piezo at rest). On the 10-bead scan of 2026-10-26 it is
taken as the DIFFERENCE of two beads / sqrt 2, which removes the common stage / focus motion and leaves the tracking
noise. The LUT is always made from the first half of each slice's frames and tested on the second half, so the test
frames are out of sample.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import refbead_analyze as A

from mtpy import calib, track

RUN26 = r"G:\l2s_rig_data\2026-10-26_refbead\zscan"          # 10 beads, 100 nm, +-5 um
RUN27 = r"G:\l2s_rig_data\2026-10-27_refbead\zfine_at"       # 2 beads, 100 nm LUT scan + 50 / 20 nm scans
CROSSES = (80, 100, 120)
FIXED26 = [0, 1, 2, 4, 6, 7, 8, 9]                             # beads 3 and 5 are loose


def profiles(crops, frames, beads, cross):
    """(frames, beads, cross/2) radial profiles at the Croquette centre, nan where tracking fails. Reads the memmap
    one frame at a time (a z-scan is several GB)."""
    half_crop, h = crops.shape[2] // 2, track.lv_round(cross * 0.6)
    win_rs, win_h = calib.windows(cross)
    out = np.full((len(frames), len(beads), cross // 2), np.nan)
    for k, f in enumerate(frames):
        for j, b in enumerate(beads):
            sub = crops[f, b, half_crop - h:half_crop + h, half_crop - h:half_crop + h]
            try:
                _, _, sx, sy = track.xy_croquette(sub, h, half_crop, half_crop, cross, win_rs, win_h, track.DEFAULT)
                out[k, j] = track.radial_profile(sub, h + sx, h + sy, cross // 2)
            except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                pass
    return out


def slices(d, seg):
    """[(name, commanded z um, frame indices)] of a z-scan segment."""
    crops, idx, _ = A.load(d, seg)
    with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as f:
        ev = [json.loads(line) for line in f if '"mark"' in line]
    st = {e["name"][:-6]: e for e in ev if e["name"].startswith(seg + "_") and e["name"].endswith("_start")}
    en = {e["name"][:-4]: e["buffer"] for e in ev if e["name"].startswith(seg + "_") and e["name"].endswith("_end")}
    out = []
    for n, e in st.items():
        z = e["z_units"] * 0.1 if "z_units" in e else int(n.split("_z")[-1]) * 0.1
        out.append((n, z, np.flatnonzero((idx[:, 0] > e["buffer"]) & (idx[:, 0] <= en[n]))))
    return crops, out


def cache():
    for d, seg, beads in ((RUN26, "zscan", FIXED26), (RUN27, "zscan", [1]), (RUN27, "zfine20", [1]),
                          (RUN27, "zfine50", [1])):
        crops, sl = slices(d, seg)
        fr = np.concatenate([s[2] for s in sl])
        for cross in CROSSES:
            path = os.path.join(d, f"{seg}.prof{cross}.npz")
            if os.path.exists(path):
                continue
            p = profiles(crops, fr, beads, cross)
            np.savez(path, prof=p, frames=fr, beads=beads,
                     slice_name=[s[0] for s in sl], slice_z=[s[1] for s in sl], slice_n=[len(s[2]) for s in sl])
            print("cached", path, p.shape, flush=True)


def load_cache(d, seg, cross, path=None):
    c = np.load(path or os.path.join(d, f"{seg}.prof{cross}.npz"))
    prof, n = c["prof"], c["slice_n"]
    edges = np.concatenate([[0], np.cumsum(n)])
    return [(str(c["slice_name"][i]), float(c["slice_z"][i]), prof[edges[i]:edges[i + 1]]) for i in range(len(n))]


def lut(sl, b, low, high, forget, cross, every=1, n_first=None, pick=None):
    """LUT of bead column b from the first half (or the first n_first) frames of every `every`-th slice."""
    use = [s for s in sl if pick is None or pick(s)]
    use = sorted(use, key=lambda s: s[1])[::every]
    st = []
    for _, _, p in use:
        k = len(p) // 2 if n_first is None else n_first
        st.append(np.nanmean(p[:k, b], 0))
    st = np.array(st)
    if np.isnan(st).any():
        return None, None
    z0, step = use[0][1], use[1][1] - use[0][1]
    return calib.prep_bead(np.concatenate([st[:, 1:][:, ::-1], st], 1), low, high, forget, step, cross), z0


def track_z(p, cal, z0, cross):
    try:
        return z0 + track.z_phase(p, cross // 2, cal, track.DEFAULT)[0] * cal["z_step"]
    except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
        return np.nan


def score(sl_test, cals, cross, beads, zlim=4.0, second_half=True):
    """cals: [(cluster, z0)] per bead column. Median per-slice z noise (nm): differential of bead pairs when there are >= 2 beads, else single bead; and the
    rms of the slice-mean error against the commanded z (nm, offset removed) - accuracy incl. the piezo's own steps."""
    noise, err = [], []
    for _, zc, p in sl_test:
        if abs(zc) > zlim:
            continue
        fr = p[len(p) // 2:] if second_half else p
        z = np.array([[track_z(fr[f, b], c, z0, cross) for b, (c, z0) in enumerate(cals)] for f in range(len(fr))])
        z = z[:, beads]
        if z.shape[1] >= 2:
            d = [(z[:, i] - z[:, j]) / np.sqrt(2) for i in range(z.shape[1]) for j in range(i + 1, z.shape[1])]
            noise.append(np.nanmedian([np.nanstd(x) for x in d]))
        else:
            noise.append(np.nanstd(z[:, 0]))
        err.append(np.nanmean(z, 0) - zc)
    err = np.array(err)
    err = err - np.nanmedian(err, 0)
    return float(np.nanmedian(noise) * 1000), float(np.sqrt(np.nanmean(err ** 2)) * 1000)


def build(sl, beads, low, high, forget, cross, **kw):
    """[(cluster, z0)] for every bead column, or None when a LUT slice is missing."""
    out = [lut(sl, b, low, high, forget, cross, **kw) for b in range(len(beads))]
    return None if any(c is None for c, _ in out) else out


def sweep():
    res = {}
    sl26 = {c: load_cache(RUN26, "zscan", c) for c in CROSSES}
    nb = len(FIXED26)
    print("== band-pass LOW / HIGH and forget radius (2026-10-26, 8 beads, cross 120, 100 nm LUT, differential)")
    for low in (0, 2, 4):
        for high in (15, 20, 25, 30, 40):
            for forget in (10, 15, 20, 25):
                cals = build(sl26[120], FIXED26, low, high, forget, 120)
                if cals is None:
                    continue
                n, e = score(sl26[120], cals, 120, list(range(nb)))
                res[f"band L{low} H{high} f{forget}"] = (n, e)
                print(f"  LOW {low:2d} HIGH {high:2d} forget {forget:2d}: noise {n:5.2f} nm  slice error {e:6.1f} nm",
                      flush=True)
    print("== profile length (cross), LOW 0 HIGH 25 forget 20 scaled with the cross")
    for cross in CROSSES:
        s = cross / 120
        cals = build(sl26[cross], FIXED26, 0, round(25 * s), round(20 * s), cross)
        n, e = score(sl26[cross], cals, cross, list(range(nb)))
        res[f"cross {cross}"] = (n, e)
        print(f"  cross {cross}: noise {n:5.2f} nm  slice error {e:6.1f} nm", flush=True)
    print("== frames averaged per LUT slice (cross 120, LOW 0 HIGH 25 forget 20)")
    for k in (1, 3, 7, 15):
        cals = build(sl26[120], FIXED26, 0, 25, 20, 120, n_first=k)
        n, e = score(sl26[120], cals, 120, list(range(nb)))
        res[f"frames {k}"] = (n, e)
        print(f"  {k:2d} frames: noise {n:5.2f} nm  slice error {e:6.1f} nm", flush=True)
    print("== LUT step from the 20 nm scan (2026-10-27, bead 1, LUT from the way up, test on the way down, +-1.8 um)")
    sl20 = load_cache(RUN27, "zfine20", 120)
    up = [s for s in sl20 if "_up" in s[0]]
    dn = [s for s in sl20 if "_dn" in s[0]]
    for every in (1, 2, 3, 5):
        cals = build(up, [1], 0, 25, 20, 120, every=every)
        n, e = score(dn, cals, 120, [0], zlim=1.8, second_half=False)
        res[f"step {20 * every} nm"] = (n, e)
        print(f"  LUT step {20 * every:3d} nm: noise {n:5.2f} nm  slice error {e:6.1f} nm", flush=True)
    with open(os.path.join(ROOT, "docs", "results", "2026-10-27-refbead-params.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)


def sweep_run(run, seg, beads, zlim=4.0, half_test=True):
    """The same parameter sweep on any z-scan segment (e.g. the tether plan's `zs_e1909`): band / forget, cross,
    frames per LUT slice, LUT step by sub-sampling the slices. `beads` are crop columns; with a reference bead among
    them the pairwise differential removes the common focus drift, and for a tethered bead paired with a reference
    it is std(tethered - reference) / sqrt 2, i.e. tracking noise plus the bead's own z fluctuation, the same for
    every method on the same frames (a relative comparison, decision 0023 item 4)."""
    res = {}
    crops, sl = slices(run, seg)
    fr = np.concatenate([x[2] for x in sl])
    cache_ = {}
    for cross in CROSSES:
        path = os.path.join(run, f"{seg}.prof{cross}.b{'-'.join(map(str, beads))}.npz")
        if not os.path.exists(path):
            pr = profiles(crops, fr, beads, cross)
            np.savez(path, prof=pr, frames=fr, beads=beads, slice_name=[x[0] for x in sl],
                     slice_z=[x[1] for x in sl], slice_n=[len(x[2]) for x in sl])
        cache_[cross] = load_cache(run, seg, cross, path)
    cols = list(range(len(beads)))
    print(f"== {seg}: band-pass / forget (cross 120, 100 nm LUT, beads {beads})")
    for low, high, forget in ((0, 25, 20), (0, 30, 10), (0, 40, 10), (0, 40, 15), (0, 50, 10), (2, 40, 10)):
        cals = build(cache_[120], beads, low, high, forget, 120)
        if cals is None:
            continue
        n, e = score(cache_[120], cals, 120, cols, zlim=zlim, second_half=half_test)
        res[f"band L{low} H{high} f{forget}"] = (n, e)
        print(f"  LOW {low:2d} HIGH {high:2d} forget {forget:2d}: noise {n:5.2f} nm  slice error {e:6.1f} nm", flush=True)
    print("== frames averaged per LUT slice (0/40/10)")
    for k in (1, 5, 15, 37):
        cals = build(cache_[120], beads, 0, 40, 10, 120, n_first=k)
        if cals is None:
            continue
        n, e = score(cache_[120], cals, 120, cols, zlim=zlim, second_half=half_test)
        res[f"frames {k}"] = (n, e)
        print(f"  {k:2d} frames: noise {n:5.2f} nm  slice error {e:6.1f} nm", flush=True)
    print("== LUT step by sub-sampling the slices (0/40/10)")
    for every in (1, 2, 3, 5):
        cals = build(cache_[120], beads, 0, 40, 10, 120, every=every)
        if cals is None:
            continue
        n, e = score(cache_[120], cals, 120, cols, zlim=zlim, second_half=half_test)
        res[f"step x{every}"] = (n, e)
        print(f"  every {every} slice: noise {n:5.2f} nm  slice error {e:6.1f} nm", flush=True)
    with open(os.path.join(run, f"{seg}.params.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    return res


def rest_noise(run, rest_seg, lut_seg, beads, ref, low=0, high=40, forget=10, cross=120, step=1):
    """z noise of each bead in a rest segment (bead at the clamp) with the LUT built from `lut_seg` (any z-scan of the
    same run: same or other magnet position / exposure). Returns per bead the std of z - z_ref (nm) at full rate
    and after 1 s averaging, so a measurement at one exposure / force can be scored against LUTs taken at others
    (owner 2026-10-28: the exposure must be the same in calibration and measurement; does the calibration force
    change the noise at the measurement force?)."""
    path = os.path.join(run, f"{lut_seg}.prof{cross}.b{'-'.join(map(str, beads))}.npz")
    if not os.path.exists(path):
        crops, sl = slices(run, lut_seg)
        fr = np.concatenate([x[2] for x in sl])
        np.savez(path, prof=profiles(crops, fr, beads, cross), frames=fr, beads=beads, slice_name=[x[0] for x in sl],
                 slice_z=[x[1] for x in sl], slice_n=[len(x[2]) for x in sl])
    cals = build(load_cache(run, lut_seg, cross, path), beads, low, high, forget, cross)
    if cals is None:
        return None
    crops, idx, _ = A.load(run, rest_seg)
    fr = np.arange(0, len(crops), step)
    prof = profiles(crops, fr, beads, cross)
    z = np.array([[track_z(prof[f, b], cals[b][0], cals[b][1], cross) for b in range(len(beads))]
                  for f in range(len(fr))])
    rate = (len(idx) - 1) / (idx[-1, 1] - idx[0, 1]) / step
    j = beads.index(ref)
    d = (z - z[:, [j]]) * 1000
    n1 = round(rate)
    out = {}
    for b, col in zip(beads, d.T):
        if b == ref:
            continue
        col = col[np.isfinite(col)]
        avg = col[:len(col) // n1 * n1].reshape(-1, n1).mean(1) if len(col) >= 2 * n1 else col
        out[str(b)] = {"sd_nm": round(float(col.std()), 2), "sd_1s_nm": round(float(avg.std()), 2),
                       "mean_um": round(float(np.nanmean(z[:, beads.index(b)])), 3)}
    return {"rest": rest_seg, "lut": lut_seg, "rate_hz": round(rate, 2), "beads": out}


if __name__ == "__main__":
    if sys.argv[1] == "rest-noise":             # py tools/refbead_params.py rest-noise <run> <rest seg> <lut seg> <beads> <ref>
        print(json.dumps(rest_noise(sys.argv[2], sys.argv[3], sys.argv[4], [int(v) for v in sys.argv[5].split(",")],
                                    int(sys.argv[6])), indent=1))
    elif sys.argv[1] == "sweep-run":              # py tools/refbead_params.py sweep-run <run dir> <segment> <beads 0,3,5>
        sweep_run(sys.argv[2], sys.argv[3], [int(v) for v in sys.argv[4].split(",")])
    else:
        {"cache": cache, "sweep": sweep}[sys.argv[1]]()
