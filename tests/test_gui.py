"""Phase 8 first build: the window drives the whole simulated flow through the public API (connect, camera preset,
beads from the fixture .cal, acquisition with the display tap, a protocol, recording, stop). Offscreen Qt; skipped
without PySide6 or the G: fixture."""
import os
import shutil
import time

import numpy as np
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
    raise AssertionError(f"timeout: {what() if callable(what) else what}")   # a callable: evaluated at the failure


@pytest.fixture
def window(tmp_path, monkeypatch):
    need(FIXTURE / "cal002")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from mtpy.gui.__main__ import sim_dev_config
    from mtpy.gui.app import MainWindow
    QSettings.setDefaultFormat(QSettings.IniFormat)          # design critique #3: never the user's own settings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
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
    assert w.ed_h5.text().endswith("tra001.h5") and "tracking 5 beads" in w.run_track.text()
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
    _until(app, lambda: "6 of 6 calls ok" in w.em_readback.text(), 10,
           lambda: f"shutter exercise; the read-back shows {w.em_readback.text()!r}; status {w.statusBar().currentMessage()!r}")
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
    """Owner 2026-10-31: a click on a device row opens that device's information, like the mock-up's device list.
    Owner 2026-11-13: the camera settings have no panel of their own - the camera / emccd row opens them."""
    app, w = window
    assert not w.dev_panel.isVisible() and w.em_group.parent() is not None and not hasattr(w, "cam_panel")
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w.dev_table.cellClicked.emit(0, 0)
    _until(app, lambda: w.dev_panel.isVisible() and "model" in w.dev_info.text(), 10, "device info panel")
    assert w.dev_panel.windowTitle() == "Device: " + w.dev_table.item(0, 0).text()
    assert w.dev_form is not None and w.dev_form.layout().rowCount() > 2       # rows, not a raw dump
    rows = {w.dev_table.item(r, 0).text(): r for r in range(w.dev_table.rowCount())}
    assert not w.cam_box.isVisible() and not w.em_box.isVisible()               # row 0 is not a camera
    w.dev_table.cellClicked.emit(rows["camera"], 0)
    _until(app, lambda: w.cam_box.isVisible(), 10, "the camera row opens the camera settings")
    assert w.cam_attrs.isVisible() and w.cam_rate.isVisible() and not w.em_box.isVisible()
    assert "rate_Hz" not in w.dev_controls                                      # one place per setting
    w.dev_table.cellClicked.emit(rows["emccd"], 0)
    _until(app, lambda: w.em_box.isVisible(), 10, "the emccd row opens the EMCCD settings")
    assert w.em_group.isVisible() and w.em_exp.isVisible() and not w.cam_box.isVisible()


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


