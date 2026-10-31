"""Offline analysis of rig_refbead_track.py runs: per run and bead the mean / std of x, y, z, the lost count, the
bead-pair differential noise (common motion removed), repeatability of the same bead across repeats and methods, and
the piezo run: mean tracked z per hold against the commanded step. Writes analysis.json next to the runs."""
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
from mtpy.data import read_run

OUT = sys.argv[1] if len(sys.argv) > 1 else r"G:\l2s_rig_data\2026-10-31_refbead_track"
NM_PX = 203.0


def stats(run):
    mt = run["mt"]
    x, y, z = mt["x_px"], mt["y_px"], mt["z_um"]
    lost = (mt["bead_lost"] > 0) | (mt["bead_good"] == 0) | np.isnan(x)
    ok = ~lost
    nb = x.shape[1]
    per = []
    for b in range(nb):
        m = ok[:, b]
        per.append({"n": int(m.sum()), "lost": int(lost[:, b].sum()),
                    "x_mean": float(x[m, b].mean()), "y_mean": float(y[m, b].mean()), "z_mean_um": float(z[m, b].mean()),
                    "x_sd_nm": float(x[m, b].std() * NM_PX), "y_sd_nm": float(y[m, b].std() * NM_PX),
                    "z_sd_nm": float(z[m, b].std() * 1000)})
    diff = []
    for a in range(nb):
        for b in range(a + 1, nb):
            m = ok[:, a] & ok[:, b]
            if m.sum() > 10:
                diff.append([float(np.std(x[m, a] - x[m, b]) / np.sqrt(2) * NM_PX),
                             float(np.std(y[m, a] - y[m, b]) / np.sqrt(2) * NM_PX),
                             float(np.std(z[m, a] - z[m, b]) / np.sqrt(2) * 1000)])
    d = np.median(diff, axis=0) if diff else [np.nan] * 3
    t = mt["t_host"]
    return {"frames": len(t), "duration_s": float(t[-1] - t[0]) if len(t) > 1 else 0.0,
            "lost_before_sum": int(mt["lost_before"].sum()), "dropped": int(mt["dropped"].sum()),
            "track_error": int(mt["track_error"].sum()), "track_ms_p50": float(np.nanpercentile(mt["track_ms"], 50)),
            "track_ms_p99": float(np.nanpercentile(mt["track_ms"], 99)),
            "diff_noise_nm_xyz": [float(v) for v in d], "beads": per}


def piezo(run, rep):
    mt, ev = run["mt"], run["events"].get("mark")
    if ev is None:
        return None
    t, z = mt["t_host"], mt["z_um"]
    ok = (mt["bead_lost"] == 0) & (mt["bead_good"] > 0)
    marks = sorted(zip(ev["t_host"], ev["data"]), key=lambda p: p[0])
    holds = []
    for i, (t0, data) in enumerate(marks):
        text = (data.get("text") if isinstance(data, dict) else json.loads(data).get("text")) or ""
        if not text.startswith("piezo ") or text.startswith("piezo back"):
            continue
        dz = float(text.split()[1])
        t1 = marks[i + 1][0] if i + 1 < len(marks) else t[-1]
        m = (t > t0 + 0.8) & (t < t1 - 0.2)         # settle 0.8 s, exclude the move
        zb = [float(z[m & ok[:, b], b].mean()) if (m & ok[:, b]).sum() > 5 else float("nan") for b in range(z.shape[1])]
        holds.append({"dz_um": dz, "frames": int(m.sum()), "z_mean_um": zb, "readback": text})
    base = [h for h in holds if h["dz_um"] == 0.0]
    z0 = np.nanmean([h["z_mean_um"] for h in base], axis=0) if base else np.zeros(z.shape[1])
    cmd = np.array([h["dz_um"] for h in holds])
    fit = []
    for b in range(z.shape[1]):
        zz = np.array([h["z_mean_um"][b] for h in holds]) - z0[b]
        g = ~np.isnan(zz)
        slope, off = np.polyfit(cmd[g], zz[g], 1) if g.sum() > 2 else (np.nan, np.nan)
        resid = zz[g] - (slope * cmd[g] + off)
        fit.append({"slope": float(slope), "offset_um": float(off), "rms_resid_nm": float(np.sqrt(np.mean(resid ** 2)) * 1000),
                    "zero_drift_nm": float(np.nanstd([h["z_mean_um"][b] for h in base]) * 1000) if len(base) > 1 else None})
    return {"holds": holds, "fit_per_bead": fit}


