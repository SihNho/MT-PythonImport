"""The window as a client of an engine process (decision 0029, step 2): Connect, acquisition with the display read
from shared memory, picks + the z scan run in the engine, beads from the written .cal, recording, Disconnect through
the shutdown sequence - the GUI never imports a device. Offscreen Qt; the engine on the simulator."""
import os
import time

import pytest
from conftest import FIXTURE, need
from test_engine import engine  # noqa: F401 - the launched engine fixture

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _until(app, cond, timeout_s, what):
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError(f"timeout: {what}")


def test_window_runs_the_flow_as_a_client_of_the_engine(engine, tmp_path, monkeypatch):  # noqa: F811
    need(FIXTURE / "cal002")
    from PySide6.QtWidgets import QApplication

    from mtpy.gui import app as gui_app
    client, _proc = engine
    gui_app.use_client(client)
    try:
        app = QApplication.instance() or QApplication([])
        w = gui_app.MainWindow(fixture=str(FIXTURE), out=str(tmp_path / "runs"))
        fails = []
        orig_fail = w._fail
        w._fail = lambda what, msg: (fails.append((what, msg)), orig_fail(what, msg))
        w.show()
        w._connect()
        def connected():
            st = client.api.devices.status()
            return bool(st) and all(d["state"] == "connected" for d in st.values()) and not w._workers
        _until(app, connected, 60, "connect through the client")
        assert "8 / 8" in w.dev_summary.text() and client.events.history() != []      # MT-TIRF: eight simulators
        # acquisition: the display comes from the shared-memory snapshot, the plot history grows
        w._toggle_acq()
        _until(app, lambda: w.btn_live.text() == "Stop acquisition", 20, "acquisition started")
        _until(app, lambda: str(w.cam_label.text).startswith("JAI frame"), 20, "a frame shown from the snapshot")   # pg.LabelItem
        # picks on the image, then the z scan in the engine (progress polled), beads from the written .cal
        w.picks = [(708.0, 301.0)]                       # bead 1 of the fixture's cal002
        w.cal_out.setText(str(tmp_path / "runs" / "cal_client"))
        w.cal_slices.setValue(9)                         # the 5-point z fit needs at least 5 slices
        w.cal_avg.setValue(1)
        w.cal_settle.setValue(0.0)
        w._run_zscan()
        _until(app, lambda: w.cal_status.text().startswith(("done", "FAILED")), 60, "z scan")
        assert w.cal_status.text().startswith("done: 1 beads"), w.cal_status.text()
        w._toggle_acq()
        _until(app, lambda: w.btn_live.text() == "Start acquisition", 20, "acquisition stopped")
        w._load_cal_list()
        w.role_ref.setText("1")
        w._select_beads()
        _until(app, lambda: w.bead_ids == [1], 20, "bead selected")
        w._toggle_acq()
        _until(app, lambda: w.btn_live.text() == "Stop acquisition" or fails, 90, "acquisition with the bead")
        assert not fails, fails
        w.btn_rec.setChecked(True)
        w._toggle_rec()
        _until(app, lambda: client.api.acq.status().get("recording"), 20, "recording on")
        _until(app, lambda: len(w.history) > 5, 20, "tracked results reach the plot history")
        w.btn_rec.setChecked(False)
        w._toggle_rec()
        w._toggle_acq()
        _until(app, lambda: w.btn_live.text() == "Start acquisition", 20, "stopped")
        # Disconnect = the shutdown sequence through the client; the engine releases everything
        w._disconnect()
        _until(app, lambda: not client.api.devices.status(), 60, "shutdown through the client")
        assert w.dev_summary.text() == "Devices: not connected"
        w.close()
        app.processEvents()
    finally:
        gui_app.use_inprocess()
