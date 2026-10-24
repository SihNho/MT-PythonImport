"""WP2: device services, simulators and the device functions of the public API (no hardware, no G: data needed)."""
import json
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from mtpy import api
from mtpy.api import estop, events, safety
from mtpy.api.errors import DeviceError, NotReady, SafetyRefused, Timeout
from mtpy.devices.sim import SimCamera

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
# TEST ONLY - not a rig value: every limit set and verified so the simulators can exercise every device function.
TEST_LIMITS = {"magnet_force_pN": (0.0, 20.0), "magnet_speed_mm_s": (0.0, 10.0), "rotor_turns": (-5.0, 5.0),
               "rotor_speed_turns_s": (0.0, 10.0), "focus_z_um": (-50.0, 50.0)}
# TEST ONLY - a clearly synthetic position-to-force table (no physics; decision 0010 needs a recorded one).
SYNTHETIC_TABLE = {"name": "synthetic test table", "version": "test", "position_mm": [0.0, 10.0, 20.0],
                   "force_pN": [0.1, 1.0, 10.0]}


def _config(tmp_path, monkeypatch, test_limits):
    shutil.copytree(REPO_CONFIG, tmp_path / "config")
    monkeypatch.setattr(safety, "CONFIG", tmp_path / "config")
    if test_limits:
        path = tmp_path / "config" / "safety_profile.json"
        p = json.loads(path.read_text(encoding="utf-8"))
        for q, (lo, hi) in TEST_LIMITS.items():
            p["limits"][q].update(min=lo, max=hi, verified=True, source="TEST ONLY")
        p["unverified"], p["by"] = [], "TEST ONLY (tests/test_devices.py)"
        path.write_text(json.dumps(p), encoding="utf-8")
    safety.load_active()


