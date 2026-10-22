"""Tracking speed against the 150 Hz budget (6 ms per frame, plan phase 3 / decision 0002).
Replays recorded frames through FastKernel for N beads (the 5 recorded beads repeated) and several thread counts, and
prints per-frame time percentiles. Usage: .venv/Scripts/python tools/bench_speed.py [n_frames]"""
import sys
import time
from pathlib import Path

import numba
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from conftest import load_harness_inputs, load_reference, read_image

from mtpy.fast import FastKernel
from mtpy.track import lv_round

n_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
win_rs, win_h, cals = load_harness_inputs()
rows = load_reference()[1:n_frames + 1]
frames = [read_image(r["frame"]).astype(np.uint8) for r in rows]
starts = [np.array(r["ff"]).reshape(-1, 3)[:, :2] for r in load_reference()[:n_frames]]
print(f"{len(frames)} frames, numba {numba.__version__}, {numba.config.NUMBA_NUM_THREADS} threads available")
print("beads threads   p50 ms   p99 ms   max ms   (budget 6 ms)")
for nb in (5, 10, 20, 40, 80):
    rep = nb // 5
    fk = FastKernel(120, win_rs, win_h, cals * rep)
    for threads in (1, 4, numba.config.NUMBA_NUM_THREADS):
        numba.set_num_threads(threads)
        t = []
        for img, st in zip(frames, starts):
            xin = [lv_round(v) for v in np.tile(st[:, 0], rep)]
            yin = [lv_round(v) for v in np.tile(st[:, 1], rep)]
            t0 = time.perf_counter()
            fk.track(img, xin, yin, np.ones(nb, dtype=bool))
            t.append(time.perf_counter() - t0)
        t = np.array(t[10:]) * 1e3                      # the first calls include compilation / cache load
        print(f"{nb:5d} {threads:7d} {np.percentile(t, 50):8.2f} {np.percentile(t, 99):8.2f} {t.max():8.2f}")