def test_bead_chips_wrap_into_rows(window):
    """G16 (rig 2026-11-01): 256 chips in one row made the window 14 726 px wide; they wrap after CHIPS_PER_ROW."""
    from mtpy.gui.app import CHIPS_PER_ROW
    _, w = window
    w.bead_ids = list(range(1, 41))
    w._rebuild_chips()
    assert w.bead_chips.count() == 40 and w.bead_chips.rowCount() == -(-40 // CHIPS_PER_ROW)
    assert w.bead_chips.columnCount() == CHIPS_PER_ROW


def test_plot_refresh_rate_is_the_users_and_paces_only_the_redraw(window, monkeypatch):
    """Owner 2026-11-01: the plot's Hz is a user control; the history keeps every displayed frame, the redraw is
    paced."""
    app, w = window
    w._connect()
    _until(app, lambda: api.devices.status() and not w._workers, 30, "connected")
    w._load_cal_list()
    w._select_beads()
    _until(app, lambda: w.bead_ids, 10, "beads selected")
    redraws = []
    monkeypatch.setattr(w, "_update_plot", lambda: redraws.append(time.monotonic()))
    w.plot_hz.setValue(2)
    w._toggle_acq()
    _until(app, lambda: api.acq.running(), 10, "acquisition")
    _pump(app, 2.0)
    assert 2 <= len(redraws) <= 6 and len(w.history) > len(redraws) * 3      # ~2 Hz redraws, data at the display rate
    w._toggle_acq()
    _until(app, lambda: not api.acq.running(), 10, "stopped")


def test_start_runs_the_protocol_a_second_time(window):
    """Owner 2026-11-04 (from the experiment): "Experiment ran the first time I pressed Start, not the next time" -
    on the simulators two Starts in a row run; a refusal on the rig shows in the Experiment label and the log."""
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w._call(lambda: api.magnet.set_touch_position(40.0), "touch")
    _until(app, lambda: api.magnet.force_calibration()["ready"], 10, "touch position")
    w.prot_edit.setPlainText(PROTOCOL)
    for n in (1, 2):
        w._run_protocol()
        _until(app, lambda: api.protocol.status()["state"] == "completed", 30, f"protocol {n} completed")
        _until(app, lambda: "completed" in w.prot_status.text(), 5, f"protocol {n} label")
    assert not [w.events_list.item(i).text() for i in range(w.events_list.count()) if "refused" in w.events_list.item(i).text()]


def test_left_click_on_the_image_adds_a_pick_inside_the_margin_only(window):
    """Owner 2026-11-04 evening: "beads cannot be picked" - the edge-margin check of the morning called a name the
    GUI's zscan module did not re-export, so every left click failed silently."""
    from PySide6.QtCore import QPointF, Qt

    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._toggle_acq()
    _until(app, lambda: api.acq.running() and w.img_item.image is not None, 30, "an image on screen")
    _pump(app, 0.5)                                               # the view auto-ranges to the image

    class _Ev:
        def __init__(self, x, y, button=Qt.LeftButton):
            self._p, self._b = w.vb.mapViewToScene(QPointF(x, y)), button

        def scenePos(self):
            return self._p

        def button(self):
            return self._b
    w._on_view_click(_Ev(640.0, 512.0))
    assert len(w.picks) == 1 and abs(w.picks[0][0] - 640.0) < 1 and abs(w.picks[0][1] - 512.0) < 1
    w._on_view_click(_Ev(1230.0, 500.0))                         # 50 px from the right edge: refused, not added
    assert len(w.picks) == 1 and any("from the right edge" in w.events_list.item(i).text() for i in range(w.events_list.count()))
    w._on_view_click(_Ev(641.0, 513.0, Qt.RightButton))          # right click removes the nearest pick
    assert w.picks == []
    w._toggle_acq()
    _until(app, lambda: not api.acq.running(), 15, "acquisition stopped")


def test_explore_shows_positions_and_relative_moves_return_to_zero(window, monkeypatch, tmp_path):
    """Owner 2026-11-04: Explore shows every motor's position and the force live, the magnet speed, two PI presets
    (Cal+ / Cal-), and a relative move's entry returns to 0 once the move is done."""
    from mtpy.gui import app as gui_app
    monkeypatch.setattr(gui_app, "PRESETS_FILE", tmp_path / "presets.json")
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    _until(app, lambda: "magnet" in w.positions.text() and "focus" in w.positions.text() and "stage" in w.positions.text(),
           10, "live positions")
    w.mag_by.setValue(1.5)
    w._move_magnet_by()
    _until(app, lambda: abs(api.magnet.position() - 1.5) < 0.01 and w.mag_by.value() == 0.0, 30, "magnet moved by 1.5, entry back to 0")
    w.preset_mm["Cal+"].setValue(3.0)
    assert gui_app.load_presets()["Cal+"] == 3.0
    w._go_preset("Cal+")
    _until(app, lambda: abs(api.magnet.position() - 3.0) < 0.01, 30, "preset Cal+ reached")
    w.rotor_turns.setValue(1.0)
    w.btn_rotate.click()                            # the button itself: wired wrongly, it did nothing (rig 2026-11-15)
    _until(app, lambda: w.rotor_turns.value() == 0.0, 30, "rotor entry back to 0")
    p0 = api.rotor.position()
    w.rotor_turns.setValue(-0.05)                   # rig 2026-11-15: one decimal turned 0.05 into 0 (no move)
    assert w.rotor_turns.value() == -0.05
    w.btn_rotate.click()
    _until(app, lambda: abs(api.rotor.position() - p0 + 0.05) < 0.003 and w.rotor_turns.value() == 0.0, 30, "-0.05 turn")
    assert (tmp_path / "runs" / "gui_events.log").exists()


def test_camera_attribute_panel_lists_sets_and_keeps_favourites(window, monkeypatch, tmp_path):
    """Owner 2026-11-04: the camera's whole attribute tree in a panel with search, level and favourites; a write
    goes through api.camera.set_attribute and is read back."""
    app, w = window
    monkeypatch.setattr(w.cam_attrs, "favourites_file", tmp_path / "fav.json")
    w.cam_attrs.favourites = []                                    # not the rig's own config/camera_favourites.json
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w.cam_attrs.load()
    _until(app, lambda: "attributes in" in w.cam_attrs.status.text(), 15, "catalogue loaded")
    assert w.cam_attrs.tree.topLevelItemCount() >= 3            # categories
    w.cam_attrs.level.setCurrentIndex(2)                           # guru shows DeviceReset too
    w.cam_attrs.search.setText("trigger")
    names = [w.cam_attrs.tree.topLevelItem(i).child(j).text(0) for i in range(w.cam_attrs.tree.topLevelItemCount())
             for j in range(w.cam_attrs.tree.topLevelItem(i).childCount())]
    assert "TriggerMode" in names and "Width" not in names
    w.cam_attrs.select("TriggerMode")
    w.cam_attrs.control.setCurrentIndex(w.cam_attrs.control.findData("On"))
    w.cam_attrs.write("TriggerMode", w.cam_attrs.control.value())
    _until(app, lambda: api.camera.get_attribute("TriggerMode") == "On", 10, "attribute written")
    _until(app, lambda: "read back" in w.cam_attrs.status.text(), 5, "read back shown")
    w.cam_attrs.toggle_favourite("TriggerMode")
    assert (tmp_path / "fav.json").exists() and w.cam_attrs.fav_form.rowCount() == 1
    w.cam_attrs.write("DeviceReset", True)                        # refused by the device: shown, nothing reset
    _until(app, lambda: "never written" in w.cam_attrs.status.text() or any(
        "never written" in w.events_list.item(i).text() for i in range(w.events_list.count())), 10, "refusal shown")


def test_attribute_panel_shows_the_value_the_device_took(window, monkeypatch, tmp_path):
    """Owner 2026-11-04: the camera rounds to its steps; after Set the control must show the applied value, not the
    typed one, and say so."""
    app, w = window
    monkeypatch.setattr(w.cam_attrs, "favourites_file", tmp_path / "fav.json")
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w.cam_attrs.load()
    _until(app, lambda: "attributes in" in w.cam_attrs.status.text(), 15, "catalogue loaded")
    w.cam_attrs.select("AcquisitionFrameRate")
    w.cam_attrs.control.setValue(150.0)
    w.cam_attrs.write("AcquisitionFrameRate", 150.0)
    _until(app, lambda: "the device took" in w.cam_attrs.status.text(), 10, "rounding shown")
    assert w.cam_attrs.control.value() == pytest.approx(149.9925, abs=1e-3)       # 1e6 / 6667 us
    w.cam_attrs.select("Width")
    w.cam_attrs.write("Width", 645)
    _until(app, lambda: w.cam_attrs.control.value() == 648, 10, "width rounded to the 8-px step")


def test_experiment_table_compiles_the_owners_example_and_runs(window):
    """Owner 2026-11-04: the Experiment table (rows parameters, columns iterations) compiles to the script and
    Start-from-table runs it on the simulators."""
    from mtpy.gui.exptable import EXAMPLE, compile_table

    text = compile_table(EXAMPLE)
    assert text.splitlines()[2:] == ["loading magnet", "# column 1", "rotate from=0 to=-10 f=1 spd=50", "# column 2", "rotate from=-10 to=0 f=1 spd=50",
                                     "# column 3: nothing to do", "# column 4", "ramp from=1 to=50 speed=0.03",
                                     "# column 5", "ramp from=50 to=1 speed=0.1", "end protocol"]
    rep = compile_table(EXAMPLE, repeat=3).splitlines()       # owner 2026-11-05: cycle repeat -> loop n=
    assert rep[2] == "loading magnet" and rep[3] == "loop n=3" and rep[-2:] == ["end", "end protocol"]
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    # rig 2026-11-05: a 30 mm ramp at 0.1 mm/s (300 s) was cut off by the 60 s arrival wait; the move now says how
    # long it takes and the waits stretch by 1.5 x that
    api.magnet.move_to(0.0).wait(10)
    m = api.magnet.move_to(5.0, speed_mm_s=1.0)
    m.wait(20)
    assert m.expected_s() == pytest.approx(5.0, abs=0.01)
    w.exp_table.repeat.setValue(2)
    assert "loop n=2" in w.exp_table.to_script()
    w.exp_table.repeat.setValue(1)
    w._apply_preset()
    w._call(lambda: api.magnet.set_touch_position(40.0), "touch")
    _until(app, lambda: api.magnet.force_calibration()["ready"], 10, "touch position")
    w.exp_table.set_columns([[1, 0.2, 0, 0, 0], [2, 0.1, 1.0, 0, 0], [2, 0.1, 0, 36, 50]])
    w._start_from_table()
    assert "ramp from=1 to=2 speed=1" in w.prot_edit.toPlainText() and "rotate from=0 to=0.1 f=2 spd=50" in w.prot_edit.toPlainText()
    _until(app, lambda: api.protocol.status()["state"] == "completed", 60, "table protocol completed")
    assert api.protocol.status()["steps_done"] == 5                 # hold, ramp, wait, rotate, wait


def test_cal_path_moves_to_the_next_free_name(tmp_path):
    """Owner 2026-11-05 ("cal_gui exists; never overwritten" at every second scan): the z scan takes the next free
    cal00N by itself."""
    from mtpy.gui.app import next_free
    assert next_free(tmp_path / "cal001") == tmp_path / "cal001"
    (tmp_path / "cal001").write_text("x")
    (tmp_path / "cal002").write_text("x")
    assert next_free(tmp_path / "cal001") == tmp_path / "cal003"
    (tmp_path / "cal_gui").write_text("x")
    assert next_free(tmp_path / "cal_gui") == tmp_path / "cal_gui001"
    from mtpy.gui.app import next_tra
    assert next_tra(tmp_path) == "tra001"
    (tmp_path / "tra001.h5").write_text("x")
    (tmp_path / "tra002-000").write_text("x")
    assert next_tra(tmp_path) == "tra003"


def test_start_replaces_the_running_protocol_and_the_badge_shows_it(window):
    """Owner 2026-11-05: a new Start ends the protocol that runs and runs the new one; the top bar says which state
    the protocol is in."""
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w._call(lambda: api.magnet.set_touch_position(40.0), "touch")
    _until(app, lambda: api.magnet.force_calibration()["ready"], 10, "touch position")
    w.prot_edit.setPlainText('grammar 0.1\nprotocol "long"\nhold f=1 t=60\nend protocol\n')
    w._run_protocol()
    _until(app, lambda: api.protocol.status()["state"] == "running", 20, "first protocol running")
    _until(app, lambda: "PROTOCOL running" in w.prot_badge.text(), 5, "badge")
    n = len(events.events())
    w.prot_edit.setPlainText('grammar 0.1\nprotocol "short"\nhold f=1 t=0.2\nend protocol\n')
    w._run_protocol()
    _until(app, lambda: any(e.kind == "protocol" and e.extra.get("action") == "end" and e.extra.get("name") == "long"
                            for e in events.events()[n:]), 30, "the long protocol ended")
    _until(app, lambda: api.protocol.status()["state"] == "completed" and api.protocol.status().get("name") == "short",
           30, "the short one ran")
    _until(app, lambda: w.prot_badge.text() == "no protocol", 5, "badge cleared")


def test_new_calibration_drops_the_beads_and_the_rotor_turns_once(window):
    """Owner 2026-11-05: with beads selected the image took no picks; 'New calibration' drops them (acquisition
    restarted without beads) so clicks pick again. The +1 / -1 turn buttons rotate one turn and leave the entry."""
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w._load_cal_list()
    w._select_beads()
    _until(app, lambda: w.bead_ids, 10, "beads selected")
    w._toggle_acq()
    _until(app, lambda: api.acq.running() and "JAI frame" in w.cam_label.text, 20, "acquisition")
    seg = api.acq.status()["segment"]
    w._new_calibration()
    _until(app, lambda: api.beads.selected() is None and w.bead_ids == [] and api.acq.running()
           and api.acq.status()["segment"] == seg, 30, "beads dropped, the camera never stopped")
    w.rotor_turns.setValue(3.0)
    p0 = api.rotor.position()
    w._rotate(1.0)
    _until(app, lambda: abs(api.rotor.position() - p0 - 1.0) < 0.01, 30, "+1 turn")
    assert w.rotor_turns.value() == 3.0
    w._rotate(-1.0)
    _until(app, lambda: abs(api.rotor.position() - p0) < 0.01, 30, "-1 turn")


def test_calibration_viewer_shows_the_lut_and_saves_the_band_to_the_cal(tmp_path):
    """Owner 2026-11-05 ("why is the calibration not fixed: band-pass, forget radius, PSF"): the viewer shows one
    bead's stack, its band-passed LUT and the self-fit; Save writes LOW / HIGH / forget into the .cal's bead_i32."""
    import shutil

    from PySide6.QtWidgets import QApplication

    from mtpy.gui.calview import CalView, self_fit
    from mtpy.lvfiles import read_cal
    need(FIXTURE / "cal002")
    QApplication.instance() or QApplication([])
    path = tmp_path / "cal_view"
    shutil.copy(FIXTURE / "cal002", path)
    cal = read_cal(path)
    z, found = self_fit(cal, 0, 0, 40, 10)
    mid = slice(len(z) // 4, 3 * len(z) // 4)
    assert len(z) == cal["n_slices"] and np.isfinite(found[mid]).all()
    assert np.nanmedian(np.abs(found[mid] - z[mid])) < 0.05           # the LUT finds its own slices within 50 nm
    saved = []
    v = CalView(on_saved=saved.append)
    v.load(path)
    assert v.bead.count() == len(cal["stack"]) and "self-fit residual" in v.info.text()
    v.forget.setValue(12)
    v.save()
    assert saved == [str(path)] and list(read_cal(path)["bead_i32"][0]) == [v.low.value(), v.high.value(), 12]
    assert list(read_cal(path)["bead_i32"][1]) == list(cal["bead_i32"][1])
    v.all_beads.setChecked(True)
    v.high.setValue(30)
    v.save()
    assert (read_cal(path)["bead_i32"] == [v.low.value(), 30, 12]).all()



def test_run_page_calibrates_then_tracks_into_the_chosen_run_file(window, monkeypatch, tmp_path):
    """Owner 2026-11-05: camera -> picks -> calibrate (asks for the .cal) -> asks for the run file -> tracking every
    bead of the .cal; watching without beads writes no file."""
    from PySide6.QtWidgets import QFileDialog

    from mtpy.lvfiles import read_cal
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w._toggle_acq()
    _until(app, lambda: api.acq.running() and w.img_item.image is not None, 20, "camera")
    assert w.ed_h5.text() == "" and "no beads" in w.run_track.text()
    cal = read_cal(FIXTURE / "cal002")
    w.picks = [tuple(xy) for xy in cal["xy"][:2, :2]]
    w._draw_picks()
    assert "2 picked" in w.run_beads.text()
    w.cal_slices.setValue(5)       # 3 slices crashed this test now and then: the z fit read past a 3-slice LUT
    w.cal_avg.setValue(1)
    w.cal_settle.setValue(0.0)
    asked = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: (asked.append(a[1]), str(tmp_path))[1]))
    w._flow_calibrate()
    seg = api.acq.status()["segment"]
    _until(app, lambda: w.bead_ids == [1, 2] and api.acq.running() and w.ed_h5.text() == str(tmp_path / "tra001.h5"), 60,
           "scan, beads selected, tracking into the chosen run file")
    assert len(asked) == 1 and (tmp_path / "cal001").exists() and w.roles[1] == "reference"
    assert w.btn_run_cam.text() == "Stop the camera"
    assert api.acq.status()["segment"] == seg          # the camera never stopped
    w._new_calibration()
    _until(app, lambda: api.beads.selected() is None and w.bead_ids == [] and api.acq.running()
           and api.acq.status()["segment"] == seg and w.ed_h5.text() == "", 30, "beads dropped, camera still running")
    w._toggle_acq()
    _until(app, lambda: not api.acq.running(), 15, "stopped")


