"""Tracking speed through the acquisition pipeline (WP3) at 150 Hz on the simulated camera replaying the fixture.
For 5, 20 and 80 beads (the 5 recorded beads repeated, as in tools/bench_speed.py) it runs camera thread -> ring ->
tracking worker and prints, per case:
- first-frame delay: wall-clock time from `start_acquisition()` to the first frame received, and to its result
  (received + that frame's receive -> result latency);
- wall-clock received / tracked rates over `seconds` after the first frame, the sim producer's own rate (buffers
  produced / wall time) and `fps_measured` (from the sim camera clock, which is the SCHEDULED frame time: it reads
  150 Hz even when the sim producer falls behind);
- tracking time in the worker (p50 / p99 / max), receive -> result latency, pipeline drops and camera gaps.
Frame sources (review l2s-wp3-r1):
- `disk-cold`: SimCamera as shipped (one TIFF read per frame in its producer thread) on fixture files this script
  has not read before (cold unless the OS file cache still holds them from another run);
- `disk`: the same from the first fixture file (files the tests and earlier benches read, usually cached);
- `memory`: the first N fixture frames preloaded and cycled (no file read in the camera thread).
Usage: .venv/Scripts/python tools/bench_pipeline.py [seconds_per_case] [preloaded_frames]"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from conftest import FIXTURE

from mtpy import api, calib  # noqa: F401 - api must load before mtpy.devices (existing import cycle)
from mtpy.acq import Beads, Pipeline, make_kernel
from mtpy.devices.sim import SimCamera
from mtpy.lvfiles import read_cal

RATE_HZ = 150.0
COLD_START = {5: 6000, 20: 7000, 80: 8000}       # fixture file windows for the cold disk cases (11822 files)
seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
n_pre = int(sys.argv[2]) if len(sys.argv) > 2 else 300


class MemoryCamera(SimCamera):
    """SimCamera whose frames come from images preloaded in memory (full sensor ROI only)."""

    def __init__(self, fixture, images):
        super().__init__(fixture)
        self.images = images

    def _image(self, b):
        return self.images[b % len(self.images)]


def read_ms(files):
    t = []
    for f in files:
        t0 = time.perf_counter()
        np.asarray(Image.open(f))
        t.append((time.perf_counter() - t0) * 1e3)
    return float(np.median(t)), float(np.percentile(t, 99))


def run(cam, beads, kernel):
    cam.open()
    cam.set("rate_Hz", RATE_HZ)
    pipe = Pipeline(cam, beads, kernel, stats_len=100000, t_source=cam.timestamp_source)
    pipe.start()
    pipe.begin_segment(cam.settings())
    t0 = time.perf_counter()
    cam.start_acquisition()
    pipe.wait_frames(1, 10)
    t_rx = time.perf_counter()
    rx0, tr0 = pipe.frames_received, pipe.frames_tracked
    time.sleep(seconds)
    rx1, tr1, tb, produced = pipe.frames_received, pipe.frames_tracked, time.perf_counter(), cam.last_buffer + 1
    cam.stop_acquisition()
    pipe.end_segment()
    complete = pipe.stop()
    cam.close()
    st = pipe.status()
    tm, lat = np.array(pipe._track_ms), np.array(pipe._latency_ms)
    return {"first_rx_ms": (t_rx - t0) * 1e3, "first_tr_ms": (t_rx - t0) * 1e3 + lat[0],
            "rx_hz": (rx1 - rx0) / (tb - t_rx), "tr_hz": (tr1 - tr0) / (tb - t_rx), "fps": st["fps_measured"],
            "produced_hz": produced / (tb - t0), "p50": st["track_ms_p50"], "p99": st["track_ms_p99"],
            "max": float(tm.max()), "lat50": st["latency_ms_p50"], "lat99": st["latency_ms_p99"],
            "drops": st["pipeline_drops"], "gaps": st["camera_gaps"], "stop": complete}


cal = read_cal(FIXTURE / "cal002")
clusters = calib.clusters(cal)
cross = cal["stack"].shape[2] + 1
win_rs, win_h = calib.windows(cross)
files = SimCamera(FIXTURE).files
cold50, cold99 = read_ms(files[9000:9100])                     # never read by this script's cases
warm50, warm99 = read_ms(files[:100])
t0 = time.perf_counter()
images = [np.asarray(Image.open(f)).copy() for f in files[:n_pre]]
print(f"{RATE_HZ:g} Hz sim camera replaying {FIXTURE}; {seconds:g} s per case after the first frame; frame period "
      f"{1e3 / RATE_HZ:.2f} ms")
print(f"TIFF read per frame (PIL): first-time files median {cold50:.2f} / p99 {cold99:.2f} ms, files 0-99 median "
      f"{warm50:.2f} / p99 {warm99:.2f} ms; preloaded {len(images)} frames "
      f"({sum(i.nbytes for i in images) / 1e6:.0f} MB) in {time.perf_counter() - t0:.1f} s")
print("source     beads  1st rx ms  1st result ms  rx/s    trk/s   produced/s  fps(sim clock)  trk p50  p99   max    "
      "lat p50  p99    drops gaps stop")
rows = []
for source in ("disk-cold", "disk", "memory"):
    for nb in (5, 20, 80):
        rep = nb // 5
        beads = Beads(tuple(range(1, nb + 1)), np.tile(cal["xy"][:, :2], (rep, 1)), clusters * rep, cross, win_rs,
                      win_h)
        kernel = make_kernel(beads)
        kernel.track(np.zeros((1024, 1280), dtype=np.uint8), np.rint(beads.xy0[:, 0]).astype(np.int64),
                     np.rint(beads.xy0[:, 1]).astype(np.int64), np.ones(nb, dtype=bool))      # warm-up
        cam = MemoryCamera(FIXTURE, images) if source == "memory" else SimCamera(FIXTURE)
        if source == "disk-cold":
            cam.files = files[COLD_START[nb]:COLD_START[nb] + 1000]
        r = run(cam, beads, kernel)
        rows.append({"source": source, "beads": nb, **{k: round(v, 2) if isinstance(v, float) else v
                                                       for k, v in r.items()}})
        print(f"{source:10s} {nb:5d} {r['first_rx_ms']:10.2f} {r['first_tr_ms']:14.2f} {r['rx_hz']:7.2f} "
              f"{r['tr_hz']:7.2f} {r['produced_hz']:11.2f} {r['fps']:15.2f} {r['p50']:8.2f} {r['p99']:5.2f} "
              f"{r['max']:6.2f} {r['lat50']:8.2f} {r['lat99']:6.2f} {r['drops']:6d} {r['gaps']:4d} "
              f"{'ok' if r['stop'] else 'INCOMPLETE'}")
print("BENCH " + json.dumps({"status": "PASS" if all(r["stop"] for r in rows) else "FAIL", "rate_Hz": RATE_HZ,
                              "seconds": seconds, "read_ms_first_time_p50": round(cold50, 2),
                              "read_ms_files0_p50": round(warm50, 2), "rows": rows}))
