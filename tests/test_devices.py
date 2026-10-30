"""WP2: device services, simulators and the device functions of the public API (no hardware, no G: data needed)."""
import json
import os
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
TEST_LIMITS = {"magnet_speed_mm_s": (0.0, 10.0), "rotor_turns": (-5.0, 5.0),
               "rotor_speed_turns_s": (0.0, 10.0), "focus_z_um": (-50.0, 50.0)}
# TEST ONLY - a clearly synthetic position-to-force table (no physics; decision 0010 needs a recorded one).
SYNTHETIC_TABLE = {"name": "synthetic test table", "version": "test", "position_mm": [0.0, 10.0, 20.0],
                   "force_pN": [0.1, 1.0, 10.0]}
# TEST ONLY - synthetic tables that reach past the magnet position limit [0, 39] mm (decision 0017).
WIDE_TABLE = {"name": "wide test table", "version": "test", "position_mm": [0.0, 20.0, 45.0],
              "force_pN": [0.1, 1.0, 30.0]}            # 39 mm -> 1 + 29 * 19 / 25 = 23.04 pN
BELOW_TABLE = {"name": "below-zero test table", "version": "test", "position_mm": [-5.0, 20.0],
               "force_pN": [0.05, 10.0]}               # 0 mm -> 0.05 + 9.95 * 5 / 25 = 2.04 pN


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
            if q == "focus_z_um":                 # v6 is absolute (0025); the tests keep the session-relative window
                p["limits"][q]["relative_to"] = "session_start"
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
    """A simulated rig on the shipped profile (v5: magnet position [0, 39] mm and speed max 15 mm/s verified, no force
    limit - decision 0017)."""
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


def test_speed_outside_profile_refused_and_moves_nothing(rig):
    """The speed is still refused outside the profile (decision 0018 changes positions and forces, not speeds); a
    position that is not a finite number is refused too."""
    n = len(events.events())
    with pytest.raises(SafetyRefused, match=r"\[0, 10\] mm/s"):
        api.magnet.move_to(1.0, speed_mm_s=50.0)                  # refused at once, not only at wait()
    with pytest.raises(SafetyRefused, match="not a finite number"):
        api.magnet.move_to(float("nan"))
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)
    assert [e.kind for e in _since(n)] == ["refused", "refused"]


@pytest.mark.parametrize("requested, applied", [(45.0, 39.0), (-3.0, 0.0)])
def test_direct_position_outside_the_limit_is_coerced_to_the_nearest_limit(rig, requested, applied):
    """Decision 0018 item 5: no alarm, no refusal; the applied value is returned (for the GUI field), logged as a
    `coerced` event with requested / applied / reason, and is the position the magnet moves to."""
    if applied == 0.0:
        api.magnet.move_to(5.0).wait(5)
    n = len(events.events())
    m = api.magnet.move_to(requested)
    assert (m.requested_mm, m.applied_mm, m.coerced) == (requested, applied, True)
    assert m.wait(10) == pytest.approx(applied, abs=0.01)
    ev = [e for e in _since(n) if e.kind in ("coerced", "act", "refused")]
    assert [e.kind for e in ev] == ["coerced", "act"]
    assert ev[0].request == {"quantity": "magnet_position_mm", "value": requested} and ev[0].extra["applied"] == applied
    assert "nearest limit" in ev[0].extra["reason"] and "[0, 39] mm" in ev[0].extra["reason"]
    assert ev[1].request["value"] == applied
    m = api.magnet.move_to(applied)                               # inside: no coercion, no event
    assert m.coerced is False and m.wait(5) == pytest.approx(applied, abs=0.01)


def test_last_step_coerces_whatever_the_caller_computed(rig):
    """Decision 0018 item 4: the final send coerces into 0..39 mm even when every earlier step is bypassed."""
    svc = rig["magnet"]
    n = len(events.events())
    api.magnet._send(svc, svc.device, 45.0, 10.0)                 # a deliberately bad internal value
    _wait_still(svc)
    assert api.magnet.position() == pytest.approx(39.0, abs=0.01)
    ev = [e for e in _since(n) if e.kind == "coerced"]
    assert len(ev) == 1 and ev[0].extra["stage"] == "send" and ev[0].extra["applied"] == 39.0
    api.magnet._send(svc, svc.device, -2.5, 10.0)
    _wait_still(svc)
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)
    with pytest.raises(SafetyRefused, match="not a finite number"):
        api.magnet._send(svc, svc.device, float("inf"), 10.0)


