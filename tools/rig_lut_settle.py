"""Rig 2026-11-01 (owner: "LUT 새로 만들어서 재확인 ㄱㄱ", after the PC's unexpected shutdown at 07:53): connect every device
(MT-TIRF), check the four hand-picked reference beads are still where they were, z scan with the new 0.2 s settle
(60 x 100 nm, 10 frames averaged), then the piezo step run (current / numba) and disconnect. Output in OUT; the analysis
is tools/rig_refbead_analyze.py OUT."""
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
from mtpy.gui import zscan

OUT = r"G:\l2s_rig_data\2026-11-01_lut_settle"
T.OUT = OUT
# the sample moved (+54, +7) px between 2026-10-31 23:24 and 2026-11-01 13:53 (the PC rebooted in between);
# the four beads found again by correlation and refined on the 13:53 frame
T.PICKS = [(814.66, 276.06), (1038.99, 629.87), (428.02, 859.6), (426.85, 303.69)]
say = T.say


def check_picks():
    """Average 10 frames, refine each old pick with the tracker's XY stage; abort when a bead moved > 5 px."""
    api.acq.start(record=False, name="check")
    try:
        img = api.acq.average(10, timeout_s=10)
    finally:
        api.acq.stop()
    np.save(os.path.join(OUT, "frame.npy"), np.clip(np.rint(img), 0, 255).astype(np.uint8))
    xy = []
    for x, y in T.PICKS:
        xo, yo, _ = zscan.bead_profile(img, x, y, 120)
        d = float(np.hypot(xo - x, yo - y))
        say(f"  pick ({x:.1f}, {y:.1f}) -> refined ({xo:.2f}, {yo:.2f}), moved {d:.2f} px, "
            f"local min/mean {img[int(y) - 10:int(y) + 10, int(x) - 10:int(x) + 10].min():.0f}/{img.mean():.0f}")
        if d > 5:
            raise RuntimeError(f"bead at {x, y} moved {d:.1f} px since 10-31: picks need redoing (frame.npy saved)")
        xy.append((xo, yo))
    return np.array(xy)


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "settle_s": zscan.SETTLE_S, "runs": []}
    with events.as_caller("script:rig-lut-settle@1"):
        report["connect"] = T.connect()
        try:
            xy = check_picks()
            report["xy"] = xy.tolist()
            cal_path = os.path.join(OUT, "cal_settle")
            api.acq.start(record=False, name="zscan")
            try:
                t0 = time.monotonic()
                zscan.run(cal_path, xy, slices=60, step_nm=100.0, n_avg=10, cross=120,
                          progress=lambda i, n: (i % 10 == 0) and say(f"  slice {i}/{n}"))
                report["zscan_s"] = time.monotonic() - t0
                say(f"RESULT z scan with settle {zscan.SETTLE_S} s: 60 x 100 nm in {report['zscan_s']:.0f} s; "
                    f"focus back at {api.focus.position():.3f} um")
            finally:
                api.acq.stop()
            ids = list(range(1, len(xy) + 1))
            api.beads.select(ids, cal_path=cal_path)
            roles = {i: "reference" for i in ids}
            report["runs"].append(T.one_run("piezo_settle_current_numba", "current", False, 0, roles, during=T.piezo_steps))
            report["piezo_um"] = T.PIEZO_UM
        except Exception as e:  # noqa: BLE001
            say(f"RESULT session FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
            report["error"] = f"{type(e).__name__}: {e}"
        finally:
            if api.acq.running():
                api.acq.stop()
            t1 = time.monotonic()
            try:
                api.devices.disconnect()
                report["disconnect_s"] = time.monotonic() - t1
                say(f"RESULT disconnect clean in {report['disconnect_s']:.1f} s; lock {api.rig.status()}")
            except Exception as e:  # noqa: BLE001
                report["disconnect_error"] = f"{type(e).__name__}: {e}"
                say(f"RESULT disconnect FAILED: {type(e).__name__}: {e}")
    report["error_events"] = [{"kind": e.kind, "extra": e.extra} for e in events.events()
                              if e.kind in ("device_error", "refused", "estop")]
    for e in report["error_events"]:
        say("EVENT", e["kind"], json.dumps(e["extra"], default=str)[:300])
    T.dump(report, "report.json")


if __name__ == "__main__":
    main()