def test_pre_calibration_tracks_with_a_saved_reference_and_zeroes_the_plot(window, monkeypatch, tmp_path):
    """Owner 2026-11-14: a reference is a name -> a .cal path and one bead (json, paths only); Pre-calibrate gives
    every picked bead that LUT with no z scan and no reference bead, sets the camera to the conditions in the run
    metadata beside the reference until Reset calibration, and Set zero makes the z shown now 0 on the graph."""
    import json

    from PySide6.QtWidgets import QFileDialog

    import mtpy.gui.app as gapp
    from mtpy.lvfiles import read_cal
    app, w = window
    monkeypatch.setattr(gapp, "PRECAL_FILE", tmp_path / "precal_references.json")
    ref = tmp_path / "ref"
    ref.mkdir()
    shutil.copy(FIXTURE / "cal002", ref / "cal002")
    (ref / "tra001.meta.json").write_text(json.dumps({
        "calibration": {"path": "X:/moved/cal002"}, "presets": {"rig_name": w.objective.currentData()},
        "devices": {"jai": {"settings_at_start": {"rate_Hz": 90.0, "exposure_ms": 3.0, "gain_dB": 2.0},
                            "binning_at_start": {"horizontal": 1, "vertical": 1}}}}), encoding="utf-8")
    w.precal_name.setText("M270")
    w.precal_cal.setText(str(ref / "cal002"))
    w.precal_bead.setValue(2)
    w._save_precal()
    assert w.precal.currentText() == "M270" and "exposure_ms" in w.precal_status.text()
    assert json.loads(gapp.PRECAL_FILE.read_text(encoding="utf-8")) == {"M270": {"cal": str(ref / "cal002"), "bead": 2}}
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w._toggle_acq()
    _until(app, lambda: api.acq.running() and w.img_item.image is not None, 20, "camera")
    s0 = api.devices.info("camera")["settings"]
    assert s0["exposure_ms"] != pytest.approx(3.0)
    cal = read_cal(FIXTURE / "cal002")
    w.picks = [tuple(xy) for xy in cal["xy"][:2, :2]]
    w._draw_picks()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    # the camera at another binning: the first press sets the reference's and asks for the picks again
    state, writes = {"horizontal": 2, "vertical": 2}, []
    monkeypatch.setattr(api.camera, "binning", lambda: dict(state))
    monkeypatch.setattr(api.camera, "set_attribute", lambda name, v, confirm=False: (
        writes.append((name, v)), state.update({"horizontal" if "Horizontal" in name else "vertical": v})))
    w._flow_precal()
    _until(app, lambda: not w.picks and "click the beads again" in w.precal_info.text(), 20, "binning set, picks dropped")
    assert writes == [("BinningHorizontal", 1), ("BinningVertical", 1)] and w.bead_ids == []
    w.picks = [tuple(xy) for xy in cal["xy"][:2, :2]]
    w._draw_picks()
    w._flow_precal()
    _until(app, lambda: w.bead_ids == [1, 2] and w.ed_h5.text() == str(tmp_path / "tra001.h5"), 60,
           "the picked beads tracked with the reference's LUT")
    out = read_cal(tmp_path / "precal001")
    assert (out["stack"] == cal["stack"][1]).all() and (out["xy"] == cal["xy"][:2, :2]).all()
    assert set(w.roles.values()) == {"tethered"}                          # no reference bead
    s = api.devices.info("camera")["settings"]
    assert s["exposure_ms"] == pytest.approx(3.0) and s["gain_dB"] == pytest.approx(2.0)
    _until(app, lambda: len(w.history) > 3, 20, "tracked rows")
    w.btn_zero.click()
    w._draw(w.plot, w.curves, "t", "z", None)
    assert w.z_zero is not None and len(w.z_zero) == 2
    assert "zero" in w.plot.getAxis("left").labelText
    w._new_calibration()
    _until(app, lambda: api.beads.selected() is None and w.z_zero is None and state == {"horizontal": 2, "vertical": 2}
           and api.devices.info("camera")["settings"]["exposure_ms"] == pytest.approx(s0["exposure_ms"]), 30,
           "beads dropped, the zero cleared, the camera as before")
    w._toggle_acq()
    _until(app, lambda: not api.acq.running(), 15, "stopped")