def _wait_still(svc, timeout_s=10.0):
    t_end = time.monotonic() + timeout_s
    time.sleep(0.05)
    while svc.device.moving() and time.monotonic() < t_end:
        time.sleep(0.02)


@pytest.fixture(params=[None, 4], ids=["shipped_v5", "history_v4"])
def v4_or_v5_rig(request, tmp_path, monkeypatch):
    """The shipped profile (v5) and v4 from the history: the same magnet position and speed limits."""
    yield from _rig(tmp_path, monkeypatch, test_limits=False, profile_version=request.param)


def test_profiles_v4_and_v5_magnet_position_moves_up_to_15_mm_s_rotor_focus_refused(v4_or_v5_rig):
    """Profiles v4 (rig check 2026-10-25) and v5 (decision 0017, same position and speed limits): a magnet POSITION
    move at <= 15 mm/s (given or read back) runs in the simulator; > 15 mm/s is refused and nothing moves; > 39 mm is
    coerced to 39 mm (decision 0018 item 5); the rotor is still refused (unverified); focus unset before v6."""
    assert safety.profile()["version"] in (4, 5, 6, 7)
    if safety.profile()["version"] < 7:
        with pytest.raises(SafetyRefused, match="not verified"):
            api.rotor.rotate(1.0)
    else:                                       # v7: rotor window +-5 turns verified on the rig 2026-10-30
        with pytest.raises(SafetyRefused, match="outside the allowed range"):
            api.rotor.rotate(6.0)
    if safety.profile()["version"] < 6:
        with pytest.raises(SafetyRefused, match="no limit set"):
            api.focus.move_to(1.0)
    else:                                       # v6 (decision 0025): focus window +-75 um from the ASI controller
        with pytest.raises(SafetyRefused, match="outside the allowed range"):
            api.focus.move_to(80.0)
    for speed in (15.5, 16.0):
        with pytest.raises(SafetyRefused, match=r"magnet_speed_mm_s .* outside the allowed range \[0, 15\]"):
            api.magnet.move_to(1.0, speed_mm_s=speed)
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01) and not v4_or_v5_rig["magnet"].device.moving()
    m = api.magnet.move_to(39.5, speed_mm_s=15.0)
    assert m.applied_mm == 39.0 and m.wait(10) == pytest.approx(39.0, abs=0.01)
    assert api.magnet.move_to(1.0, speed_mm_s=15.0).wait(5) == pytest.approx(1.0, abs=0.01)
    n = len(events.events())
    assert api.magnet.move_to(2.0).wait(5) == pytest.approx(2.0, abs=0.01)   # omitted: VEL? read back and checked
    assert [e.kind for e in _since(n) if e.kind in ("act", "refused", "unverified-limit")] == ["act"]


def test_shipped_v5_force_inside_the_reachable_range_runs(shipped_rig):
    """Decision 0017 on the shipped v5: a force is converted through the table to a position inside [0, 39] mm and
    runs; the reachable range of a table that ends inside the limit is the table's own range."""
    assert safety.profile()["version"] == 7 and "magnet_force_pN" not in safety.profile()["limits"]
    api.magnet.use_force_table(SYNTHETIC_TABLE)
    r = api.magnet.force_range()
    assert r["force_pN"] == (0.1, 10.0) and r["position_mm"] == (0.0, 20.0) and r["position_limit_mm"] == (0.0, 39.0)
    assert r["limited_by"] == ("position limit", "table end") and r["profile_version"] == 7
    assert r["table"] == "synthetic test table"
    n = len(events.events())
    assert api.magnet.set_force(1.0).wait(5) == pytest.approx(10.0, abs=0.01)
    assert [e.kind for e in _since(n) if e.kind in ("force_request", "act", "refused")] == ["force_request", "act"]
    assert api.magnet.force_position(5.5) == pytest.approx(15.0)


