"""Tracking time through the acquisition pipeline (WP3) at 150 Hz on the simulated camera replaying the fixture.
For 5, 20 and 80 beads (the 5 recorded beads repeated, as in tools/bench_speed.py) it runs camera thread -> ring ->
tracking worker for a few seconds and prints the per-frame tracking time in the worker (p50 / p99 / max), the latency
from frame receipt to result, the measured frame rate, pipeline drops and camera gaps.
Usage: .venv/Scripts/python tools/bench_pipeline.py [seconds_per_case]"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from conftest import FIXTURE

from mtpy import api, calib  # noqa: F401 - api must load before mtpy.devices (existing import cycle)
from mtpy.acq import Beads, Pipeline, make_kernel
from mtpy.devices.sim import SimCamera
from mtpy.lvfiles import read_cal

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
cal = read_cal(FIXTURE / "cal002")
clusters = calib.clusters(cal)
cross = cal["stack"].shape[2] + 1
win_rs, win_h = calib.windows(cross)
print(f"150 Hz sim camera replaying {FIXTURE}, {seconds:g} s per case")
print("beads  frames  track p50 ms  p99 ms  max ms  latency p50 ms  p99 ms  fps     drops  gaps  (budget 6.67 ms)")
for nb in (5, 20, 80):
    rep = nb // 5
    beads = Beads(tuple(range(1, nb + 1)), np.tile(cal["xy"][:, :2], (rep, 1)), clusters * rep, cross, win_rs, win_h)
    kernel = make_kernel(beads)
    kernel.track(np.zeros((1024, 1280), dtype=np.uint8), np.rint(beads.xy0[:, 0]).astype(np.int64),
                 np.rint(beads.xy0[:, 1]).astype(np.int64), np.ones(nb, dtype=bool))      # warm-up
    cam = SimCamera(FIXTURE)
    cam.open()
    cam.set("rate_Hz", 150.0)
    pipe = Pipeline(cam, beads, kernel, stats_len=100000, t_source=cam.timestamp_source)
    pipe.start()
    pipe.begin_segment(cam.settings())
    cam.start_acquisition()
    time.sleep(seconds)
    cam.stop_acquisition()
    pipe.end_segment()
    pipe.stop()
    cam.close()
    st = pipe.status()
    tm = np.array(pipe._track_ms)
    print(f"{nb:5d} {st['frames_tracked']:7d} {st['track_ms_p50']:13.2f} {st['track_ms_p99']:7.2f} {tm.max():7.2f} "
          f"{st['latency_ms_p50']:15.2f} {st['latency_ms_p99']:7.2f} {st['fps_measured']:7.2f} "
          f"{st['pipeline_drops']:6d} {st['camera_gaps']:5d}")