def test_experiment_opens_empty_and_the_estop_banner_shows_only_while_engaged(window):
    """Design critique 2026-11-05 #1 and #4: no runnable example on the Experiment page at start; the red banner
    with Acknowledge appears with the emergency stop and goes with it."""
    app, w = window
    assert w.prot_edit.toPlainText() == "" and w.exp_table.columns() == [["0"] * 6]
    w.exp_table.btn_example.click()
    assert len(w.exp_table.columns()) == 5
    assert not w.estop_banner.isVisible()
    w._estop()
    _until(app, lambda: w.estop_banner.isVisible() and w.btn_ack.isVisible(), 5, "banner")
    w._estop_clear()
    _until(app, lambda: not w.estop_banner.isVisible(), 5, "banner gone")


def test_owner_feedback_2026_11_06_plot_folder_rate_and_step_highlight(window, monkeypatch, tmp_path):
    """Owner 2026-11-06 after the first experiment: (1) the trace plot subtracts the reference beads' mean from the
    tethered beads; (2) the run folder follows the .cal's folder unless the user browsed one; (3) a table column with
    a Force rate compiles to `ramp rate=` (pN/s); (4) the running statement and its column are highlighted."""
    from PySide6.QtWidgets import QFileDialog

    from mtpy.gui.exptable import compile_table
    app, w = window
    # (1) reference subtraction on the plot
    w.bead_ids, w.roles = [1, 2], {1: "reference", 2: "tethered"}
    w._rebuild_chips()
    w.t0 = time.time()
    for k in range(5):
        w.history.append((0.1 * k, 1.0, 2.0, np.array([[10.0, 20.0, 0.5 * k], [11.0, 21.0, 1.0 + 0.5 * k]])))
    w.history.append((0.5, 1.0, 2.0, np.array([[-1.0, -1.0, -1.0], [11.0, 21.0, 3.5]])))   # the reference lost once (the kernel's row)
    w.ax_y.setCurrentIndex(list(w.ax_y.itemData(i) for i in range(w.ax_y.count())).index("z"))
    w._update_plot()
    y2 = w.curves[2].yData
    assert np.allclose(y2[:5], 1.0) and np.isnan(y2[5])                    # tethered - reference; lost = gap
    assert np.allclose(w.curves[1].yData[:5], [0, 0.5, 1.0, 1.5, 2.0])     # the reference stays raw
    assert w.curves[2].name() == "b2 - ref" and "ref, raw" in w.curves[1].name()
    w.sub_ref.setChecked(False)
    w._update_plot()
    assert np.allclose(w.curves[2].yData[:5], [1.0, 1.5, 2.0, 2.5, 3.0]) and w.curves[2].name() == "b2"
    # owner 2026-11-10: the Plot page's tall graph draws only while its page is shown, with its own axes
    assert not w.curves2
    w._set_step(w.panel.indexOf(w.plot2.parent()))
    w.ax_x2.setCurrentIndex(w.ax_x2.findData("force"))
    w._update_plot()
    assert np.allclose(w.curves2[2].xData, 2.0) and np.allclose(w.curves2[2].yData[:5], [1.0, 1.5, 2.0, 2.5, 3.0])
    # owner 2026-11-10: the span is the user's - the tall graph on any X axis, the wide one's Follow length
    w.history.append((100.0, 1.0, 2.0, np.array([[10.0, 20.0, 1.0], [11.0, 21.0, 2.0]])))
    w.last2_s.setValue(5)
    w.follow_s.setValue(5)
    w._update_plot()
    assert len(w.curves2[2].xData) == 1 and len(w.curves[2].xData) == 1
    w.last2.setChecked(False)
    w._update_plot()
    assert len(w.curves2[2].xData) == 7
    # (2) the run folder follows the calibration's folder
    cal_dir = tmp_path / "cells" / "A"
    cal_dir.mkdir(parents=True)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(cal_dir / "cal003"), "")))
    w._browse_cal_out()
    assert w.ed_out.text() == str(cal_dir) and w.ed_name.text() == "tra001"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path / "elsewhere")))
    w._browse_out()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(FIXTURE / "cal002"), "")))
    w._browse_cal()
    assert w.ed_out.text() == str(tmp_path / "elsewhere")                 # browsed by hand: the .cal no longer wins
    # (3) the table's Loading choice: magnet mm/s or force pN/s, one or the other
    text = compile_table([[1, 0, 0.1, 0, 0], [10, 2, 0.5, 0, 0], [1, 0, 0.1, 0, 0]], force_rate=True)
    assert "ramp from=1 to=10 rate=0.5" in text and "ramp from=10 to=1 rate=0.1" in text
    w.exp_table.set_columns([[1, 0, 0.1, 0, 0], [10, 2, 0.5, 0, 0]])
    assert "speed=0.5" in w.exp_table.to_script() and w.exp_table.table.verticalHeaderItem(2).text() == "Motor (mm/s)"
    w.exp_table.loading.setCurrentIndex(1)
    assert "rate=0.5" in w.exp_table.to_script() and w.exp_table.table.verticalHeaderItem(2).text() == "Force rate (pN/s)"
    w.exp_table.loading.setCurrentIndex(0)
    # (4) the running statement highlighted in the script and the table
    w.prot_edit.setPlainText(text)
    w._show_current({"step": 2, "line": 6, "statement": "ramp from=1 to=10 rate=0.5"})
    assert [s.cursor.blockNumber() for s in w.prot_edit.extraSelections()] == [5]
    assert w.exp_table.table.item(0, 1).background().color().name() == "#ffd54f"
    assert w.exp_table.table.item(0, 0).background().color().name() != "#ffd54f"
    w._show_current(None)
    assert w.prot_edit.extraSelections() == [] and w.exp_table.table.item(0, 1).background().color().name() != "#ffd54f"
    w._show_run_doc()
    assert "metadata" in w.run_doc_panel.findChild(QTextBrowser_).toPlainText()


