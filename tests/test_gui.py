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
    w._rotate()
    _until(app, lambda: w.rotor_turns.value() == 0.0, 30, "rotor entry back to 0")
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
    assert text.splitlines()[2:] == ["# column 1", "rotate from=0 to=-10 f=1 t=10", "# column 2", "rotate from=-10 to=0 f=1 t=10",
                                     "# column 3: nothing to do", "# column 4", "ramp from=1 to=50 speed=0.03",
                                     "# column 5", "ramp from=50 to=1 speed=0.1", "end protocol"]
    app, w = window
    w._connect()
    _until(app, lambda: "8 / 8" in w.dev_summary.text(), 15, "connect")
    w._apply_preset()
    w._call(lambda: api.magnet.set_touch_position(40.0), "touch")
    _until(app, lambda: api.magnet.force_calibration()["ready"], 10, "touch position")
    w.exp_table.set_columns([[1, 0.2, 0, 0, 0], [2, 0.1, 1.0, 0, 0], [2, 0.1, 0, 36, 50]])
    w._start_from_table()
    assert "ramp from=1 to=2 speed=1" in w.prot_edit.toPlainText() and "rotate from=0 to=0.1 f=2 t=0.1" in w.prot_edit.toPlainText()
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