def test_table_force_above_the_reachable_range_is_coerced_to_the_limit_end(shipped_rig):
    """Decision 0018 with a table (the swappable alternative): 25 pN needs 40.69 mm -> 23.04 pN at 39 mm; returned,
    logged as `coerced`, and moved to. 31 pN (beyond the table itself) -> the same."""
    api.magnet.use_force_table(WIDE_TABLE)
    r = api.magnet.force_range()
    assert r["force_pN"][0] == pytest.approx(0.1) and r["force_pN"][1] == pytest.approx(23.04)
    assert r["position_mm"] == (0.0, 39.0) and r["limited_by"] == ("position limit", "position limit")
    n = len(events.events())
    m = api.magnet.set_force(25.0)
    assert m.requested_pN == 25.0 and m.applied_pN == pytest.approx(23.04) and m.coerced and m.position_mm == 39.0
    assert m.wait(10) == pytest.approx(39.0, abs=0.01)
    ev = [x for x in _since(n) if x.kind in ("coerced", "force_request", "act", "refused")]
    assert [x.kind for x in ev] == ["coerced", "force_request", "act"]
    c = ev[0]
    assert c.request["value"] == 25.0 and c.extra["applied"] == pytest.approx(23.04)
    assert c.extra["calibration"] == "wide test table" and c.extra["position_mm"] == 39.0
    assert "above the reachable range [0.1, 23.04] pN" in c.extra["reason"]
    assert "set to 23.04 pN at the position limit (39 mm)" in c.extra["reason"] and "rig safety profile v7" in c.extra["reason"]
    assert api.magnet.coerce_force(31.0)["applied_pN"] == pytest.approx(23.04)
    m = api.magnet.set_force(23.0)
    assert not m.coerced and m.wait(10) == pytest.approx(20 + 25 * 22 / 29, abs=0.01)


def test_table_force_below_the_reachable_range_is_coerced_to_the_limit_end(shipped_rig):
    api.magnet.use_force_table(BELOW_TABLE)
    r = api.magnet.force_range()
    assert r["force_pN"][0] == pytest.approx(2.04) and r["force_pN"][1] == pytest.approx(10.0)
    assert r["position_mm"] == (0.0, 20.0) and r["limited_by"] == ("position limit", "table end")
    api.magnet.move_to(5.0).wait(5)
    m = api.magnet.set_force(1.0)
    assert m.applied_pN == pytest.approx(2.04) and m.coerced and m.position_mm == 0.0
    assert m.wait(10) == pytest.approx(0.0, abs=0.01)
    assert api.magnet.coerce_force(1.0)["reason"].startswith("magnet force 1 pN is below the reachable range")


def test_changing_the_force_table_changes_the_reachable_range_not_the_profile(shipped_rig):
    v = safety.profile()["version"]
    api.magnet.use_force_table(SYNTHETIC_TABLE)
    narrow = api.magnet.force_range()["force_pN"]
    api.magnet.use_force_table(WIDE_TABLE)
    wide = api.magnet.force_range()["force_pN"]
    assert narrow == (0.1, 10.0) and wide[1] == pytest.approx(23.04) and safety.profile()["version"] == v
    assert api.magnet.force_range(SYNTHETIC_TABLE)["force_pN"] == narrow       # a table for one call
    m = api.magnet.set_force(15.0)                                              # 15 pN is reachable with WIDE only
    assert not m.coerced and m.wait(10) > 20.0
    m = api.magnet.set_force(15.0, table=SYNTHETIC_TABLE)
    assert m.coerced and m.applied_pN == 10.0 and m.wait(10) == pytest.approx(20.0, abs=0.01)


def test_default_calibration_is_the_live_equation_and_needs_the_touch_position(shipped_rig):
    cal = api.magnet.force_calibration()
    assert cal["name"] == "M270 v3 (LabVIEW Magnet2Force v3, case 1)" and cal["kind"] == "equation"
    assert not cal["ready"] and cal["touch_mm"] is None and api.magnet.force_table() is None
    for call in (lambda: api.magnet.set_force(1.0), api.magnet.force_range, lambda: api.magnet.force_position(1.0),
                 lambda: api.magnet.force_at(10.0)):
        with pytest.raises(NotReady, match="needs the touch position"):
            call()
    assert api.magnet.live_force(10.0) is None
    with pytest.raises(SafetyRefused, match="position strictly monotonic"):
        api.magnet.use_force_table({**SYNTHETIC_TABLE, "position_mm": [0.0, 20.0, 10.0]})
    with pytest.raises(SafetyRefused, match="not a finite number"):
        api.magnet.set_touch_position(float("nan"))
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)


def _f(d):
    return 48.8162 * np.exp(-d / 1.13483) + 22.8394 * np.exp(-d / 3.68428) - 0.45845


