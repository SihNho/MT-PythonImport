"""Rig 2026-10-31 (owner: dry channel with reference and magnetic beads in focus, EMCCD powered): track the same
reference bead repeatedly with every tracker (Z method x executor), step the focus piezo during tracking, and verify the
iXon open / close path. Everything through the program's API (it holds the rig lock itself, decision 0026).

Steps: connect MT-TIRF -> frame average -> isolated beads (V6 bead-map finder) -> z scan (.cal) -> repeated tracking runs
(record=True, HDF5) -> piezo step run -> disconnect. Motion: focus only (+-3 um scan, +-1 um steps; the magnet does not
move, the stage does not move). Output in OUT; RESULT lines on stdout; analysis offline (rig_refbead_analyze.py).
"""
import json
import os
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
sys.path.insert(0, r"G:\Codes\rig")
import riglock

from mtpy import api
from mtpy.api import events
from mtpy.gui import zscan

OUT = r"G:\l2s_rig_data\2026-10-31_refbead_track"
RUN_S = float(os.environ.get("RUN_S", "20"))                 # seconds per tracking run
REPEATS = int(os.environ.get("REPEATS", "3"))
METHODS = [(zm, gpu) for gpu in (False, True) for zm in ("current", "spline", "phase_spline")]
PIEZO_UM = [0.0, 0.5, 1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.0]   # within the +-3 um scan
HOLD_S = 3.0
N_BEADS = 4                                                  # the first is "the" reference bead; the others are controls


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def dump(obj, name):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)


def connect():
    t0 = time.monotonic()
    st = api.devices.connect({"backend": "real-motors", "mode": "MT-TIRF"})
    say(f"connect {time.monotonic() - t0:.1f} s:", {k: v["state"] for k, v in st.items()})
    for name, row in st.items():
        if row["state"] != "connected":
            say("RESULT", name, "NOT connected:", row.get("last_error"))
    rep = {"connect_s": time.monotonic() - t0, "states": {k: v["state"] for k, v in st.items()}}
    if st.get("emccd", {}).get("state") == "connected":
        info = api.devices.info("emccd")
        rep["emccd_found_at_open"] = info["identity"].get("found_at_open")
        rep["emccd_settings"] = api.emccd.settings()
        say("RESULT emccd found_at_open:", rep["emccd_found_at_open"])
        say("emccd now:", {k: rep["emccd_settings"].get(k) for k in ("sensor_temperature_C", "cooler", "temperature_C")})
    rep["camera"] = api.devices.info("camera")
    say("camera:", json.dumps(rep["camera"], default=str)[:300])
    return rep


# Hand-picked from frame.npy of the first attempt (23:24): the V6 bead-map finder expects a dark disk and found none
# of this dry channel's ring-shaped beads. Isolated single beads, far from the magnetic clusters, centres refined by
# the tracker's XY stage. Bead 1 is "the" reference bead; 2-4 are controls.
PICKS = [(760.4, 268.65), (984.43, 623.94), (373.37, 853.73), (372.42, 296.99)]


def find_beads():
    """Average 10 frames (saved), run the finder for the record, return the hand picks."""
    import refbead_record as R
    api.acq.start(record=False, name="find")
    try:
        img = api.acq.average(10, timeout_s=10)
        frame = np.clip(np.rint(img), 0, 255).astype(np.uint8)
        np.save(os.path.join(OUT, "frame.npy"), frame)
        beads, found = R.find_beads(frame)
    finally:
        api.acq.stop()
    say(f"finder (for the record): {len(found['beads'])} beads, {len(beads)} isolated; using {len(PICKS)} hand picks")
    for i, (x, y) in enumerate(PICKS):
        say(f"  bead {i + 1}: x {x:.2f} y {y:.2f}  local mean {frame[int(y) - 40:int(y) + 40, int(x) - 40:int(x) + 40].mean():.1f}")
    dump({"picked": PICKS, "finder": found["beads"]}, "beads.json")
    if not PICKS:
        raise RuntimeError("no beads picked")
    return np.array(PICKS, dtype=np.float64)


def calibrate(xy):
    cal_path = os.path.join(OUT, "cal_refbead")
    api.acq.start(record=False, name="zscan")
    try:
        t0 = time.monotonic()
        cal = zscan.run(cal_path, xy, slices=60, step_nm=100.0, n_avg=10, cross=120,
                        progress=lambda i, n: (i % 10 == 0) and say(f"  slice {i}/{n}"))
        say(f"RESULT z scan: {len(cal['xy'])} beads, 60 x 100 nm in {time.monotonic() - t0:.0f} s -> {cal_path}; "
            f"focus back at {api.focus.position():.3f} um")
    finally:
        api.acq.stop()
    return cal_path


