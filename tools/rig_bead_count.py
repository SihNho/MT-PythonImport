"""Rig 2026-11-01 (owner: "the frame numbers against the bead count too"): tracking time per frame, latency and drops
against the number of beads, numba and CUDA, at the camera's 90 Hz. The beads are copies of the owner's four (the
.cal of the motion bench repeated N / 4 times: the kernel's work per bead is the same whether beads are distinct or
not). RUN_S seconds per point. Output in OUT: cal_<n>, count_<n>_<exec>.h5, report.json.
"""
import json
import os
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
import rig_refbead_track as T

from mtpy import api
from mtpy.api import events
from mtpy.lvfiles import read_cal, write_cal

OUT = os.environ.get("OUT", r"G:\l2s_rig_data\2026-11-01_bead_count")
CAL = os.environ.get("CAL", r"G:\l2s_rig_data\2026-11-01_motion_noise\cal_motion")
T.OUT = OUT
COUNTS = [int(c) for c in os.environ.get("COUNTS", "4,16,64,128,256").split(",")]
RUN_S = float(os.environ.get("RUN_S", "15"))
EXECUTORS = [("numba", False), ("gpu", True)]
say = T.say


def main():
    os.makedirs(OUT, exist_ok=True)
    base = read_cal(CAL)
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "cal": CAL, "run_s": RUN_S, "runs": []}
    with events.as_caller("script:rig-bead-count@1"):
        report["connect"] = T.connect()
        try:
            for n in COUNTS:
                k = -(-n // len(base["xy"]))
                cal = dict(base)
                cal["xy"] = np.tile(base["xy"], (k, 1))[:n]
                cal["stack"] = np.tile(base["stack"], (k, 1, 1))[:n]
                cal["bead_i32"] = np.tile(base["bead_i32"], (k, 1))[:n]
                cal["bead_flags"] = np.zeros(n, dtype=np.int32)
                cal_path = os.path.join(OUT, f"cal_{n}")
                write_cal(cal_path, cal)
                ids = list(range(1, n + 1))
                api.beads.select(ids, cal_path=cal_path)
                roles = {i: "reference" for i in ids}
                for ex, gpu in EXECUTORS:
                    row = T.one_run(f"count_{n}_{ex}", "current", gpu, RUN_S, roles)
                    row["beads"] = n
                    report["runs"].append(row)
                    T.dump(report, "report.json")
        except Exception as e:  # noqa: BLE001
            say(f"RESULT session FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
            report["error"] = f"{type(e).__name__}: {e}"
        finally:
            if api.acq.running():
                api.acq.stop()
            try:
                api.devices.disconnect()
                say(f"RESULT disconnect clean; lock {api.rig.status()}")
            except Exception as e:  # noqa: BLE001
                say(f"RESULT disconnect FAILED: {type(e).__name__}: {e}")
    report["error_events"] = [{"kind": e.kind, "extra": e.extra} for e in events.events()
                              if e.kind in ("device_error", "refused", "estop")]
    T.dump(report, "report.json")
    say("beads  exec   frames  fps    gaps drops  track ms p50/p99   latency ms p50/p99  ring  not written")
    for r in report["runs"]:
        if "error" in r:
            say(f"{r['beads']:5d}  {r['name'].split('_')[-1]:5s}  {r['error'][:80]}")
            continue
        say(f"{r['beads']:5d}  {r['name'].split('_')[-1]:5s}  {r['frames_tracked']:6d}  {r['fps_measured']:.2f}  {r['camera_gaps']:4d} "
            f"{r['pipeline_drops']:5d}  {r['track_ms_p50']:6.2f} / {r['track_ms_p99']:6.2f}   "
            f"{r['latency_ms_p50']:6.2f} / {r['latency_ms_p99']:6.2f}   {r.get('frames_not_written')}")
    say(json.dumps(report["error_events"], default=str)[:400])


if __name__ == "__main__":
    main()