from PySide6.QtWidgets import QTextBrowser as QTextBrowser_  # noqa: E402 - used by the test above only


def test_autofocus_holds_the_reference_bead_through_the_focus(window):
    """Owner 2026-11-06: the piezo (focus) holds the reference bead's z at the LUT's middle; on its own thread, one
    step of at most 0.2 um per period; off with the camera."""
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w.autofocus.setChecked(True)                 # no beads yet: refused, stays off
    _pump(app, 0.3)
    assert not w.autofocus.isChecked() and not api.focus.autofocus_status()["on"]
    w.ed_cal.setText(str(FIXTURE / "cal002"))
    w._load_cal_list()
    w._select_beads()
    _until(app, lambda: w.bead_ids and w.roles.get(1) == "reference", 10, "beads")
    w._toggle_acq()
    _until(app, lambda: api.acq.running() and api.acq.display() is not None and api.acq.display().result is not None, 20, "camera")
    z0 = api.focus.position()
    w.autofocus.setChecked(True)
    _until(app, lambda: api.focus.autofocus_status()["on"] and api.focus.autofocus_status()["moves"] >= 2, 15, "autofocus moves")
    st = api.focus.autofocus_status()
    assert st["bead"] == 1 and st["error"] is None and "holding bead 1" in w.af_status.text()
    # owner 2026-11-12: the target is a percent of the LUT, default 30
    from mtpy.lvfiles import read_cal

    cal = read_cal(FIXTURE / "cal002")
    span = (cal["n_slices"] - 1) * float(cal["z_step"])
    assert st["target_percent"] == w.af_target.value() == 30 and abs(st["z_center_um"] - 0.3 * span) < 1e-9
    w.af_target.setValue(50)
    _until(app, lambda: abs(api.focus.autofocus_status()["z_center_um"] - 0.5 * span) < 1e-9, 10, "target 50 %")
    w.af_target.setValue(30)
    _until(app, lambda: abs(api.focus.autofocus_status()["z_center_um"] - 0.3 * span) < 1e-9, 10, "target 30 %")
    assert abs(api.focus.position() - z0) <= 0.2 * (api.focus.autofocus_status()["moves"] + 1) + 1e-6
    af = [e for e in events.events() if e.kind == "autofocus_move"]
    assert af and abs(af[-1].extra["step_um"]) <= 0.2 and af[-1].extra["bead"] == 1
    w._toggle_acq()
    _until(app, lambda: not api.acq.running() and not w.autofocus.isChecked(), 15, "stopped, autofocus off")
    _until(app, lambda: not api.focus.autofocus_status()["on"], 10, "autofocus thread off")   # switched off on a worker


