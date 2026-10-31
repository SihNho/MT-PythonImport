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
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
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


def test_gui_emccd_group_on_simulators(window):
    """The EMCCD group (owner 2026-10-30): apply the five parameters with read-back, snap into the image view,
    shutter open / close, and the shutter exercise, all through api.emccd on the simulated iXon."""
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w.em_rate.setValue(18.0)
    w._apply_emccd()
    _until(app, lambda: "emccd read back" in w.em_readback.text(), 10, "emccd preset")
    assert "'rate_Hz': 17.99" in w.em_readback.text() and "'temperature_C': -70" in w.em_readback.text()
    w._snap_emccd()
    _until(app, lambda: "emccd frame 512 x 512" in w.em_readback.text(), 10, "emccd snap")
    w._shutter(2)
    _until(app, lambda: w.em_readback.text() == "emccd shutter: closed", 10, "shutter closed")
    w._shutter(1)
    _until(app, lambda: w.em_readback.text() == "emccd shutter: open", 10, "shutter open")
    w.em_cycles.setValue(3)
    w.em_pause.setValue(0.0)
    w._exercise_emccd()
    _until(app, lambda: "6 of 6 calls ok" in w.em_readback.text(), 10, "shutter exercise")
    assert api.emccd.settings()["shutter"] == 2
    w._disconnect()
    _until(app, lambda: "not connected" in w.dev_summary.text(), 20, "disconnect")


def test_gui_pick_flow_on_simulators(window, tmp_path):
    """Owner 2026-10-30: pick beads on the image, calibrate them, select, track. Also the sim-only oddity seen once
    on 2026-10-30 (tracking stopped by itself after ~79 frames): tracking must still run and advance after 3 s."""
    from mtpy.lvfiles import read_cal
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._toggle_acq()
    _until(app, lambda: api.acq.running() and "JAI frame" in w.cam_label.text, 20, "display-only acquisition")
    for x, y in read_cal(FIXTURE / "cal002")["xy"][:3]:
        w.picks.append((float(x), float(y)))
    w._draw_picks()
    w.cal_out.setText(str(tmp_path / "cal_pick"))
    w.cal_slices.setValue(9)
    w.cal_avg.setValue(3)
    w.cal_settle.setValue(0.0)
    w._run_zscan()
    _until(app, lambda: w.cal_status.text().startswith("done"), 120, "z scan of the picks")
    w._toggle_acq()
    _until(app, lambda: not api.acq.running(), 20, "stop")
    w._load_cal_list()
    assert w.bead_list.count() == 3
    w._select_beads()
    _until(app, lambda: w.bead_ids == [1, 2, 3], 20, "select")
    assert w.picks == []                                      # the picks became the selected beads
    w._toggle_acq()
    _until(app, lambda: api.acq.running() and api.acq.status()["frames_tracked"] > 10, 30, "tracking")
    _until(app, lambda: api.acq.status()["frames_tracked"] > 150, 30, "tracking past the 79 frames seen once")
    assert api.acq.running(), api.acq.status()
    w._toggle_acq()
    _until(app, lambda: not api.acq.running(), 20, "stop 2")


def test_camera_settings_and_device_info_open_in_panels(window):
    """Owner 2026-10-31: the camera settings are not crammed into the step column but open in their own panel; a
    click on a device row opens that device's information, like the mock-up's device list."""
    app, w = window
    assert not w.cam_panel.isVisible() and w.em_group.parent() is not None
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w.dev_table.cellClicked.emit(0, 0)
    _until(app, lambda: w.dev_panel.isVisible() and "model" in w.dev_info.text(), 10, "device info panel")
    assert w.dev_panel.windowTitle() == "Device: " + w.dev_table.item(0, 0).text()
    assert w.dev_form is not None and w.dev_form.layout().rowCount() > 2       # rows, not a raw dump
    w.cam_panel.open_()
    assert w.cam_panel.isVisible() and w.em_group.isVisible() and w.em_exp.isVisible()