def main():
    with open(os.path.join(OUT, "report.json"), encoding="utf-8") as f:
        rep = json.load(f)
    out = {"runs": {}, "report_runs": rep["runs"]}
    for f in sorted(glob.glob(os.path.join(OUT, "*.h5"))):
        name = os.path.basename(f)[:-3]
        run = read_run(f)
        if "x_px" not in run["mt"]:
            continue
        out["runs"][name] = stats(run)
        if name.startswith("piezo"):
            out["piezo"] = piezo(run, rep)
    # repeatability: the first bead's mean position across the repeats of each method, and across methods
    by_method = {}
    for name, s in out["runs"].items():
        if name.startswith("piezo"):
            continue
        key = name.rsplit("_", 1)[0]
        by_method.setdefault(key, []).append(s)
    out["repeatability"] = {}
    for key, runs in by_method.items():
        b0 = [r["beads"][0] for r in runs]
        out["repeatability"][key] = {
            "runs": len(runs),
            "x_mean_spread_nm": float(np.std([b["x_mean"] for b in b0]) * NM_PX),
            "y_mean_spread_nm": float(np.std([b["y_mean"] for b in b0]) * NM_PX),
            "z_mean_spread_nm": float(np.std([b["z_mean_um"] for b in b0]) * 1000),
            "z_mean_um": [b["z_mean_um"] for b in b0], "x_mean_px": [b["x_mean"] for b in b0],
            "lost_total": int(sum(b["lost"] for b in b0)),
            "diff_noise_nm_xyz_median": [float(v) for v in np.median([r["diff_noise_nm_xyz"] for r in runs], axis=0)],
            "track_ms_p50_median": float(np.median([r["track_ms_p50"] for r in runs])),
            "track_ms_p99_max": float(max(r["track_ms_p99"] for r in runs)),
            "frames": [r["frames"] for r in runs], "dropped": sum(r["dropped"] for r in runs),
            "lost_before": sum(r["lost_before_sum"] for r in runs)}
    with open(os.path.join(OUT, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"{'method':24s} {'runs':>4s} {'frames':>7s} {'lost':>5s} {'drop':>4s} {'gaps':>4s} {'dx/dy/dz noise nm':>20s} "
          f"{'z mean per run (um)':>28s} {'spread x/y/z nm':>18s} {'ms p50/p99':>11s}")
    for key, r in out["repeatability"].items():
        d = r["diff_noise_nm_xyz_median"]
        print(f"{key:24s} {r['runs']:4d} {sum(r['frames']):7d} {r['lost_total']:5d} {r['dropped']:4d} {r['lost_before']:4d} "
              f"{d[0]:6.1f}/{d[1]:5.1f}/{d[2]:6.1f} {[round(v, 3) for v in r['z_mean_um']]!s:>28s} "
              f"{r['x_mean_spread_nm']:5.1f}/{r['y_mean_spread_nm']:5.1f}/{r['z_mean_spread_nm']:5.1f} "
              f"{r['track_ms_p50_median']:5.2f}/{r['track_ms_p99_max']:5.2f}")
    if out.get("piezo"):
        print("piezo: dz_um -> tracked z (um) per bead")
        for h in out["piezo"]["holds"]:
            print(f"  {h['dz_um']:+.2f}  {[round(v, 3) for v in h['z_mean_um']]}  ({h['frames']} frames)")
        for b, f in enumerate(out["piezo"]["fit_per_bead"]):
            print(f"  bead {b + 1}: slope {f['slope']:.4f}, rms residual {f['rms_resid_nm']:.1f} nm, zero drift {f['zero_drift_nm']}")


if __name__ == "__main__":
    main()