def test_bead_near_the_lut_edge_is_shown_orange_on_the_box_and_the_chip(window):
    """Owner 2026-11-06 ("how do I know the bead is near the calibration boundary?"): within 10 slices of either
    LUT end the bead's box and chip turn orange, the chip reads the raw z against the LUT top."""
    app, w = window
    w.ed_cal.setText(str(FIXTURE / "cal002"))
    w._load_cal_list()
    n, step = w.lut
    assert n == 60 and step == pytest.approx(0.1, abs=1e-6) and "z 0 .. 5.9 um, middle 3.0" in w.beads_info.text()
    w.bead_ids, w.roles = [1, 2, 3], {1: "reference", 2: "tethered", 3: "tethered"}
    w._rebuild_chips()
    z = np.array([3.0, 5.2, -1.0])
    w._draw_boxes(np.array([[100.0, 100.0], [200.0, 200.0], [300.0, 300.0]]), np.array([True, True, False]), z)
    colors = [b.pen().color().name().upper() for b in w.boxes if hasattr(b, "pen")]
    assert colors == [COLORS_[0].upper(), "#F97316", "#9CA3AF"]
    w._chip_texts(np.array([[100.0, 100.0, 3.0], [200.0, 200.0, 5.2], [-1.0, -1.0, -1.0]]))
    assert w.chips[1].text() == "b1 3.0/5.9" and w.chips[2].text() == "b2 5.2/5.9" and w.chips[3].text() == "b3 lost"
    assert all(c.width() == 104 for c in w.chips.values())      # Request1 item 2: a fixed width, no re-layout
    assert "#F97316" in w.chips[2].styleSheet() and "#F97316" not in w.chips[1].styleSheet()
    assert w._near_edge(0.9) and not w._near_edge(1.1) and w._near_edge(4.95) and not w._near_edge(4.8)
    w.lut = (60, -0.1)                                  # the mirror test (a negative step): z <= 0, index = z / step
    assert w._near_edge(-0.9) and not w._near_edge(-1.1) and w._near_edge(-4.95) and not w._near_edge(-4.8)
    w._chip_texts(np.array([[100.0, 100.0, -1.0]]))     # z = -1.0 is a VALUE here (index 10), not the lost marker
    assert w.chips[1].text() == "b1 -1.0/-5.9"