def test_equation_force_coerced_above_and_below_and_touch_changes_the_range(shipped_rig):
    """Decision 0018 with the default equation: the reachable range is [F(0 mm), F(39 mm)] for the touch position;
    too high -> F(39 mm) at 39 mm, too low -> F(0 mm) at 0 mm; a different touch gives a different range."""
    api.magnet.set_touch_position(40.0)
    r = api.magnet.force_range()
    assert r["force_pN"] == pytest.approx((_f(40.0), _f(1.0)), rel=1e-12) and r["position_mm"] == (0.0, 39.0)
    assert r["touch_mm"] == 40.0 and r["touch_beyond_limit"] is False and r["kind"] == "equation"
    assert api.magnet.force_calibration()["ready"] and api.magnet.force_at(39.0) == pytest.approx(_f(1.0), rel=1e-12)
    n = len(events.events())
    m = api.magnet.set_force(100.0)
    assert m.coerced and m.applied_pN == pytest.approx(_f(1.0), rel=1e-12) and m.position_mm == 39.0
    assert m.wait(10) == pytest.approx(39.0, abs=0.01)
    c = [x for x in _since(n) if x.kind == "coerced"]
    assert len(c) == 1 and c[0].extra["touch_mm"] == 40.0 and c[0].extra["calibration"].startswith("M270 v3")
    assert "at touch 40 mm" in c[0].extra["reason"]
    m = api.magnet.set_force(10.0)                                 # inside: position by the live inverse
    assert not m.coerced and _f(40.0 - m.position_mm) == pytest.approx(10.0, abs=1e-8)
    assert m.wait(10) == pytest.approx(m.position_mm, abs=0.01)
    api.magnet.set_touch_position(45.0)
    assert api.magnet.force_range()["force_pN"][1] == pytest.approx(_f(6.0), rel=1e-12)     # range follows touch
    api.magnet.set_touch_position(10.0)                            # F(0 mm) = F(d = 10) ~ 1.06 pN
    m = api.magnet.set_force(0.5)
    assert m.coerced and m.applied_pN == pytest.approx(_f(10.0), rel=1e-12) and m.position_mm == 0.0
    assert m.wait(10) == pytest.approx(0.0, abs=0.01)
    assert api.magnet.force_range()["touch_beyond_limit"] is True   # open point: touch inside the travel


class _BadCalibration:
    """TEST ONLY: F = position, but the inverse returns a position outside the limit (a deliberately bad value)."""
    name, kind, needs_touch = "TEST ONLY bad inverse", "equation", False

    def domain(self):
        return (-np.inf, np.inf)

    def force(self, p, touch=None):
        return float(p)

    def position(self, f, lo, hi, touch=None):
        return 45.0

    def describe(self, touch=None):
        return {"name": self.name}


def test_bad_internal_position_from_a_calibration_is_still_coerced(shipped_rig):
    n = len(events.events())
    m = api.magnet.set_force(10.0, table=_BadCalibration())
    assert m.applied_mm == 39.0 and m.wait(10) == pytest.approx(39.0, abs=0.01)
    assert any(x.kind == "coerced" and x.request["quantity"] == "magnet_position_mm" for x in _since(n))


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
    assert set(report) == {"camera", "magnet", "rotor", "stage", "focus", "arduino", "light", "emccd"}
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


def test_set_force_needs_a_ready_calibration(rig):
    with pytest.raises(NotReady, match="touch position"):
        api.magnet.set_force(1.0)
    api.magnet.use_force_table(SYNTHETIC_TABLE)
    assert api.magnet.set_force(1.0).wait(5) == pytest.approx(10.0, abs=0.01)
    assert api.devices.info("magnet")["calibration"]["force_table"]["name"] == "synthetic test table"
    m = api.magnet.set_force(15.0)                                   # coerced to the table end (decision 0018)
    assert m.applied_pN == 10.0 and m.wait(10) == pytest.approx(20.0, abs=0.01)


def test_unknown_backend_not_implemented_and_not_connected():
    with pytest.raises(NotImplementedError, match="does not exist"):
        api.devices.connect({"backend": "ebus"})
    with pytest.raises(NotReady, match="connect"):
        api.magnet.position()


def test_real_backend_refuses_without_the_rig_lock(tmp_path, monkeypatch, fake_riglock):
    """Phase 6 / decision 0026: a real backend takes the rig lock first; refused -> NotReady, nothing opened."""
    _config(tmp_path, monkeypatch, True)
    fake_riglock.refuse = "held by V6-chat (pid 1)"
    with pytest.raises(NotReady, match="held by"):
        api.devices.connect({"backend": "real"})
    assert api.devices.status() == {} and "RIGLOCK_TOKEN" not in os.environ


