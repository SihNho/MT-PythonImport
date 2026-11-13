"""The fair comparison of decision 0031: the bead windows one rig run kept (rig_accuracy.py WINDOWS=1 ->
windows_<run>.npz) tracked again, offline, with every Z method version on numba and on the FP32 GPU - the same frames
for every method, so the piezo's run-to-run variation (2026-11-01: 84 nm) is out of the comparison. Per variant the
columns of rig_accuracy.accuracy_of (the holds from the online run's marks), the not-good / lost bead-frames and the
time per frame; current_v1 on numba is checked against the online run (the same numbers).

  py tools/offline_windows.py windows_<run>.npz [...] [--gpu] [--json OUT]
"""
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
import rig_accuracy as A

from mtpy import api
from mtpy.acq.pipeline import BeadTracker, make_kernel
from mtpy.data import read_run
from mtpy.lvfiles import read_cal, write_cal
from mtpy.track import Z_METHODS


def canvas_of(d):
    """The windows side by side (ceil(sqrt(nb)) per row) and the beads' positions on that canvas."""
    win, org, xy = d["win"], d["org"], d["xy"]
    nb, W = win.shape[1], win.shape[2]
    cols = int(np.ceil(np.sqrt(nb)))
    frames = np.zeros((win.shape[0], (-(-nb // cols)) * W, cols * W), dtype=np.uint8)
    cxy = np.zeros((nb, 2))
    for b in range(nb):
        r, c = divmod(b, cols)
        frames[:, r * W:(r + 1) * W, c * W:(c + 1) * W] = win[:, b]
        cxy[b] = (c * W + xy[b][0] - org[b][0], r * W + xy[b][1] - org[b][1])
    return frames, cxy


def one(path, gpu):
    d = np.load(path)
    frames, cxy = canvas_of(d)
    run = read_run(str(d["run"]))
    cal = read_cal(str(d["cal"]))
    cal["xy"] = cxy
    canvas_cal = os.path.join(os.path.dirname(path), "cal_canvas")
    write_cal(canvas_cal, cal)
    nb = len(cxy)
    api.beads.select(list(range(1, nb + 1)), cal_path=canvas_cal)
    beads = api.beads.selected()
    t_of = dict(zip(run["mt"]["buffer_number"].tolist(), run["mt"]["t_host"].tolist()))
    t_tap = np.array([t_of.get(int(b), np.nan) for b in d["buf"]])
    online = {int(b): i for i, b in enumerate(run["mt"]["buffer_number"].tolist())}
    rows = []
    variants = [(zm, False, None) for zm in Z_METHODS] + ([(zm, True, None) for zm in Z_METHODS] if gpu else [])
    for zm, g, prec in variants:
        trk = BeadTracker(beads, make_kernel(beads, zm, g, prec))
        z, good, lost, ms = np.zeros((len(frames), nb)), np.zeros((len(frames), nb), bool), np.zeros((len(frames), nb), bool), []
        for i, img in enumerate(frames):
            t0 = time.perf_counter()
            xyz, gd = trk.step(img)
            ms.append((time.perf_counter() - t0) * 1e3)
            z[i], good[i], lost[i] = xyz[:, 2], gd, xyz[:, 2] == -1.0
        fake = {"mt": {"t_host": t_tap, "z_um": z, "bead_lost": lost.astype(np.uint8), "bead_good": good.astype(np.uint8)},
                "events": run["events"]}
        row = {"z_method": zm, "executor": "cuda" if g else "numba", "precision": "fp32" if g else "fp64",
               "frames": len(frames), "not_good": int((~good).sum()), "lost": int(lost.sum()),
               "ms_p50": float(np.median(ms[1:])), "ms_p99": float(np.percentile(ms[1:], 99)), "ms_max": float(max(ms[1:])),
               "accuracy": A.accuracy_of(fake, nb)}
        if zm == "current_v1" and not g:              # the online run was current_v1 numba: the same numbers?
            sel = [(i, online[int(b)]) for i, b in enumerate(d["buf"]) if int(b) in online]
            dz = np.abs(np.array([z[i] for i, _ in sel]) - np.array([run["mt"]["z_um"][j, :nb] for _, j in sel]))
            row["online_vs_offline_max_dz_nm"] = float(np.nanmax(dz) * 1000)
        rows.append(row)
        a = row["accuracy"]
        print(f"{zm:16s} {row['executor']:6s} {row['ms_p50']:5.2f}/{row['ms_p99']:5.2f} ms  not good {row['not_good']:5d}  "
              f"{A.fmt(a)}"
              + (f"  online vs offline {row['online_vs_offline_max_dz_nm']:.3f} nm" if "online_vs_offline_max_dz_nm" in row else ""))
    return {"windows": path, "run": str(d["run"]), "beads": nb, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npz", nargs="+")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    out = [one(p, a.gpu) for p in a.npz]
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, default=str)
        print("->", a.json)


if __name__ == "__main__":
    main()