from mtpy.gui.app import COLORS as COLORS_  # noqa: E402 - used by the test above only


def test_request2_explore_on_the_run_page_and_the_cal_dialog_start(window, monkeypatch, tmp_path):
    """Requests/Request2 (owner 2026-11-06): Explore sits inside the Run page; the calibration folder dialog starts
    at the owner's Dropbox data folder when it exists. (The Scan direction choice of the first answer is gone: the
    reversed sign is the driver's, owner 2026-11-07.)"""
    from pathlib import Path

    from PySide6.QtWidgets import QFileDialog

    from mtpy.gui import app as appmod
    app, w = window
    assert [k for k, _ in appmod.STEPS] == ["setup", "run", "exp", "plot", "beads", "cal", "save"]
    assert w.mag_by.window() is w and w.panel.widget(1).isAncestorOf(w.mag_by)       # Explore inside Run (page 1)
    assert not hasattr(w, "scan_dir")
    seen = {}
    monkeypatch.setattr(api.zscan, "run", lambda *a, **k: seen.update(k) or {"xy": [[1, 2]]})
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w._toggle_acq()
    _until(app, lambda: api.acq.running(), 20, "camera")
    w.picks = [(640.0, 512.0)]
    w.cal_out.setText(str(tmp_path / "cal001"))
    w._run_zscan()
    _until(app, lambda: "settle_s" in seen, 10, "scan started")
    assert "direction" not in seen
    asked = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: (asked.append(a[2]), "")[1]))
    w._flow_calibrate()
    assert asked and asked[0] == (str(appmod.CAL_ROOT) if appmod.CAL_ROOT.is_dir() else str(Path(w.cal_out.text()).parent))
    w._toggle_acq()
    _until(app, lambda: not api.acq.running(), 15, "stopped")