class _FakeImaqdx:
    """`imaqdx.ImaqdxCamera` as the JAI answers it (attribute names and .icd defaults from the manual)."""
    name, model, serial = "cam1", "SP-5000M-USB", "000014FB0067A270"

    def __init__(self):
        from mtpy.devices import jai
        from mtpy.devices.imaqdx import ACQ, IMG
        self.a = {ACQ + "ExposureTime": 1909.0, ACQ + "ExposureAuto": "Continuous", ACQ + "AcquisitionFrameRate": 90.0009,
                  jai.GAIN: 16.0, IMG + "OffsetX": 0, IMG + "OffsetY": 0, IMG + "Width": 1280, IMG + "Height": 1024,
                  jai.DEV + "DeviceFirmwareVersion": "0.2.0.0"}
        self.rate_key, self.acquiring, self.stopped = ACQ + "AcquisitionFrameRate", False, threading.Event()

    def open(self):
        pass

    def get(self, n, t):
        return self.a[n]

    def set(self, n, t, v):
        self.a[n] = 1e6 / round(1e6 / v) if n == self.rate_key else v     # 1 us period steps, as the camera

    def start(self, n_buffers):
        self.t0, self.acquiring = time.perf_counter(), True
        self.stopped.clear()

    def frame(self, b):
        due = self.t0 + b / self.a[self.rate_key]
        while time.perf_counter() < due:
            if self.stopped.is_set():
                raise RuntimeError("acquisition stopped")
            if due - time.perf_counter() > 0.002:          # spin the last 2 ms: Windows sleep is 1-2 ms coarse
                time.sleep(0.0005)
        return b, time.time(), np.full((1024, 1280), 90, np.uint8)

    def stop_streaming(self):
        self.stopped.set()

    def stop(self):
        self.stopped.set()
        self.acquiring = False

    close = stop


def test_real_camera_preset_readback_and_recording(tmp_path, monkeypatch):
    """The JAI device behind the same API as the simulator: preset read back (U15), per-frame PC timestamps and the
    frame-rate triple in the run file."""
    import h5py

    from mtpy.devices import jai
    _config(tmp_path, monkeypatch, True)
    monkeypatch.setattr(jai, "ImaqdxCamera", _FakeImaqdx)
    monkeypatch.setattr(jai, "_permitted", lambda: None)
    with events.as_caller("gui"):
        api.devices.connect({"backend": "real"})
    try:
        cam = api.devices.service("camera").device
        dx = cam.cam
        got = api.camera.apply_preset({"name": "tracking 150 Hz", "rate_Hz": 150.0, "exposure_ms": 5.0})
        assert got["rate_Hz"] == pytest.approx(149.9925, abs=1e-4) and got["exposure_ms"] == 5.0
        assert cam.cam.a[jai.ACQ + "ExposureAuto"] == "Off"
        with pytest.raises(DeviceError, match="read-only"):
            api.camera.set_gain(2.0)
        api.acq.start(record=True, name="jai", folder=tmp_path)
        api.acq.wait_frames(30, 5.0)
        st = api.acq.stop()
        assert st["camera_gaps"] == 0 and st["frames_received"] >= 30 and cam.error is None
        with h5py.File(tmp_path / "jai.h5", "r") as f:
            triple = f["metadata/run/frame_rate_hz"][()]
            assert triple[0] == 150.0 and triple[1] == pytest.approx(149.9925, abs=1e-4)
            assert triple[2] == pytest.approx(150.0, rel=0.05)
            assert "PC receive time" in f["mt/t_camera"].attrs["source"]
            assert np.all(np.diff(f["mt/t_camera"][()]) > 0)
    finally:
        api.devices.disconnect()
    assert dx.acquiring is False and cam.cam is None                   # cleanup: streaming stopped, session closed


def test_disconnect_reports_a_failed_close(rig):
    """Phase 7 (RULES.md 2.5): a device whose close fails - a real motor's session end - makes disconnect() raise
    after every other device is closed, instead of swallowing it (run 1 on the rig, 2026-10-30)."""
    dev = rig["magnet"].device

    def bad_close():
        raise ConnectionError("PI magnet return: POS 5, not within 0.01 of 0 mm; limits NOT released")
    dev.close = bad_close
    with pytest.raises(DeviceError, match="cleanup incomplete.*limits NOT released"):
        api.devices.disconnect()
    assert api.devices.status() == {}
