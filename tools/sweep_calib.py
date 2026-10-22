"""Compare calibration settings (band-pass LOW / HIGH, forget radius) offline, on recorded data only.

A. Re-track recorded frames with each setting (FastKernel + the main VI's frame-to-frame rule) and measure the
   reference bead's z noise per frame: std of successive differences / sqrt(2). Also lost-bead frames.
B. Interpolation test on the .cal stack itself: build the cluster from the even slices (0.2 um apart) and look up
   each odd slice, whose true z lies halfway. Reports the RMS and worst error. No images needed.

Usage: .venv/Scripts/python tools/sweep_calib.py [n_frames] [out.csv]
The settings LabVIEW used are in the .cal; nothing here changes a file.
"""
import csv
import itertools
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from conftest import FIXTURE, read_image

from mtpy import calib
from mtpy.fast import FastKernel
from mtpy.lvfiles import read_cal
from mtpy.track import DEFAULT, lv_round, z_phase

CROSS = 120
REF = 0                                        # bead 1 = the reference bead in the fixture (docs/rig-facts.md)


def retrack(frames, xy0, clusters):
    """The Tracker state machine on FastKernel. Returns z (frames, beads) with NaN for -1 and the lost-frame count."""
    win_rs, win_h = calib.windows(CROSS)
    fk = FastKernel(CROSS, win_rs, win_h, clusters)
    nb = len(clusters)
    xy, good, lost = xy0.copy(), np.ones(nb, bool), False
    z = np.full((len(frames), nb), np.nan)
    n_lost = 0
    for f, img in enumerate(frames):
        if lost:
            xy, good = xy0.copy(), np.ones(nb, bool)
        xyz, _, g = fk.track(img, [lv_round(v) for v in xy[:, 0]], [lv_round(v) for v in xy[:, 1]], good)
        lost = bool((xyz == -1.0).any())
        n_lost += lost
        ok = xyz[:, 2] != -1.0
        z[f, ok] = xyz[ok, 2]
        xy, good = xyz[:, :2].copy(), g
    return z, n_lost


def frame_noise(v):
    v = v[np.isfinite(v)]
    return np.std(np.diff(v)) / np.sqrt(2) if v.size > 10 else np.nan


def interpolation_error(cal, low, high, forget):
    """Test B for every bead: cluster from even slices, odd slices as input. Errors in um."""
    half = CROSS // 2
    even = dict(cal, stack=cal["stack"][:, ::2], z_step=2 * cal["z_step"],
                bead_i32=np.tile([low, high, forget], (len(cal["stack"]), 1)))
    errs = []
    for b, cl in enumerate(calib.clusters(even)):
        for s in range(5, cal["stack"].shape[1] - 6, 2):           # away from the stack ends
            zi, _ = z_phase(cal["stack"][b, s, half - 1:], half, cl, DEFAULT)
            errs.append(zi * cl["z_step"] - s * cal["z_step"])
    e = np.abs(errs)
    return np.sqrt(np.mean(e ** 2)), e.max()


def main():
    n_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("sweep_calib.csv")
    cal = read_cal(FIXTURE / "cal002")
    t0 = time.time()
    names = sorted(FIXTURE.glob("img*.tif"))[:n_frames]          # the recorded frames, with the camera's own gaps
    frames = [read_image(int(p.stem[3:])).astype(np.uint8) for p in names]
    print(f"{len(frames)} frames loaded in {time.time() - t0:.0f} s; stored setting per bead: {cal['bead_i32'].tolist()}")
    grid = [(lo, hi, fg) for lo, hi, fg in itertools.product((0, 2, 4, 6), range(13, 50, 3), range(4, 34, 3))
            if hi - lo >= 8]
    grid.insert(0, tuple(int(v) for v in cal["bead_i32"][REF]))   # the stored setting first, as the baseline
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["low", "high", "forget", "ref_z_noise_nm", "beads_z_noise_nm", "lost_frames", "interp_rms_nm",
                    "interp_max_nm"])
        for k, (lo, hi, fg) in enumerate(grid):
            z, n_lost = retrack(frames, cal["xy"], calib.clusters(cal, lo, hi, fg))
            noise = [1000 * frame_noise(z[:, b]) for b in range(z.shape[1])]
            rms, mx = interpolation_error(cal, lo, hi, fg)
            w.writerow([lo, hi, fg, f"{noise[REF]:.3f}", ";".join(f"{v:.2f}" for v in noise), n_lost,
                        f"{1000 * rms:.2f}", f"{1000 * mx:.2f}"])
            f.flush()
            if k % 20 == 0:
                print(f"{k}/{len(grid)} ({lo},{hi},{fg}): ref z noise {noise[REF]:.2f} nm, lost {n_lost}, "
                      f"interp rms {1000 * rms:.1f} nm  [{time.time() - t0:.0f} s]", flush=True)
    print("written", out)


if __name__ == "__main__":
    main()
