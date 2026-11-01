"""Rig 2026-11-01 (owner: "in the end it has to be measured in the app's GUI; GUI control allowed - run the same bench
through the GUI"): the motion-noise bench and the bead-count bench driven through the real MainWindow (backend
real-motors): its Connect, its picks, its Calibrate panel (z scan), its bead list, its Start acquisition / Record,
its GPU box, and its shutdown dialog. The GUI thread is pumped (processEvents) throughout, so the display tap, the
plot and the status bar run as for an operator. Motions and marks go through the API, as the GUI's own buttons do.
Output in OUT: runs/*.h5, cal_gui, screenshots, gui_bench.json; the analysis is rig_motion_noise.analyze.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
sys.path.insert(0, r"G:\Codes\rig")
import riglock
from rig_motion_noise import FOCUS_UM, MAGNET_MM, STAGE_UM, analyze, report_noise
from rig_refbead_track import ms4

from mtpy import api  # noqa: F401 - rebound to the engine client in CLIENT mode (main)

CLIENT = bool(os.environ.get("CLIENT"))          # decision 0029 step 3: the window as a client of an engine process
from mtpy.gui import zscan

OUT = Path(os.environ.get("OUT", r"G:\l2s_rig_data\2026-11-01_gui_bench"))
COUNT_CALS = Path(os.environ.get("COUNT_CALS", r"G:\l2s_rig_data\2026-11-01_bead_count"))
PICKS = [(1074.53, 570.25), (679.78, 701.47), (564.26, 790.12), (429.96, 474.93)]   # owner's beads, 15:15 positions
HOLD_S = 3.0
R = {"steps": [], "runs": {}}


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def note(name, **kw):
    kw["t"] = time.strftime("%H:%M:%S")
    R["steps"].append({"step": name, **kw})
    say("STEP", name, json.dumps(kw, default=str)[:400])


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
        say("engine:", client.call("engine.info"))
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv[:1])
    w = MainWindow(fixture=r"G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch\test",
                   out=str(OUT / "runs"), backend="real-motors")
    w.resize(1500, 950)
    w.show()

    def pump(s):
        t = time.monotonic() + s
        while time.monotonic() < t:
            app.processEvents()
            time.sleep(0.01)

    def until(cond, timeout, what):
        t = time.monotonic() + timeout
        while time.monotonic() < t:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.03)
        note(f"TIMEOUT {what}", status=w.statusBar().currentMessage())
        return False

    def shot(name):
        pump(0.3)
        w.grab().save(str(OUT / f"{name}.png"))

    def lock():
        st = riglock.status()
        h = st.get("holder")
        return {"holder": h and {k: h[k] for k in ("name", "pid")}, "state": st["rig_state"]["value"]}

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

    def focus_steps():
        z0 = api.focus.position()
        try:
            for dz in FOCUS_UM:
                got = api.focus.move_to(z0 + dz).wait(10)
                api.acq.mark(f"focus {dz:+.2f} um (read back {got})")
                pump(HOLD_S)
        finally:
            api.focus.move_to(z0).wait(10)
            api.acq.mark("focus back to start")

    def stage_steps():
        x0, y0 = api.stage.position()
        try:
            for dx, dy in STAGE_UM:
                got = api.stage.move_to(x0 + dx / 1000.0, y0 + dy / 1000.0).wait(10)
                api.acq.mark(f"stage {dx:+d} {dy:+d} um (read back {got})")
                pump(HOLD_S)
        finally:
            api.stage.move_to(x0, y0).wait(10)
            api.acq.mark("stage back to start")

    def magnet_steps():
        try:
            for p in MAGNET_MM:
                got = api.magnet.move_to(p).wait(30)
                api.acq.mark(f"magnet {p:+.1f} mm (read back {got})")
                pump(HOLD_S)
        finally:
            api.magnet.move_to(0.0).wait(30)
            api.acq.mark("magnet back to start")

    def select_from_cal(path, refs):
        w.ed_cal.setText(str(path))
        w._load_cal_list()
        w.role_ref.setText(refs)
        w.bead_ids = []
        w._select_beads()
        return until(lambda: bool(w.bead_ids), 30, "select beads")

    pump(1.0)
    note("start", lock=lock())
    shot("00_start")
    try:
        w.ed_out.setText(str(OUT / "runs"))
        w._connect()
        ok = until(lambda: "/ 8" in w.dev_summary.text() and not w._workers, 120, "connect")
        st = api.devices.status()
        note("connect", ok=ok, summary=w.dev_summary.text(), lock=lock(),
             devices={n: d["state"] for n, d in st.items()})
        shot("01_connected")
        # --- picks on the live image, then the Calibrate panel's z scan
        acq_start("gui_check", False)
        img = api.acq.average(10, timeout_s=10)
        xy = []
        for x, y in PICKS:
            xo, yo, _ = zscan.bead_profile(img, x, y, 120)
            xy.append((float(xo), float(yo)))
        w.picks = list(xy)
        w._draw_picks()
        note("picks", xy=[(round(x, 1), round(y, 1)) for x, y in xy])
        w.cal_out.setText(str(OUT / "cal_gui"))
        w.cal_avg.setValue(10)
        w.cal_settle.setValue(zscan.SETTLE_S)
        t0 = time.monotonic()
        w._run_zscan()
        ok = until(lambda: w.cal_status.text().startswith("done") or w.cal_status.text().startswith("FAILED"), 120, "z scan")
        note("zscan", ok=ok, status=w.cal_status.text()[:200], seconds=round(time.monotonic() - t0, 1))
        shot("02_zscan")
        acq_stop()
        if not select_from_cal(OUT / "cal_gui", "1,2,3,4"):
            raise RuntimeError("bead selection failed")
        note("beads", ids=w.bead_ids, info=w.beads_info.text()[:200])
        # --- motion bench through the GUI
        for axis, steps in (("focus", focus_steps), ("stage", stage_steps), ("magnet", magnet_steps)):
            for ex, gpu in (("numba", False), ("gpu", True)):
                name = f"gui_motion_{axis}_{ex}"
                if not acq_start(name, gpu):
                    raise RuntimeError(f"{name}: acquisition did not start")
                pump(1.0)
                rec(True)
                t0 = time.monotonic()
                steps()
                rec(False)
                st = acq_stop()
                keep = ("frames_received", "frames_tracked", "fps_measured", "camera_gaps", "pipeline_drops",
                        "track_ms_p50", "track_ms_std", "track_ms_p99", "track_ms_max", "latency_ms_p50",
                        "latency_ms_std", "latency_ms_p99", "latency_ms_max", "display_updates")
                R["runs"][name] = {k: st.get(k) for k in keep}
                R["runs"][name]["wall_s"] = time.monotonic() - t0
                say(f"RESULT {name}: {st.get('frames_tracked')} tracked, gaps {st.get('camera_gaps')}, drops "
                    f"{st.get('pipeline_drops')}, track ms median/std/p99/max {ms4(st)}, "
                    f"display updates {st.get('display_updates')}")
                if axis == "stage" and ex == "numba":
                    shot("03_stage_run")
        # --- bead count through the GUI (the cal files of the bead-count bench)
        for n in (4, 64, 256):
            if not select_from_cal(COUNT_CALS / f"cal_{n}", ",".join(str(i) for i in range(1, n + 1))):
                raise RuntimeError(f"selection of {n} beads failed")
            for ex, gpu in (("numba", False), ("gpu", True)):
                name = f"gui_count_{n}_{ex}"
                acq_start(name, gpu)
                rec(True)
                pump(10.0)
                rec(False)
                st = acq_stop()
                R["runs"][name] = {k: st.get(k) for k in ("frames_tracked", "fps_measured", "camera_gaps", "pipeline_drops",
                                                          "track_ms_p50", "track_ms_p99", "latency_ms_p50", "latency_ms_p99",
                                                          "display_updates")}
                say(f"RESULT {name}: {st.get('frames_tracked')} tracked, drops {st.get('pipeline_drops')}, track ms "
                    f"median/std/p99/max {ms4(st)}, display updates {st.get('display_updates')}")
                if n == 256 and ex == "numba":
                    shot("04_256_beads")
    except Exception as e:  # noqa: BLE001
        note("FAILED", error=f"{type(e).__name__}: {e}", status=w.statusBar().currentMessage())
        traceback.print_exc()
        if api.acq.running():
            acq_stop()
    # --- the shutdown dialog, as the operator's Disconnect
    d = ShutdownDialog(w)
    d.show()
    t0 = time.monotonic()
    until(lambda: d.ok or d.buttons.isEnabled(), 600, "shutdown")
    d.grab().save(str(OUT / "05_shutdown.png"))
    note("shutdown", ok=d.ok, seconds=round(time.monotonic() - t0, 1), lock=lock(), devices=api.devices.status())
    d.close()
    w.close()
    if client is not None:
        client.exit_engine()
        proc.wait(120)
        say("engine exited", proc.returncode)
    with open(OUT / "gui_bench.json", "w", encoding="utf-8") as f:
        json.dump(R, f, indent=1, default=str)
    for name in sorted(R["runs"]):
        p = OUT / "runs" / f"{name}.h5"
        if "motion" in name and p.exists():
            report_noise(name, analyze(str(p)))
    print("RESULT", json.dumps({"shutdown_ok": d.ok, "lock": lock()}, default=str), flush=True)


if __name__ == "__main__":
    main()