def _rig(tmp_path, monkeypatch, test_limits):
    _config(tmp_path, monkeypatch, test_limits)
    with events.as_caller("gui"):
        estop.clear()
        api.devices.connect({"backend": "sim"})
    yield {n: api.devices.service(n) for n in api.devices.status()}
    api.devices.disconnect()
    with events.as_caller("gui"):
        estop.clear()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A simulated rig on the TEST profile."""
    yield from _rig(tmp_path, monkeypatch, test_limits=True)


@pytest.fixture
def shipped_rig(tmp_path, monkeypatch):
    """A simulated rig on the shipped profile v1."""
    yield from _rig(tmp_path, monkeypatch, test_limits=False)


def _since(n):
    return events.events()[n:]


def test_moves_within_limits_read_back(rig):
    assert abs(api.magnet.move_to(2.0).wait(5) - 2.0) <= 0.01
    assert abs(api.magnet.position() - 2.0) <= 0.01
    assert api.rotor.rotate(1.5).wait(5) == pytest.approx(1.5, abs=0.002)
    assert api.focus.move_to(rig["focus"].origin + 10.0).wait(5) == pytest.approx(rig["focus"].origin + 10.0, abs=0.2)
    ox, oy = rig["stage"].origin
    x, y = api.stage.move_to(ox + 1.0, oy - 1.0).wait(5)
    assert abs(x - ox - 1.0) <= 0.0005 and abs(y - oy + 1.0) <= 0.0005


def test_refusal_outside_profile_names_range_and_moves_nothing(rig):
    n = len(events.events())
    with pytest.raises(SafetyRefused, match=r"\[0, 39\] mm"):
        api.magnet.move_to(40.0)                                  # refused at once, not only at wait()
    with pytest.raises(SafetyRefused, match=r"\[0, 10\] mm/s"):
        api.magnet.move_to(1.0, speed_mm_s=50.0)
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)
    assert [e.kind for e in _since(n)] == ["refused", "refused"]


def test_shipped_profile_refuses_rotor_and_focus(shipped_rig):
    with pytest.raises(SafetyRefused, match="not verified"):
        api.rotor.rotate(1.0)
    with pytest.raises(SafetyRefused, match="no limit set"):
        api.focus.move_to(1.0)
    with pytest.raises(SafetyRefused, match="no limit set"):
        api.magnet.move_to(1.0, speed_mm_s=1.0)


def test_controller_limit_stop_is_readback_mismatch(rig):
    stage = rig["stage"].device
    ox, oy = rig["stage"].origin
    stage.x.axis.travel = (-500.0, ox + 1.0)                      # an SU firmware limit inside the profile window
    m = api.stage.move_to(ox + 1.5, oy)
    with pytest.raises(DeviceError, match="not what was asked"):
        m.wait(5)


def test_nan_readback_and_no_reply_are_device_errors(rig):
    rig["magnet"].device.fault = "nan"
    with pytest.raises(DeviceError, match="not a finite number"):
        api.magnet.move_to(0.5).wait(5)
    rig["magnet"].device.fault = "no_reply"
    with pytest.raises(DeviceError, match="no reply.*PI controller"):
        api.magnet.position()
    st = api.devices.status()["magnet"]
    assert st["state"] == "error" and "PI controller" in st["last_error"]["hint"]
    rig["magnet"].device.fault = None
    api.devices.reconnect("magnet")
    assert api.devices.status()["magnet"]["state"] == "connected"


def test_estop_cancels_running_motion_and_blocks_new_ones(rig):
    rig["magnet"].device.axis.speed = 2.0
    m = api.magnet.move_to(5.0)
    time.sleep(0.2)
    n = len(events.events())
    estop.engage("test")
    with pytest.raises(NotReady, match="emergency stop"):
        m.wait(5)
    p = api.magnet.position()
    assert 0.1 < p < 2.0 and not rig["magnet"].device.moving()
    with pytest.raises(NotReady, match="emergency stop"):
        api.magnet.move_to(1.0)
    with pytest.raises(NotReady):
        api.light.set("532", True)
    assert "cancelled" in [e.kind for e in _since(n)]


def test_motion_cancel_and_wait_timeout(rig):
    rig["magnet"].device.axis.speed = 1.0
    m = api.magnet.move_to(5.0)
    with pytest.raises(Timeout):
        m.wait(0.05)
    assert not m.done
    m.cancel()
    with pytest.raises(NotReady, match="cancelled"):
        m.wait(5)


def test_caller_shown_from_worker_threads(rig):
    rig["magnet"].device.fault = None
    n = len(events.events())
    errors, seen = [], []

    def script():
        try:
            with events.as_caller("script:scan@1.0"):
                seen.append(rig["stage"].call(events.caller))           # what the service thread sees
                api.stage.move_to(*rig["stage"].origin).wait(5)
                rig["light"].device.fault = "no_reply"
                with pytest.raises(DeviceError):
                    api.light.set("532", True)
        except Exception as e:  # noqa: BLE001 - reported below
            errors.append(e)

    t = threading.Thread(target=script)
    with events.as_caller("gui"):
        t.start()
        api.magnet.move_to(1.0).wait(5)
    t.join(10)
    assert not errors and seen == ["script:scan@1.0"]
    acts = {e.request["quantity"]: e.caller for e in _since(n) if e.kind == "act"}
    assert acts == {"stage_xy_mm": "script:scan@1.0", "magnet_position_mm": "gui"}
    faults = [e for e in _since(n) if e.kind in ("device_fault", "device_error")]
    assert faults and all(e.caller == "script:scan@1.0" for e in faults)


def test_camera_preset_reapplied_after_reopen(rig):
    preset = {"name": "tracking 150 Hz", "rate_Hz": 150.0, "exposure_ms": 5.0, "gain_dB": 2.0,
              "roi": (0, 0, 640, 512)}
    got = api.camera.apply_preset(preset)
    assert got["rate_Hz"] == pytest.approx(149.9925, abs=1e-4) and got["roi"] == (0, 0, 640, 512)
    cam = rig["camera"].device
    cam.open()                                                    # the JAI resets on every open ...
    assert cam.get("roi") == (0, 0, 1280, 1024) and cam.get("exposure_ms") == 1.909
    api.devices.reconnect("camera")                               # ... so a reconnect re-applies the preset
    s = api.devices.info("camera")["settings"]
    assert s["roi"] == (0, 0, 640, 512) and s["exposure_ms"] == 5.0 and s["gain_dB"] == 2.0
    with pytest.raises(SafetyRefused, match="frame period"):
        api.camera.apply_preset({"name": "bad", "rate_Hz": 200.0, "exposure_ms": 6.0})


def test_camera_preset_mismatch_is_device_error(rig, monkeypatch):
    cam = rig["camera"].device
    real_set = cam.set
    monkeypatch.setattr(cam, "set", lambda k, v: real_set(k, v * 0.5 if k == "gain_dB" else v))
    with pytest.raises(DeviceError, match="not what was asked"):
        api.camera.apply_preset({"name": "g", "gain_dB": 4.0})


def test_rate_change_pauses_and_restarts_with_readback(rig):
    cam = rig["camera"].device
    cam.start_acquisition()
    assert cam.next_frame(2.0) is not None
    n = len(events.events())
    assert api.camera.set_rate(150.0) == pytest.approx(149.9925, abs=1e-4)
    kinds = [(e.kind, e.extra.get("action")) for e in _since(n)]
    assert kinds == [("acquisition", "pause"), ("act", None), ("acquisition", "restart")]
    assert cam.acquiring() and cam.next_frame(2.0).buffer_number == 0      # IMAQdx restarts buffer numbers
    assert api.camera.set_exposure(4.0) == 4.0                            # immediate: no pause
    rig["camera"].recording = True
    with pytest.raises(SafetyRefused, match="confirm=True"):
        api.camera.set_roi(0, 0, 640, 512)
    assert api.camera.set_roi(0, 0, 640, 512, confirm=True) == (0, 0, 640, 512)
    assert "guarded_change" in [e.kind for e in _since(n)]
    with pytest.raises(SafetyRefused, match="step 8"):
        api.camera.set_roi(0, 0, 641, 512, confirm=True)
    assert cam.next_frame(2.0).image.shape == (512, 640)
    cam.stop_acquisition()


def test_camera_drop_and_stall_injection():
    cam = SimCamera()                                             # no fixture -> synthetic rings
    cam.open()
    cam.set("rate_Hz", 200.0)
    cam.drop_every = 3
    cam.start_acquisition()
    got = [cam.next_frame(2.0) for _ in range(6)]
    cam.stall(0.2)
    later = [cam.next_frame(2.0) for _ in range(4)]
    cam.stop_acquisition()
    nums = [f.buffer_number for f in got]
    assert nums == [0, 1, 3, 4, 6, 7] and got[0].image.shape == (1024, 1280) and got[0].image.dtype == np.uint8
    gaps = np.diff([f.t_camera_s for f in later])
    assert max(gaps) >= 0.15                                      # a stall shows as a jump in camera time


def test_camera_replays_fixture_frames():
    from conftest import FIXTURE, need, read_image
    need(FIXTURE / "img00004.tif")
    cam = SimCamera(FIXTURE)
    cam.open()
    cam.start_acquisition()
    f = cam.next_frame(5.0)
    cam.stop_acquisition()
    assert f.image.shape == (1024, 1280) and np.array_equal(f.image, read_image(4).astype(np.uint8))


def test_relative_windows_use_session_start_origin(rig):
    ox, oy = rig["stage"].origin
    api.stage.move_to(ox + 1.9, oy).wait(5)
    with pytest.raises(SafetyRefused, match=r"session_start"):
        api.stage.move_to(ox + 2.1, oy)                           # only 0.2 mm from here, but outside start +- 2
    api.devices.reconnect("stage")
    assert rig["stage"].origin == (ox, oy)                        # kept for the whole session
    api.rotor.rotate(4.0).wait(5)
    with pytest.raises(SafetyRefused, match=r"\[-5, 5\] turns"):
        api.rotor.rotate(2.0)                                     # target 6 turns from the start


def test_self_check_report(rig):
    report = api.devices.self_check()
    assert set(report) == {"camera", "magnet", "rotor", "stage", "focus", "arduino", "light"}
    assert all(r["ok"] for steps in report.values() for r in steps)
    rig["rotor"].device.fault = "no_reply"
    steps = api.devices.self_check()["rotor"]
    assert [s["step"] for s in steps] == ["open", "reply"] and not steps[-1]["ok"]
    assert "rotor driver" in steps[-1]["detail"]


def test_arduino_divider_records_gating_per_frame(rig):
    assert api.sync.set_ratio(3) == 3
    ard = rig["arduino"].device
    api.light.set("532", True)
    for b in range(6):
        ard.on_jai_frame(b)
    api.light.set("637", True)
    for b in range(6, 9):
        ard.on_jai_frame(b)
    assert list(ard.frames) == [(0, 0, ("532",)), (1, 3, ("532",)), (2, 6, ("532", "637"))]
    with pytest.raises(SafetyRefused, match=r"\[1, 65536\]"):
        api.sync.set_ratio(0)
    with pytest.raises(SafetyRefused, match="laser"):
        api.light.set("488", True)


def test_set_force_needs_a_table(rig):
    with pytest.raises(NotReady, match="force table"):
        api.magnet.set_force(1.0)
    api.magnet.use_force_table(SYNTHETIC_TABLE)
    assert api.magnet.set_force(1.0).wait(5) == pytest.approx(10.0, abs=0.01)
    assert api.devices.info("magnet")["calibration"]["force_table"]["name"] == "synthetic test table"
    with pytest.raises(SafetyRefused, match="range"):
        api.magnet.set_force(15.0)


def test_real_backend_not_implemented_and_not_connected():
    with pytest.raises(NotImplementedError, match="phases 6/7"):
        api.devices.connect({"backend": "real"})
    with pytest.raises(NotReady, match="connect"):
        api.magnet.position()
