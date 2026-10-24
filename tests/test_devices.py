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


def _config(tmp_path, monkeypatch, test_limits, profile_version=None):
    """A copy of the shipped config in tmp_path. profile_version: make that history version the active profile
    (e.g. 1, to check that v1 still refuses every magnet move after v2 was shipped, decision 0016)."""
    shutil.copytree(REPO_CONFIG, tmp_path / "config")
    monkeypatch.setattr(safety, "CONFIG", tmp_path / "config")
    if profile_version is not None:
        src = tmp_path / "config" / "safety_profiles" / f"{profile_version}.json"
        (tmp_path / "config" / "safety_profile.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    if test_limits:
        path = tmp_path / "config" / "safety_profile.json"
        p = json.loads(path.read_text(encoding="utf-8"))
        for q, (lo, hi) in TEST_LIMITS.items():
            p["limits"][q].update(min=lo, max=hi, verified=True, source="TEST ONLY")
        p["unverified"], p["by"] = [], "TEST ONLY (tests/test_devices.py)"
        path.write_text(json.dumps(p), encoding="utf-8")
    safety.load_active()


def _rig(tmp_path, monkeypatch, test_limits, profile_version=None):
    _config(tmp_path, monkeypatch, test_limits, profile_version)
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
    """A simulated rig on the shipped profile (v4: magnet speed max 15 mm/s, verified by the rig check 2026-10-25)."""
    yield from _rig(tmp_path, monkeypatch, test_limits=False)


@pytest.fixture
def v1_rig(tmp_path, monkeypatch):
    """A simulated rig on profile v1 (no magnet speed maximum), taken from the history."""
    yield from _rig(tmp_path, monkeypatch, test_limits=False, profile_version=1)


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


def test_shipped_profile_v4_magnet_moves_up_to_15_mm_s_rotor_focus_force_refused(shipped_rig):
    """Shipped profile v4 (rig check 2026-10-25): a magnet POSITION move at <= 15 mm/s (given or read back) runs in
    the simulator; > 15 mm/s is refused and nothing moves; rotor, focus and force are still refused."""
    assert safety.profile()["version"] == 4
    with pytest.raises(SafetyRefused, match="not verified"):
        api.rotor.rotate(1.0)
    with pytest.raises(SafetyRefused, match="no limit set"):
        api.focus.move_to(1.0)
    api.magnet.use_force_table({"name": "t", "version": "test", "position_mm": [0.0, 20.0], "force_pN": [0.1, 10.0]})
    with pytest.raises(SafetyRefused, match="magnet_force_pN has no limit set"):
        api.magnet.set_force(1.0)
    for speed in (15.5, 16.0):
        with pytest.raises(SafetyRefused, match=r"magnet_speed_mm_s .* outside the allowed range \[0, 15\]"):
            api.magnet.move_to(1.0, speed_mm_s=speed)
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01) and not shipped_rig["magnet"].device.moving()
    assert api.magnet.move_to(1.0, speed_mm_s=15.0).wait(5) == pytest.approx(1.0, abs=0.01)
    n = len(events.events())
    assert api.magnet.move_to(2.0).wait(5) == pytest.approx(2.0, abs=0.01)   # omitted: VEL? read back and checked
    assert [e.kind for e in _since(n) if e.kind in ("act", "refused", "unverified-limit")] == ["act"]


def test_profile_v3_still_refuses_every_magnet_move(tmp_path, monkeypatch):
    """v3 from the history (speed 15 mm/s verified:false) still refuses every magnet move, also at 10 and 15 mm/s."""
    gen = _rig(tmp_path, monkeypatch, test_limits=False, profile_version=3)
    rig = next(gen)
    try:
        assert safety.profile()["version"] == 3
        for speed in (10.0, 15.0, 16.0):
            with pytest.raises(SafetyRefused, match=r"magnet_speed_mm_s limit \[0, 15\] mm/s is not verified"):
                api.magnet.move_to(1.0, speed_mm_s=speed)
        n = len(events.events())
        with pytest.raises(SafetyRefused, match="not verified"):
            api.magnet.move_to(1.0)               # omitted speed: read back (VEL?) and checked, refused
        assert "omitted" in _since(n)[-1].request["source"]
        assert api.magnet.position() == pytest.approx(0.0, abs=0.01) and not rig["magnet"].device.moving()
    finally:
        next(gen, None)


