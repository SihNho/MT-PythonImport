"""Rig 2026-11-01 (owner: "measure the tracking noise while moving the piezo and the stage each, and the magnet too;
the same on the GPU; run the bench"): the owner's four beads at the owner's focus. LUT (0.2 s settle), then six
recorded runs - focus steps, stage x / y steps, magnet steps - each with the numba and the CUDA executor (`current`).
Every hold is marked; the analysis (below, also standalone with ANALYZE=1) gives per hold the differential noise
(median over the bead pairs, std of the pair difference / sqrt 2) and the mean shift from the first hold.
Motion: focus +-1 um, stage +-5 um (1 / 2 / 5 um steps), magnet 0..30 mm (dry sample: no force on anything).
Output in OUT: cal_motion, motion_<axis>_<exec>.h5, report.json, noise.json.
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
from mtpy.data import read_run
from mtpy.gui import zscan

OUT = os.environ.get("OUT", r"G:\l2s_rig_data\2026-11-01_motion_noise")
T.OUT = OUT
PICKS = [(1074.06, 573.43), (679.15, 704.65), (563.62, 793.33), (429.28, 478.23)]   # owner's beads 1, 13, 11, 8 (15:02)
NM_PX = 203.0
HOLD_S = 3.0
FOCUS_UM = [0.0, 0.5, 1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.0]
STAGE_UM = [(0, 0), (1, 0), (2, 0), (5, 0), (2, 0), (0, 0), (0, 1), (0, 2), (0, 5), (0, 2), (0, 0), (-5, 0), (0, 0),
            (0, -5), (0, 0)]
MAGNET_MM = [0.0, 5.0, 10.0, 20.0, 30.0, 20.0, 10.0, 5.0, 0.0]
EXECUTORS = [("numba", False), ("gpu", True)]
say = T.say


def check_picks():
    api.acq.start(record=False, name="check")
    try:
        img = api.acq.average(10, timeout_s=10)
    finally:
        api.acq.stop()
    np.save(os.path.join(OUT, "frame.npy"), np.clip(np.rint(img), 0, 255).astype(np.uint8))
    xy = []
    for x, y in PICKS:
        xo, yo, _ = zscan.bead_profile(img, x, y, 120)
        say(f"  pick ({x:.1f}, {y:.1f}) -> refined ({xo:.2f}, {yo:.2f}), moved {np.hypot(xo - x, yo - y):.2f} px")
        if np.hypot(xo - x, yo - y) > 15:
            raise RuntimeError(f"bead at {x, y} moved too far: picks need redoing (frame.npy saved)")
        xy.append((xo, yo))
    return np.array(xy)


def focus_steps():
    z0 = api.focus.position()
    try:
        for dz in FOCUS_UM:
            got = api.focus.move_to(z0 + dz).wait(10)
            api.acq.mark(f"focus {dz:+.2f} um (read back {got})")
            time.sleep(HOLD_S)
    finally:
        api.focus.move_to(z0).wait(10)
        api.acq.mark("focus back to start")


def stage_steps():
    x0, y0 = api.stage.position()
    try:
        for dx, dy in STAGE_UM:
            got = api.stage.move_to(x0 + dx / 1000.0, y0 + dy / 1000.0).wait(10)
            api.acq.mark(f"stage {dx:+d} {dy:+d} um (read back {got})")
            time.sleep(HOLD_S)
    finally:
        api.stage.move_to(x0, y0).wait(10)
        api.acq.mark("stage back to start")


def magnet_steps():
    try:
        for p in MAGNET_MM:
            got = api.magnet.move_to(p).wait(30)
            api.acq.mark(f"magnet {p:+.1f} mm (read back {got})")
            time.sleep(HOLD_S)
    finally:
        api.magnet.move_to(0.0).wait(30)
        api.acq.mark("magnet back to start")


SEQUENCES = [("focus", focus_steps), ("stage", stage_steps), ("magnet", magnet_steps)]


def analyze(path):
    """Per hold: frames, differential noise x / y / z (nm; median over bead pairs of std(pair difference) / sqrt 2),
    mean shift of the beads from the first hold (nm), and the per-frame noise over the whole run."""
    run = read_run(path)
    mt = run["mt"]
    t = mt["t_host"]
    p = np.stack([mt["x_px"] * NM_PX, mt["y_px"] * NM_PX, mt["z_um"] * 1000.0], axis=-1)      # (n, beads, 3) nm
    ok = (mt["bead_lost"] == 0) & (mt["bead_good"] > 0)
    p = np.where(ok[..., None], p, np.nan)
    nb = p.shape[1]
    pairs = [(i, j) for i in range(nb) for j in range(i + 1, nb)]

    def diff_noise(sel):
        return [float(np.nanmedian([np.nanstd(sel[:, i, k] - sel[:, j, k]) / np.sqrt(2) for i, j in pairs])) for k in range(3)]
    marks = sorted(zip(run["events"]["mark"]["t_host"], run["events"]["mark"]["data"]))
    holds, first = [], None
    for i, (t0, data) in enumerate(marks):
        text = (data if isinstance(data, dict) else json.loads(data)).get("text", "")
        if text.endswith("back to start"):
            continue
        t1 = marks[i + 1][0] if i + 1 < len(marks) else t[-1]
        m = (t > t0 + 0.8) & (t < t1 - 0.2)
        if m.sum() < 10:
            continue
        mean = np.nanmean(p[m], axis=0)                    # (beads, 3)
        if first is None:
            first = mean
        shift = np.nanmean(mean - first, axis=0)
        holds.append({"step": text.split(" (")[0], "frames": int(m.sum()), "noise_nm": diff_noise(p[m]),
                      "shift_nm": shift.tolist(), "lost": int((~ok[m]).sum())})
    return {"frames": len(t), "lost_rows": int(mt["lost_before"].sum()), "dropped": int(mt["dropped"].sum()),
            "noise_whole_run_nm": diff_noise(p), "holds": holds}


def report_noise(name, a):
    say(f"RESULT {name}: {a['frames']} frames, lost {a['lost_rows']}, dropped {a['dropped']}, whole-run noise x/y/z "
        + "/".join(f"{v:.1f}" for v in a["noise_whole_run_nm"]) + " nm")
    for h in a["holds"]:
        say(f"   {h['step']:<22} {h['frames']:4d} fr  noise " + "/".join(f"{v:5.1f}" for v in h["noise_nm"])
            + "  shift " + "/".join(f"{v:7.0f}" for v in h["shift_nm"]) + f"  lost {h['lost']}")


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": [], "focus_um": FOCUS_UM, "stage_um": STAGE_UM,
              "magnet_mm": MAGNET_MM}
    with events.as_caller("script:rig-motion-noise@1"):
        report["connect"] = T.connect()
        try:
            xy = check_picks()
            report["xy"] = xy.tolist()
            cal_path = os.path.join(OUT, "cal_motion")
            api.acq.start(record=False, name="zscan")
            try:
                zscan.run(cal_path, xy, slices=60, step_nm=100.0, n_avg=10, cross=120)
                say(f"RESULT z scan done; focus back at {api.focus.position():.3f} um")
            finally:
                api.acq.stop()
            ids = list(range(1, len(xy) + 1))
            api.beads.select(ids, cal_path=cal_path)
            roles = {i: "reference" for i in ids}
            for axis, steps in SEQUENCES:
                for ex, gpu in EXECUTORS:
                    report["runs"].append(T.one_run(f"motion_{axis}_{ex}", "current", gpu, 0, roles, during=steps))
                    T.dump(report, "report.json")
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
                say(f"RESULT disconnect clean in {time.monotonic() - t1:.1f} s; lock {api.rig.status()}")
            except Exception as e:  # noqa: BLE001
                report["disconnect_error"] = f"{type(e).__name__}: {e}"
                say(f"RESULT disconnect FAILED: {type(e).__name__}: {e}")
    report["error_events"] = [{"kind": e.kind, "extra": e.extra} for e in events.events()
                              if e.kind in ("device_error", "refused", "estop")]
    for e in report["error_events"]:
        say("EVENT", e["kind"], json.dumps(e["extra"], default=str)[:300])
    T.dump(report, "report.json")
    analyze_all()


def analyze_all():
    out = {}
    for axis, _ in SEQUENCES:
        for ex, _ in EXECUTORS:
            name = f"motion_{axis}_{ex}"
            path = os.path.join(OUT, name + ".h5")
            if os.path.exists(path):
                out[name] = analyze(path)
                report_noise(name, out[name])
    T.dump(out, "noise.json")


if __name__ == "__main__":
    analyze_all() if os.environ.get("ANALYZE") else main()
