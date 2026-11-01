"""Rig 2026-11-01 (owner: "run the isolation measurement"): why the tracker's tail grows under the GUI. The real
MainWindow (backend real-motors), the owner's beads (cal_4 / cal_256 of the bead-count bench), 10 s recorded runs
under five GUI conditions: normal | display off (no image / boxes; plot on) | no plot | no event log | timers off (GUI
idle). The GUI tick itself is timed. Output in OUT: runs/*.h5, isolate.json; a table on stdout.
STEPS=1 (owner 2026-11-01, accuracy bench): the run steps the piezo and the magnet (rig_accuracy.steps) instead of
standing still and the row carries rig_accuracy.accuracy of the first four beads; FPS=90,150 repeats the cases per
camera rate through the GUI's own preset box.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\rig")
import rig_accuracy as A
import rig_motion_noise as M
import riglock

from mtpy import api  # noqa: F401 - rebound to the engine client in CLIENT mode (main)
from mtpy.lvfiles import read_cal

CLIENT = bool(os.environ.get("CLIENT"))          # decision 0029 step 3: the window as a client of an engine process

OUT = Path(os.environ.get("OUT", r"G:\l2s_rig_data\2026-11-01_gui_isolate"))
COUNT_CALS = Path(os.environ.get("COUNT_CALS", r"G:\l2s_rig_data\2026-11-01_bead_count"))
RUN_S = float(os.environ.get("RUN_S", "10"))
def _case(c):
    n, ex, *zm = c.split(":")
    return int(n), ex == "gpu", (zm[0] if zm else "current")


CASES = [_case(c) for c in os.environ.get("CASES", "4:numba,256:numba,256:gpu").split(",")]   # n:exec[:z_method]
CONDITIONS = tuple(os.environ.get("CONDITIONS", "normal,display_off,no_plot,no_log,timers_off").split(","))
STEPS = bool(os.environ.get("STEPS"))
FPS = [f if f == "max" else float(f) for f in os.environ["FPS"].split(",")] if os.environ.get("FPS") else [None]
ROI = tuple(int(v) for v in os.environ["ROI"].split(",")) if os.environ.get("ROI") else None   # x,y,w,h (no GUI control)
NB = len(A.PICK_IDS)                             # distinct beads at the front of the cals (3 in the half-ROI bench)
MAKE_CAL = bool(os.environ.get("MAKE_CAL"))      # a fresh LUT per frame rate here (the beads drift ~15 px/h)
R = {"runs": []}


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    from PySide6.QtWidgets import QApplication

    from mtpy.gui import app as gui_app
    from mtpy.gui.app import MainWindow
    from mtpy.gui.shutdown import ShutdownDialog
    global api
    client = proc = None
    if CLIENT:
        from mtpy.client import launch
        client, proc = launch()
        gui_app.use_client(client)
        api = client.api
        A.api = M.api = api
        A.zscan = api.zscan
        say("engine:", client.call("engine.info"))
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv[:1])
    w = MainWindow(fixture=r"G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch\test",
                   out=str(OUT / "runs"), backend="real-motors")
    w.resize(1500, 950)
    w.show()
    tick_ms = []
    orig_tick, orig_plot, orig_on_event = w._tick, w._update_plot, w._on_event

    def timed_tick():
        t0 = time.perf_counter()
        orig_tick()
        tick_ms.append((time.perf_counter() - t0) * 1e3)
    w._tick = timed_tick
    w.timer.timeout.disconnect()
    w.timer.timeout.connect(w._tick)

    def pump(s):
        t = time.monotonic() + s
        while time.monotonic() < t:
            app.processEvents()
            time.sleep(0.005)

    def until(cond, timeout, what):
        t = time.monotonic() + timeout
        while time.monotonic() < t:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.03)
        say("TIMEOUT", what, w.statusBar().currentMessage())
        return False

    def acq_start(name, gpu):
        w.gpu.setChecked(gpu)
        w.ed_name.setText(name)
        w._toggle_acq()
        return until(lambda: w.btn_live.text() == "Stop acquisition" and api.acq.running(), 60, f"start {name}")

    def acq_stop():
        st = api.acq.status()
        w._toggle_acq()
        until(lambda: not api.acq.running() and w.btn_live.text() == "Start acquisition", 60, "stop acquisition")
        return st

    def rec(on):
        w.btn_rec.setChecked(on)
        w._toggle_rec()
        return until(lambda: api.acq.status().get("recording") == on, 30, f"recording {on}")

    def select_from_cal(path, n):
        w.ed_cal.setText(str(path))
        w._load_cal_list()
        w.role_ref.setText(",".join(str(i) for i in range(1, n + 1)))
        w.bead_ids = []
        w._select_beads()
        return until(lambda: bool(w.bead_ids), 30, "select beads")

    def set_rate(fps):
        if fps == "max":
            fps = float(api.devices.info("camera")["limits"]["rate_Hz"][1])
        if w.cam_rate.findData(fps) >= 0 and ROI is None:          # the GUI's own preset box (ROI fixed at full frame)
            w.cam_rate.setCurrentIndex(w.cam_rate.findData(fps))
            w.cam_exp.setValue(api.devices.info("camera")["settings"]["exposure_ms"])   # keep the exposure the LUT saw
            w._apply_preset()
            until(lambda: not w._workers, 60, f"camera preset {fps}")
        else:                                   # shortcut: the GUI offers 90 / 150 Hz and no ROI, so the API sets these
            api.camera.set_rate(fps, confirm=True)
        got = api.devices.info("camera")["settings"]["rate_Hz"]
        say(f"camera rate {fps} -> {got}")
        if abs(got - fps) > 1:
            raise RuntimeError(f"camera rate {fps} not taken: {got}")
        return fps

    def set_condition(c):
        w.display_on = c != "display_off"
        w._update_plot = (lambda: None) if c == "no_plot" else orig_plot
        w._on_event = (lambda ev: None) if c == "no_log" else orig_on_event
        if c == "timers_off":
            w.timer.stop()
            w.slow.stop()
        else:
            if not w.timer.isActive():
                w.timer.start()
            if not w.slow.isActive():
                w.slow.start()

    pump(1.0)
    try:
        w.ed_out.setText(str(OUT / "runs"))
        w._connect()
        until(lambda: "/ 8" in w.dev_summary.text() and not w._workers, 120, "connect")
        say("connected:", w.dev_summary.text())
        M.SLEEP = pump
        roi0 = tuple(api.devices.info("camera")["settings"]["roi"])
        if ROI:
            say("camera ROI:", api.camera.set_roi(*ROI, confirm=True))
        for fps in FPS:
          if fps is not None:
            fps = set_rate(fps)
          if MAKE_CAL:
            A.OUT = str(OUT)
            cal_src = OUT / f"cal_acc_{fps:.0f}"
            A.make_cal(str(cal_src))
            base = read_cal(str(cal_src))
            for n in sorted({c[0] for c in CASES}):
                A.tiled_cal(base, n, str(OUT / f"cal_{fps:.0f}_{n}"))
            cals = OUT
          else:
            cals = COUNT_CALS
          for n, gpu, zm in CASES:
            if not select_from_cal(cals / (f"cal_{n}" if fps is None else f"cal_{fps:.0f}_{n}"), n):
                raise RuntimeError(f"selection of {n} beads failed")
            w.z_method.setCurrentText(zm)
            for c in CONDITIONS:
                name = f"iso_{'' if fps is None else f'{fps:.0f}_'}{n}_{zm}_{'gpu' if gpu else 'numba'}_{c}"
                set_condition(c)
                tick_ms.clear()
                if not acq_start(name, gpu):
                    raise RuntimeError(f"{name}: no start")
                pump(0.5)
                rec(True)
                if STEPS:
                    A.steps()
                else:
                    pump(RUN_S)
                rec(False)
                st = acq_stop()
                set_condition("normal")
                ticks = sorted(tick_ms)
                row = {"fps": fps, "beads": n, "gpu": gpu, "z_method": zm, "condition": c, "frames": st.get("frames_tracked"),
                       "gaps": st.get("camera_gaps"),
                       "drops": st.get("pipeline_drops"), "track_p50": st.get("track_ms_p50"), "track_p99": st.get("track_ms_p99"),
                       "track_std": st.get("track_ms_std"), "track_max": st.get("track_ms_max"),
                       "latency_p99": st.get("latency_ms_p99"), "display_updates": st.get("display_updates"),
                       "ticks": len(ticks), "tick_ms_p50": ticks[len(ticks) // 2] if ticks else None,
                       "tick_ms_max": ticks[-1] if ticks else None}
                if STEPS and row["frames"]:
                    row["accuracy"] = A.accuracy(str(OUT / "runs" / f"{name}.h5"), min(NB, n))
                    say("   accuracy:", A.fmt(row["accuracy"]))
                R["runs"].append(row)
                say(f"RESULT {name}: frames {row['frames']}, drops {row['drops']}, track {row['track_p50']:.2f}/{row['track_p99']:.2f} ms, "
                    f"latency p99 {row['latency_p99']:.2f}, ticks {row['ticks']} ({row['tick_ms_p50'] or 0:.1f}/{row['tick_ms_max'] or 0:.1f} ms)")
    except Exception as e:  # noqa: BLE001
        say(f"FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        if api.acq.running():
            acq_stop()
    set_condition("normal")
    if FPS[0] is not None:
        set_rate(90.0)                                   # initial condition
    if ROI:
        say("camera ROI back:", api.camera.set_roi(*roi0, confirm=True))
    d = ShutdownDialog(w)
    d.show()
    until(lambda: d.ok or d.buttons.isEnabled(), 600, "shutdown")
    say("shutdown ok:", d.ok, "lock:", riglock.status().get("holder"))
    d.close()
    w.close()
    if client is not None:
        client.exit_engine()
        proc.wait(120)
        say("engine exited", proc.returncode)
    with open(OUT / "isolate.json", "w", encoding="utf-8") as f:
        json.dump(R, f, indent=1, default=str)
    say("fps  beads z method      exec  condition    frames gaps drops  track ms median/std/p99/max   lat p99   GUI tick p50/max ms (n)"
        + ("   focus raw  focus ref  stage raw  stage ref  magnet raw magnet ref noise lost  follow  over" if STEPS else ""))
    for r in R["runs"]:
        say(f"{r['fps'] or 0:4.0f} {r['beads']:4d}  {r.get('z_method', 'current'):12s} {'gpu' if r['gpu'] else 'numba':5s} {r['condition']:11s} {r['frames']:6d} {r['gaps'] or 0:4d} {r['drops']:5d}  "
            f"{r['track_p50']:5.2f}/{r['track_std'] or 0:5.2f}/{r['track_p99']:6.2f}/{r['track_max'] or 0:6.2f}   "
            f"{r['latency_p99']:6.2f}   "
            f"{r['tick_ms_p50'] or 0:5.1f}/{r['tick_ms_max'] or 0:6.1f} ({r['ticks']})"
            + ("   " + A.fmt(r["accuracy"]) if "accuracy" in r else ""))


if __name__ == "__main__":
    main()