def test_profile_v1_still_refuses_every_magnet_move(v1_rig):
    assert safety.profile()["version"] == 1
    with pytest.raises(SafetyRefused, match="no limit set"):
        api.magnet.move_to(1.0, speed_mm_s=1.0)
    n = len(events.events())
    with pytest.raises(SafetyRefused, match="magnet_speed_mm_s has no limit set"):
        api.magnet.move_to(1.0)                   # omitted speed: still checked, so v1 refuses every magnet move
    ev = _since(n)[-1]
    assert ev.kind == "refused" and ev.request["value"] == 10.0 and "omitted" in ev.request["source"]
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)


def test_omitted_speed_is_read_back_and_checked(rig):
    """Review l2s-wp2-r1: an omitted speed is the controller's current speed, read back and checked, then sent."""
    dev = rig["magnet"].device
    dev.axis.speed = 50.0                         # outside the TEST limit [0, 10] mm/s
    with pytest.raises(SafetyRefused, match=r"magnet_speed_mm_s 50 mm/s is outside.*\[0, 10\] mm/s"):
        api.magnet.move_to(1.0)
    assert not dev.moving()
    dev.axis.speed = 8.0
    assert api.magnet.move_to(1.0).wait(5) == pytest.approx(1.0, abs=0.01)
    assert dev.axis.speed == 8.0                  # the checked speed is the one applied


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


# --- review l2s-wp2-r1: stop order and the send window ---------------------------------------------------------------

def test_estop_stops_everything_before_events_slow_subscriber_failing_stopper():
    order = []

    def bad_stop():
        order.append("stop bad")
        raise RuntimeError("port gone")

    def good_stop():
        order.append("stop good")

    def slow_subscriber(ev):
        order.append(f"event {ev.kind}")
        time.sleep(0.2)                           # a slow subscriber must not delay any stop

    removes = [estop.add_stopper(bad_stop), estop.add_stopper(good_stop)]
    unsub = events.subscribe(slow_subscriber)
    g = estop.generation()
    try:
        estop.engage("test")
        assert estop.active() and estop.generation() == g + 1
    finally:
        unsub()
        for r in removes:
            r()
        with events.as_caller("gui"):
            estop.clear()
    assert order[:2] == ["stop bad", "stop good"]
    assert order[2:] == ["event estop", "event estop_error"]
    err = [e for e in events.events() if e.kind == "estop_error"][-1]
    assert "bad_stop" in err.extra["stopper"] and "port gone" in err.extra["error"]


def _blocked_send(monkeypatch, dev):
    """Make dev.move_to wait inside the send (on the service thread) until `release` is set."""
    entered, release = threading.Event(), threading.Event()
    real = dev.move_to

    def slow(target, speed=None):
        entered.set()
        release.wait(5)
        real(target, speed)
    monkeypatch.setattr(dev, "move_to", slow)
    return entered, release


def _no_act(n, quantity):
    kinds = [e.kind for e in _since(n) if isinstance(e.request, dict) and e.request.get("quantity") == quantity]
    return "act" not in kinds and "cancelled" in kinds


def test_engage_and_clear_while_send_waits_stops_again(rig, monkeypatch):
    dev = rig["magnet"].device
    dev.axis.speed = 1.0
    entered, release = _blocked_send(monkeypatch, dev)
    n = len(events.events())
    m = api.magnet.move_to(5.0, speed_mm_s=1.0)
    assert entered.wait(2)
    estop.engage("test")
    with events.as_caller("gui"):
        estop.clear()                             # released before the send even returns
    release.set()                                 # the move is applied now ... and must be stopped again
    with pytest.raises(NotReady, match="emergency stop"):
        m.wait(5)
    assert not dev.moving() and api.magnet.position() < 0.1
    assert _no_act(n, "magnet_position_mm")


def test_cancel_while_send_waits_stops_again(rig, monkeypatch):
    dev = rig["magnet"].device
    entered, release = _blocked_send(monkeypatch, dev)
    n = len(events.events())
    m = api.magnet.move_to(5.0, speed_mm_s=1.0)
    assert entered.wait(2)
    t0 = time.monotonic()
    m.cancel()                                    # the service thread is busy in the send: cancel must not queue
    assert time.monotonic() - t0 < 0.2
    release.set()
    with pytest.raises(NotReady, match="cancelled"):
        m.wait(5)
    assert not dev.moving() and api.magnet.position() < 0.1
    assert _no_act(n, "magnet_position_mm")


