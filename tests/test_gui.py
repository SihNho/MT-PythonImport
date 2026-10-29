"""Phase 8 first build: the window drives the whole simulated flow through the public API (connect, camera preset,
beads from the fixture .cal, acquisition with the display tap, a protocol, recording, stop). Offscreen Qt; skipped
without PySide6 or the G: fixture."""
import os
import shutil
import time

import pytest
from conftest import FIXTURE, need

from mtpy import api
from mtpy.api import estop, events, safety

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROTOCOL = 'grammar 0.1\nprotocol "gui-test"\nhold f=1 t=0.3\nmove mm=2 t=0.2\nmark "m"\nend protocol\n'


def _pump(app, seconds):
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        app.processEvents()
        time.sleep(0.01)


def _until(app, cond, timeout_s, what):
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError(f"timeout: {what}")


@pytest.fixture
def window(tmp_path, monkeypatch):
    need(FIXTURE / "cal002")
    from PySide6.QtWidgets import QApplication

    from mtpy.gui.__main__ import sim_dev_config
    from mtpy.gui.app import MainWindow
    saved = (safety.CONFIG, safety._active, api.beads._selected)
    monkeypatch.setattr(api.protocol, "_engine", None)
    cfg = sim_dev_config()
    app = QApplication.instance() or QApplication([])
    w = MainWindow(fixture=str(FIXTURE), out=str(tmp_path / "runs"), sim_dev=cfg)
    w.show()
    yield app, w
    w.close()
    _pump(app, 0.2)
    with events.as_caller("gui"):
        estop.clear()
    safety.CONFIG, safety._active, api.beads._selected = saved
    shutil.rmtree(cfg.parent, ignore_errors=True)


def test_gui_flow_on_simulators(window):
    app, w = window
    w._connect()
    _until(app, lambda: "7 / 7" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w._call(lambda: api.magnet.set_touch_position(40.0), "touch")
    _until(app, lambda: api.magnet.force_calibration()["ready"], 10, "touch position")
    w._load_cal_list()
    assert w.bead_list.count() >= 5
    w._select_beads()
    _until(app, lambda: w.bead_ids, 10, "beads selected")
    w._toggle_acq()
    _until(app, lambda: api.acq.running() and len(w.history) > 20, 30, "acquisition + display history")
    w.btn_rec.setChecked(True)
    w._toggle_rec()
    w.prot_edit.setPlainText(PROTOCOL)
    w._run_protocol()
    _until(app, lambda: api.protocol.status()["state"] == "completed", 30, "protocol completed")
    _until(app, lambda: "completed" in w.prot_status.text(), 5, "protocol label (2 Hz status tick)")
    w.btn_rec.setChecked(False)
    w._toggle_rec()
    w._toggle_acq()
    _until(app, lambda: not api.acq.running(), 15, "acquisition stopped")
    st = api.acq.status()
    assert st["frames_tracked"] > 20 and st["pipeline_drops"] == 0
    assert w.bead_ids == [1, 2, 3, 4, 5] and w.roles[1] == "reference"
    kinds = [w.events_list.item(i).text().split("  ")[1] for i in range(w.events_list.count())]
    assert "motor_reading" not in kinds and "mark" in kinds and "recording" in kinds
