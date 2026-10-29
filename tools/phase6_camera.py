r"""phase6_camera.py - phase 6 measurement: the real JAI camera at 150 Hz with the GUI running (docs/plan.md phase 6).

  RIG, inside V6 tools/rig_session.py --no-motor-session (it holds the rig lock, polls `permitted`, kills on refusal):
  py tools/rig_session.py --purpose "LabVIEW2Scr phase 6" --no-motor-session --max-min 15 -- \
      G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -u G:\Codes\LabVIEW2Scr\tools\phase6_camera.py --out <dir> --minutes 5

Shows the GUI (backend real), connects, applies the 150 Hz preset (read back), records to `<out>/<name>.h5`, drags the
window by real mouse input three times during the run (the Windows modal move loop blocks the UI thread - the case
where LabVIEW loses frames, decision 0008), stops, disconnects (camera closed) and writes `<out>/<name>.summary.json`:
frames received, camera gaps (total and during the drags), pipeline drops, the frame-rate triple from the run file.
Nothing moves; the simulated motors are not touched.
"""
import argparse
import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


def drag_window(w, dx=300, seconds=3.0):
    """Press on the title bar and move the cursor for `seconds` (real input: the UI thread enters the move loop)."""
    u = ctypes.windll.user32
    g = w.frameGeometry()
    x, y = g.x() + g.width() // 2, g.y() + 12
    u.SetCursorPos(x, y)
    u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    n, t0 = 60, time.perf_counter()
    for i in range(1, n + 1):
        u.SetCursorPos(x + round(dx * i / n), y)
        time.sleep(seconds / n)
    u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return time.perf_counter() - t0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--rate", type=float, default=150.0)
    ap.add_argument("--exposure-ms", type=float, default=1.909)
    ap.add_argument("--drags", type=int, default=3)
    ap.add_argument("--backend", default="real", help="sim = a dry run of this script on the simulators")
    a = ap.parse_args(argv)
    from PySide6.QtWidgets import QApplication

    from mtpy import api
    from mtpy.api import estop, events
    from mtpy.gui.app import MainWindow
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = time.strftime("phase6_%Y%m%d_%H%M%S")
    app = QApplication(sys.argv[:1])
    w = MainWindow(fixture=str(out), out=str(out), backend=a.backend)
    w.show()
    result = {"name": name, "rate_Hz": a.rate, "exposure_ms": a.exposure_ms, "minutes": a.minutes, "drags": []}

    def job():
        try:
            with events.as_caller("gui"):
                estop.clear()
                st = api.devices.connect({"backend": a.backend})
                result["devices"] = st
                if st["camera"]["state"] != "connected":
                    raise RuntimeError(f"camera not connected: {st['camera']['last_error']}")
                result["identity"] = api.devices.info("camera")["identity"]
                result["preset_readback"] = api.camera.apply_preset(
                    {"name": f"tracking {a.rate:g} Hz", "rate_Hz": a.rate, "exposure_ms": a.exposure_ms})
                api.acq.start(record=True, name=name, folder=out)
                t_end = time.time() + a.minutes * 60.0
                gap_s = a.minutes * 60.0 / (a.drags + 1)
                for k in range(a.drags):
                    time.sleep(gap_s)
                    before = api.acq.status()
                    api.acq.mark(f"drag {k + 1} start")
                    dur = drag_window(w)
                    api.acq.mark(f"drag {k + 1} end")
                    time.sleep(0.5)
                    after = api.acq.status()
                    result["drags"].append({"seconds": dur, "gaps_during": after["camera_gaps"] - before["camera_gaps"],
                                            "frames_during": after["frames_received"] - before["frames_received"]})
                time.sleep(max(0.0, t_end - time.time()))
                result["status"] = api.acq.stop()
        except Exception as e:  # noqa: BLE001 - recorded in the summary; cleanup below
            result["error"] = f"{type(e).__name__}: {e}"
        finally:
            try:
                if api.acq.running():
                    api.acq.stop()
                api.devices.disconnect()
                result["cleanup"] = {"devices_after": api.devices.status(), "camera_closed": True}
            except Exception as e:  # noqa: BLE001
                result["cleanup"] = {"error": f"{type(e).__name__}: {e}", "camera_closed": False}
            try:
                import h5py
                with h5py.File(out / f"{name}.h5", "r") as f:
                    result["frame_rate_hz"] = f["metadata/run/frame_rate_hz"][()].tolist()
                    result["t_camera_source"] = str(f["mt/t_camera"].attrs.get("source"))
                    result["rows"] = int(f["mt/buffer_number"].shape[0])
            except Exception as e:  # noqa: BLE001
                result["run_file"] = f"not read: {type(e).__name__}: {e}"
            (out / f"{name}.summary.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
            print("SUMMARY " + json.dumps({k: result.get(k) for k in ("error", "frame_rate_hz", "rows", "drags", "cleanup")},
                                          default=str), flush=True)
            # app.quit() from this thread did not end the loop on the rig (2026-10-29 run 2 hung until the wrapper's
            # time limit); the summary is written, the camera closed, so end the process here
            os._exit(1 if result.get("error") else 0)

    threading.Thread(target=job, daemon=True).start()
    app.exec()


if __name__ == "__main__":
    sys.exit(main())