def test_script_to_table_round_trip():
    """Owner 2026-11-10: script -> table. A table's script parses back to a table that compiles to the same script;
    a line the table cannot hold is refused by its line number."""
    import pytest

    from mtpy.gui.exptable import EXAMPLE, compile_table, parse_script
    for cols, rep, rate in ((EXAMPLE, 1, False), ([[1, 0.2, 0, 0, 0], [2, 0.1, 1.0, 0, 0], [2, 3, 0, 36, 50]], 4, True),
                            ([[5, 2, 0, 0, 0], [5, 1, 0, 0, 0], [7, 2, 0, 0, 0]], 1, False),
                            # owner 2026-11-12: the Focus (um) row, piezo steps at a fixed force
                            ([[10, 30, 0, 0, 0, 0], [10, 10, 0, 0, 0, 0.1], [10, 10, 0, 0, 0, 0.2], [10, 5, 0, 0, 0, 0]], 1, True),
                            ([[1, 2, 0, 0, 0, 0.5], [3, 0, 1, 0, 0, -0.5]], 2, True)):
        text = compile_table(cols, "t", rep, rate)
        back, rep2, rate2 = parse_script(text)
        assert compile_table(back, "t", rep2, rate2) == text and rep2 == rep
    assert "hold f=10 t=30\n# column 2\nfocus um=0.1\nwait t=10\n" in compile_table(
        [[10, 30, 0, 0, 0, 0], [10, 10, 0, 0, 0, 0.1]])
    with pytest.raises(ValueError, match="line 4"):
        parse_script('grammar 0.1\nprotocol "x"\nhold f=1 t=0\nrecord on\nend protocol\n')
    with pytest.raises(ValueError, match="previous force"):
        parse_script("hold f=1 t=0\nramp from=3 to=5 speed=0.1\n")