def test_touch_position_is_kept_locked_and_applied_at_connect(window, monkeypatch, tmp_path):
    """Owner 2026-10-31: the touch position starts from the LabVIEW value (40.94 mm), changes only through
    Change... / Set, is kept in a file across restarts and is in force right after Connect."""
    from mtpy.gui import app as gui_app
    app, w = window
    monkeypatch.setattr(gui_app, "TOUCH_FILE", tmp_path / "touch_position.json")
    assert w.touch_mm.value() == 40.94 and not w.touch_mm.isEnabled() and not w.btn_touch_set.isEnabled()
    w._unlock_touch()
    w.touch_mm.setValue(40.5)
    w._set_touch()
    assert not w.touch_mm.isEnabled() and gui_app.load_touch_mm() == 40.5
    w._connect()
    _until(app, lambda: api.magnet.force_calibration()["ready"], 15, "touch position applied at connect")
    assert api.magnet.force_calibration()["touch_mm"] == 40.5


def test_connect_is_refused_while_the_emergency_stop_is_engaged(window):
    """Fault list G15 (owner 2026-10-31 "둘 다 고쳐"): Connect used to clear an engaged stop silently; now it is refused
    until Acknowledge."""
    app, w = window
    w._estop()
    w._connect()
    _until(app, lambda: any("Acknowledge first" in w.events_list.item(i).text() for i in range(w.events_list.count())),
           5, "refusal shown")
    assert api.devices.status() == {} and estop.active()
    w._estop_clear()
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect after Acknowledge")


def test_device_panel_has_numeric_controls_that_move_the_device(window):
    """Owner 2026-10-31: the device panel is a control panel - numbers go into numeric fields; Move acts and the
    panel reads the device back."""
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    row = next(i for i in range(w.dev_table.rowCount()) if w.dev_table.item(i, 0).text() == "magnet")
    w.dev_table.cellClicked.emit(row, 0)
    _until(app, lambda: "position_mm" in w.dev_controls, 10, "magnet controls")
    c = w.dev_controls
    assert c["position_mm"].maximum() == pytest.approx(safety.profile()["limits"]["magnet_position_mm"]["max"])
    c["position_mm"].setValue(1.5)
    w._dev_act("magnet", "magnet move", lambda: api.magnet.move_to(c["position_mm"].value(), c["speed_mm_s"].value()).wait(60))
    _until(app, lambda: abs(api.magnet.position() - 1.5) < 0.01, 20, "magnet moved from the panel")
    _until(app, lambda: "position_mm" in w.dev_controls and w.dev_controls["position_mm"] is not c["position_mm"], 10,
           "panel read back after the move")
    assert w.dev_controls["position_mm"].value() == pytest.approx(1.5, abs=0.01)


def test_setup_has_a_camera_sdk_selector_in_the_connect_preset(window, monkeypatch):
    """Owner 2026-11-01: the Setup panel chooses the JAI's SDK (IMAQdx default, eBUS) and Connect passes it on."""
    app, w = window
    seen = {}
    real = api.devices.connect
    monkeypatch.setattr(api.devices, "connect", lambda p: seen.update(p) or real(p))
    assert w.cam_sdk.currentData() == "imaqdx"
    w.cam_sdk.setCurrentIndex(1)
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    assert seen["camera_sdk"] == "ebus" and seen["backend"] == "sim"       # the sim ignores it; a real backend builds EbusCamera


def test_apply_preset_asks_before_a_guarded_change_while_recording(window, monkeypatch):
    """Fault list G5: the GUI's confirm=True is the operator's answer to a question, not a default."""
    from PySide6.QtWidgets import QMessageBox
    app, w = window
    calls = []
    monkeypatch.setattr(api.acq, "status", lambda: {"running": True, "recording": True})
    monkeypatch.setattr(api.camera, "apply_preset", lambda preset, confirm=False: calls.append(confirm) or {})
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    w._apply_preset()
    assert calls == []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    w._apply_preset()
    _until(app, lambda: calls == [True], 5, "preset applied after yes")