def one_run(name, zm, gpu, seconds, roles, during=None):
    t0 = time.monotonic()
    try:
        api.acq.start(record=True, name=name, folder=OUT, roles=roles, z_method=zm, gpu=gpu)
    except Exception as e:  # noqa: BLE001 - a refused combination is a result
        say(f"RESULT run {name} ({zm}, gpu={gpu}) could not start: {type(e).__name__}: {e}")
        return {"name": name, "z_method": zm, "gpu": gpu, "error": f"{type(e).__name__}: {e}"}
    try:
        if during:
            during()
        else:
            time.sleep(seconds)
        st = api.acq.status()
        api.acq.stop()
    except Exception as e:  # noqa: BLE001
        say(f"RESULT run {name} failed mid-run: {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            api.acq.stop()
        except Exception as e2:  # noqa: BLE001
            say("  stop also failed:", e2)
        return {"name": name, "z_method": zm, "gpu": gpu, "error": f"{type(e).__name__}: {e}"}
    keep = ("frames_received", "frames_tracked", "fps_measured", "camera_gaps", "pipeline_drops", "track_ms_p50",
            "track_ms_p99", "latency_ms_p50", "latency_ms_p99", "tracking_errors", "sink_failures", "frames_not_written")
    row = {"name": name, "z_method": zm, "gpu": gpu, "wall_s": time.monotonic() - t0, **{k: st.get(k) for k in keep}}
    say(f"RESULT run {name} ({zm}, gpu={gpu}): {row['frames_tracked']} tracked, fps {row['fps_measured']}, gaps "
        f"{row['camera_gaps']}, drops {row['pipeline_drops']}, track ms p50/p99 {row['track_ms_p50']}/{row['track_ms_p99']}, "
        f"errors {row['tracking_errors']}")
    return row


def piezo_steps():
    z0 = api.focus.position()
    try:
        for dz in PIEZO_UM:
            got = api.focus.move_to(z0 + dz).wait(10)
            api.acq.mark(f"piezo {dz:+.2f} um (read back {got})")
            time.sleep(HOLD_S)
    finally:
        api.focus.move_to(z0).wait(10)
        api.acq.mark("piezo back to start")


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "riglock_before": riglock.status(), "runs": []}
    say("riglock before:", json.dumps(report["riglock_before"], default=str)[:160])
    with events.as_caller("script:rig-refbead-track@1"):
        report["connect"] = connect()
        try:
            xy = find_beads()
            cal_path = calibrate(xy)
            ids = list(range(1, len(xy) + 1))
            pos = api.beads.select(ids, cal_path=cal_path)
            say("selected:", pos)
            roles = {i: "reference" for i in ids}
            for zm, gpu in METHODS:
                for r in range(REPEATS):
                    report["runs"].append(one_run(f"{zm}_{'gpu' if gpu else 'numba'}_{r + 1}", zm, gpu, RUN_S, roles))
                    dump(report, "report.json")
            report["runs"].append(one_run("piezo_current_numba", "current", False, 0, roles, during=piezo_steps))
            report["piezo_um"] = PIEZO_UM
        except Exception as e:  # noqa: BLE001
            say(f"RESULT session FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
            report["error"] = f"{type(e).__name__}: {e}"
        finally:
            if api.acq.running():
                api.acq.stop()
            t1 = time.monotonic()
            try:
                if "emccd" in api.devices.status():
                    s = api.emccd.settings()
                    report["emccd_before_close"] = {k: s.get(k) for k in ("sensor_temperature_C", "cooler", "temperature_C")}
                api.devices.disconnect()
                report["disconnect_s"] = time.monotonic() - t1
                say(f"RESULT disconnect clean in {report['disconnect_s']:.1f} s")
            except Exception as e:  # noqa: BLE001
                report["disconnect_error"] = f"{type(e).__name__}: {e}"
                say(f"RESULT disconnect FAILED after {time.monotonic() - t1:.1f} s: {type(e).__name__}: {e}")
    report["riglock_after"] = riglock.status()
    say("riglock after:", json.dumps(report["riglock_after"], default=str)[:160])
    report["error_events"] = []
    for e in events.events():
        if e.kind in ("device_error", "refused", "estop") or "error" in json.dumps(e.extra, default=str).lower():
            report["error_events"].append({"kind": e.kind, "caller": e.caller, "extra": e.extra})
            say("EVENT", e.kind, json.dumps(e.extra, default=str)[:300])
    dump(report, "report.json")
    say("devices left:", api.devices.status())


if __name__ == "__main__":
    main()