def test_cancel_stops_at_once_while_the_queue_is_blocked(rig):
    svc, dev = rig["magnet"], rig["magnet"].device
    m = api.magnet.move_to(5.0, speed_mm_s=1.0)
    time.sleep(0.2)
    assert dev.axis.moving()
    entered, release = threading.Event(), threading.Event()

    def blocker():
        entered.set()
        release.wait(5)
    t = threading.Thread(target=lambda: svc.call(blocker, what="long command", timeout_s=6))
    t.start()
    try:
        assert entered.wait(2)
        t0 = time.monotonic()
        m.cancel()
        assert time.monotonic() - t0 < 0.2 and not dev.axis.moving()     # stopped without the queue
    finally:
        release.set()
        t.join(7)
    with pytest.raises(NotReady, match="cancelled"):
        m.wait(5)


def test_requests_made_before_estop_never_run_after_clear(rig):
    light, magnet = rig["light"], rig["magnet"]
    entered = {s.name: threading.Event() for s in (light, magnet)}     # per device (re-review l2s-wp2-r2)
    release = threading.Event()

    def blocker(name):
        entered[name].set()
        release.wait(5)
    blockers = [threading.Thread(target=lambda s=s: s.call(blocker, s.name, what="long command", timeout_s=6))
                for s in (light, magnet)]
    errors = []

    def set_light():
        try:
            api.light.set("532", True)
        except Exception as e:  # noqa: BLE001 - checked below
            errors.append(e)
    n = len(events.events())
    for b in blockers:
        b.start()
    try:
        assert all(e.wait(2) for e in entered.values())             # BOTH service threads are blocked
        lt = threading.Thread(target=set_light)
        lt.start()
        m = api.magnet.move_to(5.0, speed_mm_s=1.0)
        t_end = time.monotonic() + 2
        while light._q.qsize() < 1 and time.monotonic() < t_end:     # the light send is queued behind the blocker
            time.sleep(0.005)
        assert light._q.qsize() >= 1
        estop.engage("test")
        with events.as_caller("gui"):
            estop.clear()
    finally:
        release.set()
        for b in blockers:
            b.join(7)
    lt.join(7)
    with pytest.raises(NotReady, match="emergency stop"):
        m.wait(5)
    assert len(errors) == 1 and isinstance(errors[0], NotReady)
    assert light.device.outputs_dict()["532"] is False                      # never sent
    assert magnet.device.position() == pytest.approx(0.0, abs=0.01)         # never moved
    assert _no_act(n, "light_532") and _no_act(n, "magnet_position_mm")


# --- re-review l2s-wp2-r2: generation recorded before the pre-reads; void check after a send that raised -------------

def _blocked_once(monkeypatch, dev, attr):
    """Make the FIRST dev.<attr>() call wait (on the service thread) until `release` is set; later calls are real."""
    entered, release = threading.Event(), threading.Event()
    real = getattr(dev, attr)

    def slow(*a):
        if not entered.is_set():
            entered.set()
            release.wait(5)
        return real(*a)
    monkeypatch.setattr(dev, attr, slow)
    return entered, release


def _engage_clear_during_preread(monkeypatch, dev, attr, start):
    """Run start() (a public move call) in a thread; engage and clear the stop while its pre-read dev.<attr>() waits.
    Returns what start() returned or raised."""
    entered, release = _blocked_once(monkeypatch, dev, attr)
    out = []

    def run():
        try:
            out.append(start())
        except Exception as e:  # noqa: BLE001 - checked by the caller
            out.append(e)
    t = threading.Thread(target=run)
    t.start()
    try:
        assert entered.wait(2)
        estop.engage("test")
        with events.as_caller("gui"):
            estop.clear()                         # released again before the pre-read returns
    finally:
        release.set()
        t.join(5)
    assert len(out) == 1
    return out[0]


def test_engage_clear_during_magnet_speed_preread_voids_the_move(rig, monkeypatch):
    dev = rig["magnet"].device
    n = len(events.events())
    got = _engage_clear_during_preread(monkeypatch, dev, "speed", lambda: api.magnet.move_to(5.0))
    assert isinstance(got, NotReady) and "emergency stop" in str(got)
    assert not dev.moving() and dev.position() == pytest.approx(0.0, abs=0.01)
    assert "act" not in [e.kind for e in _since(n)]


def test_engage_clear_during_rotor_position_preread_voids_the_move(rig, monkeypatch):
    dev = rig["rotor"].device
    p0 = dev.position()
    n = len(events.events())
    got = _engage_clear_during_preread(monkeypatch, dev, "position", lambda: api.rotor.rotate(1.0))
    assert isinstance(got, NotReady) and "emergency stop" in str(got)
    assert not dev.moving() and dev.position() == pytest.approx(p0, abs=0.002)
    assert "act" not in [e.kind for e in _since(n)]


def _send_applies_then_raises(monkeypatch, dev):
    """dev.move_to waits until `release`, then APPLIES the move and raises (a reply lost after the command went out)."""
    entered, release = threading.Event(), threading.Event()
    real = dev.move_to

    def applies_then_raises(target, speed=None):
        entered.set()
        release.wait(5)
        real(target, speed)
        raise RuntimeError("reply lost after the move was applied")
    monkeypatch.setattr(dev, "move_to", applies_then_raises)
    return entered, release


@pytest.mark.parametrize("void_by", ["engage_clear", "cancel"])
def test_voided_send_that_raised_is_stopped_again_and_cancelled(rig, monkeypatch, void_by):
    svc, dev = rig["magnet"], rig["magnet"].device
    entered, release = _send_applies_then_raises(monkeypatch, dev)
    n = len(events.events())
    m = api.magnet.move_to(5.0, speed_mm_s=1.0)
    assert entered.wait(2)
    if void_by == "cancel":
        m.cancel()
    else:
        estop.engage("test")
        with events.as_caller("gui"):
            estop.clear()
    release.set()                                 # the move is applied now, then the send raises
    with pytest.raises(NotReady, match="emergency stop" if void_by == "engage_clear" else "cancelled") as ei:
        m.wait(5)
    assert isinstance(ei.value.__cause__, RuntimeError)                # the original send exception is the cause
    assert not dev.moving() and dev.position() < 0.1                  # stopped again on the device thread
    assert _no_act(n, "magnet_position_mm")
    kinds = [e.kind for e in _since(n)]
    assert "device_error" not in kinds and "estop_error" not in kinds
    fault = [e for e in _since(n) if e.kind == "device_fault"]
    assert len(fault) == 1 and "reply lost" in fault[0].extra["hint"] and fault[0].extra["voided"]
    assert svc.status()["state"] != "error"


def test_send_that_raised_and_is_not_void_is_a_device_error(rig, monkeypatch):
    dev = rig["magnet"].device
    _entered, release = _send_applies_then_raises(monkeypatch, dev)
    release.set()
    with pytest.raises(DeviceError, match="reply lost"):
        api.magnet.move_to(5.0, speed_mm_s=1.0).wait(5)
    dev.stop()


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


def test_arduino_divider_count_reset_rule(rig):
    """Review l2s-wp2-r1: the divider counts its own pulses; reset on open and on set_ratio only, so frame m covers
    its pulses [mN, (m+1)N) whatever the camera's buffer numbers do."""
    ard = rig["arduino"].device
    api.sync.set_ratio(2)
    for b in (0, 1, 2, 3, 4):
        ard.on_jai_frame(b)
    for b in (0, 1):                              # camera acquisition restarted: buffers restart, the count does not
        ard.on_jai_frame(b)
    assert ard.pulses == 7
    assert [(m, b) for m, b, _ in ard.frames] == [(0, 0), (1, 2), (2, 4), (3, 1)]
    api.sync.set_ratio(2)                         # configuring N starts a new count
    assert ard.pulses == 0
    ard.on_jai_frame(7)
    assert list(ard.frames)[-1][:2] == (0, 7)
    api.devices.reconnect("arduino")              # opening the port resets the board: count, ratio and records
    assert ard.pulses == 0 and ard.ratio == 1 and not ard.frames


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
