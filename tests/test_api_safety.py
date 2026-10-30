"""WP1: the rig safety profile, the acting-call safety behaviour, the event log and the emergency stop (no hardware)."""
import json
import shutil
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pytest

from mtpy import api
from mtpy.admin import safety_admin as admin
from mtpy.api import estop, events, safety
from mtpy.api._act import acting
from mtpy.api.errors import DeviceError, NotReady, SafetyRefused

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    """A temporary config folder holding profile v1 only (active and history), loaded fresh for each test: the WP1
    tests of the profile mechanism and the admin write path start from v1. The shipped config (v2 since decision
    0016) is checked by test_shipped_config_is_v2_with_magnet_speed_max_15."""
    shutil.copytree(REPO_CONFIG, tmp_path / "config")
    hist = tmp_path / "config" / "safety_profiles"
    (tmp_path / "config" / "safety_profile.json").write_text((hist / "1.json").read_text(encoding="utf-8"),
                                                              encoding="utf-8")
    for f in hist.glob("*.json"):
        if f.stem != "1":
            f.unlink()
    monkeypatch.setattr(safety, "CONFIG", tmp_path / "config")
    safety.load_active()
    with events.as_caller("gui"):
        estop.clear()
    yield tmp_path / "config"
    with events.as_caller("gui"):
        estop.clear()


class Motor:
    """A fake device: `offset` makes it read back something other than what was asked."""

    def __init__(self, offset=0.0):
        self.pos, self.offset, self.sent = 0.0, offset, []

    def do(self, v):
        self.sent.append(v)
        self.pos = v + self.offset

    def readback(self):
        return self.pos


def test_shipped_config_is_v7_focus_window_from_the_controller_rotor_verified(monkeypatch):
    """v7 (rig 2026-10-30): `rotor_turns` +-5 turns verified (both edges driven, one pulse past refused). Decision
    0025 (v6): `focus_z_um` = the ASI controller's SL/SU Z (+-75 um, absolute, verified by readback), else as v5. Decision 0017 (v5): `magnet_force_pN`
    removed (the force limit is derived from the magnet position limit), nothing checked on the rig, every other
    limit identical to v4; v1-v5 stay in the history."""
    monkeypatch.setattr(safety, "CONFIG", REPO_CONFIG)
    p = safety.load_active()
    v4, v5, v6, v7 = (json.loads((REPO_CONFIG / "safety_profiles" / f"{v}.json").read_text(encoding="utf-8")) for v in (4, 5, 6, 7))
    assert p["version"] == 7 and p["base_version"] == 6 and safety.versions() == [1, 2, 3, 4, 5, 6, 7]
    assert safety._thaw(p) == v7 and v7["allow_unverified"] is False and v6["allow_unverified"] is False
    assert v7["limits"]["rotor_turns"]["verified"] is True and v7["recommissioning"]["checked"] == {"rotor_turns": True}
    assert v7["unverified"] == ["rotor_speed_turns_s"] and safety.check("rotor_turns", 204.0, 200.0) is True
    assert {q: e for q, e in v7["limits"].items() if q != "rotor_turns"} == {q: e for q, e in v6["limits"].items() if q != "rotor_turns"}
    assert v6["limits"]["focus_z_um"] == {"min": -75.0, "max": 75.0, "unit": "um", "relative_to": None, "verified": True,
                                          "source": v6["limits"]["focus_z_um"]["source"]}
    assert "0025" in v6["limits"]["focus_z_um"]["source"] and "focus_z_um" not in v6["unverified"]
    assert v6["recommissioning"]["checked"] == {"focus_z_um": True}
    assert {q: e for q, e in v6["limits"].items() if q != "focus_z_um"} == {q: e for q, e in v5["limits"].items() if q != "focus_z_um"}
    assert safety.check("focus_z_um", 70.0) is True
    assert v5["allow_unverified"] is False
    assert "magnet_force_pN" not in v5["limits"] and "magnet_force_pN" not in v5["unverified"]
    assert v5["limits"] == {q: e for q, e in v4["limits"].items() if q != "magnet_force_pN"}
    assert v5["unverified"] == [q for q in v4["unverified"] if q != "magnet_force_pN"]
    assert v5["recommissioning"]["checked"] == {} and v5["recommissioning"]["not_checked_unverified"] == []
    assert "0017" in v5["reason"]
    assert safety.check("magnet_position_mm", 39.0) is True and safety.check("magnet_speed_mm_s", 15.0) is True
    with pytest.raises(SafetyRefused, match="magnet_force_pN is not in the rig safety profile v7"):
        safety.check("magnet_force_pN", 1.0)


def test_history_v4_magnet_speed_15_rig_checked(monkeypatch):
    """v4 in the history (base v3, admin path, 2026-10-25): magnet_speed_mm_s [0, 15] mm/s verified after the rig
    move-and-read-back (V6 card pivel15r), recorded as `checked` through the normal path (no unverified exception).
    Every other limit is identical to v3; v3 as written (speed 15 mm/s verified:false, nothing checked)."""
    hist = {v: json.loads((REPO_CONFIG / "safety_profiles" / f"{v}.json").read_text(encoding="utf-8"))
            for v in (1, 2, 3, 4)}
    monkeypatch.setattr(safety, "_active", safety._freeze(hist[4]))
    v3, v4 = hist[3], hist[4]
    assert v4["version"] == 4 and v4["base_version"] == 3
    assert v4["allow_unverified"] is False and "magnet_speed_mm_s" not in v4["unverified"]
    assert v4["recommissioning"]["checked"] == {"magnet_speed_mm_s": True}
    assert v4["recommissioning"]["not_checked_unverified"] == []
    assert "pivel15r" in v4["recommissioning"]["notes"] and "pi_vel15_check_20261025.log" in v4["recommissioning"]["notes"]
    speed = v4["limits"]["magnet_speed_mm_s"]
    assert speed["min"] == 0.0 and speed["max"] == 15.0 and speed["verified"] is True and "pivel15r" in speed["source"]
    assert [q for q in v4["limits"] if v4["limits"][q] != v3["limits"][q]] == ["magnet_speed_mm_s"]
    assert v3["limits"]["magnet_speed_mm_s"]["verified"] is False and v3["recommissioning"]["checked"] == {}
    for v in (1, 2):
        assert [q for q in hist[v]["limits"] if hist[v]["limits"][q] != v3["limits"][q]] == ["magnet_speed_mm_s"]
    assert safety.check("magnet_speed_mm_s", 15.0) is True
    with pytest.raises(SafetyRefused, match=r"outside the allowed range \[0, 15\]"):
        safety.check("magnet_speed_mm_s", 15.5)
    with pytest.raises(SafetyRefused, match="magnet_force_pN has no limit set"):
        safety.check("magnet_force_pN", 1.0)


def _speed_limits(verified, max_=15.0):
    limits = safety._thaw(safety.profile()["limits"])
    limits["magnet_speed_mm_s"].update(max=max_, verified=verified, source="TEST")
    return limits


def test_unverified_change_activates_without_checked_and_refuses(session):
    """Review l2s-wp5-r4: a changed entry whose new value is verified:false, with allow_unverified false, activates
    with an empty `checked` (never recorded as checked) and refuses every request."""
    with events.as_caller("gui"):
        pending = admin.propose_change(session, _speed_limits(False), by="admin", reason="owner value, not rig-checked")
        p = admin.activate(session, pending, admin.RecommissioningReport(by="admin", checked={}))
    assert p["version"] == 2 and p["recommissioning"]["checked"] == {}
    assert list(p["recommissioning"]["not_checked_unverified"]) == ["magnet_speed_mm_s"]
    with pytest.raises(SafetyRefused, match="not verified"):
        safety.check("magnet_speed_mm_s", 5.0)


def test_verified_change_without_checked_is_refused(session):
    with events.as_caller("gui"):
        pending = admin.propose_change(session, _speed_limits(True), by="admin", reason="r")
        with pytest.raises(SafetyRefused, match=r"does not show these new limits as checked: \['magnet_speed_mm_s'\]"):
            admin.activate(session, pending, admin.RecommissioningReport(by="admin", checked={}))
    assert safety.profile()["version"] == 1


def test_no_unchecked_exception_when_unverified_limits_are_allowed(config, session):
    """With allow_unverified true an unverified limit is USED, so it is not exempt from `checked`."""
    _allow_unverified_on_disk(config)
    with events.as_caller("gui"):
        pending = admin.propose_change(session, _speed_limits(False), by="admin", reason="r")
        with pytest.raises(SafetyRefused, match="does not show these new limits as checked"):
            admin.activate(session, pending, admin.RecommissioningReport(by="admin", checked={}))
    assert safety.profile()["version"] == 1


def test_version_and_shipped_profile_is_valid():
    assert api.VERSION == "0.10.1"
    p = safety.profile()
    assert p["version"] == 1 and safety.versions() == [1]
    assert p["limits"]["magnet_position_mm"]["max"] == 39.0
    with pytest.raises(TypeError):
        p["limits"]["magnet_position_mm"]["max"] = 50.0          # read-only view


def test_refusal_names_the_range_and_never_clamps():
    m = Motor()
    with pytest.raises(SafetyRefused, match=r"\[0, 39\] mm"):
        acting("magnet_position_mm", 40.0, m.do, m.readback, tol=0.01)
    assert m.sent == []                                           # nothing sent, nothing clamped
    assert acting("magnet_position_mm", 39.0, m.do, m.readback, tol=0.01) == 39.0


def test_relative_window_and_unset_limits():
    safety.check("stage_x_mm", 11.9, origin=10.0)
    with pytest.raises(SafetyRefused, match=r"\[8, 12\] mm"):
        safety.check("stage_x_mm", 12.1, origin=10.0)
    with pytest.raises(SafetyRefused, match="not given"):
        safety.check("stage_x_mm", 10.0)
    with pytest.raises(SafetyRefused, match="no limit set"):
        safety.check("magnet_force_pN", 1.0)
    with pytest.raises(SafetyRefused, match="not in the rig safety profile"):
        safety.check("laser_power_mW.green", 1.0)
    with pytest.raises(SafetyRefused, match="finite"):
        safety.check("magnet_position_mm", float("nan"))


def test_event_logged_with_caller_and_subscriber():
    seen = []
    unsubscribe = events.subscribe(seen.append)
    n = len(events.events())
    m = Motor()
    with events.as_caller("script:cleavage@1.2"):
        acting("magnet_position_mm", 5.0, m.do, m.readback, tol=0.01)
        with pytest.raises(SafetyRefused):
            acting("magnet_position_mm", -1.0, m.do, m.readback, tol=0.01)
    unsubscribe()
    new = [e for e in events.events()[n:] if e.kind in ("act", "refused")]
    assert [e.kind for e in new] == ["act", "refused"]
    assert all(e.caller == "script:cleavage@1.2" for e in new)
    assert new[0].request == {"quantity": "magnet_position_mm", "value": 5.0} and new[0].readback == 5.0
    assert new[0] in seen and new[1] in seen
    assert events.caller() == "unknown"
    with pytest.raises(ValueError), events.as_caller("hacker"):
        pass


def test_readback_mismatch_is_device_error():
    m = Motor(offset=0.5)
    with pytest.raises(DeviceError) as e:
        acting("magnet_position_mm", 5.0, m.do, m.readback, tol=0.01)
    assert e.value.device == "magnet" and "5.5" in e.value.hint
    assert events.events()[-1].kind == "device_error"


def test_estop_blocks_acting_calls():
    m = Motor()
    estop.engage()
    with pytest.raises(NotReady, match="emergency stop"):
        acting("magnet_position_mm", 5.0, m.do, m.readback, tol=0.01)
    assert m.sent == []
    with events.as_caller("gui"):
        estop.clear()
    assert acting("magnet_position_mm", 5.0, m.do, m.readback, tol=0.01) == 5.0


# --- item 1: tolerance, read-back and device exceptions ------------------------------------------------------------

@pytest.mark.parametrize("tol", [float("nan"), float("inf"), -0.1, "0.1", None, True])
def test_bad_tolerance_refused_before_sending(tol):
    m = Motor()
    with pytest.raises(SafetyRefused, match="tolerance"):
        acting("magnet_position_mm", 5.0, m.do, m.readback, tol=tol)
    assert m.sent == [] and events.events()[-1].kind == "refused"


@pytest.mark.parametrize("got", [float("nan"), float("inf"), "5.0", None, [5.0]])
def test_non_numeric_readback_is_device_error(got):
    m = Motor()
    n = len(events.events())
    with pytest.raises(DeviceError, match="not a finite number"):
        acting("magnet_position_mm", 5.0, m.do, lambda: got, tol=0.01)
    assert [e.kind for e in events.events()[n:]] == ["device_error"]      # never logged as success


def test_numpy_readback_accepted():
    m = Motor()
    assert acting("magnet_position_mm", 5.0, m.do, lambda: np.float32(5.0), tol=0.01) == 5.0


def _boom(*_):
    raise OSError("port COM3 closed")


@pytest.mark.parametrize("stage", ["send", "readback"])
def test_device_exception_becomes_device_error(stage):
    m = Motor()
    do, rb = (_boom, m.readback) if stage == "send" else (m.do, _boom)
    n = len(events.events())
    with pytest.raises(DeviceError) as e:
        acting("magnet_position_mm", 5.0, do, rb, tol=0.01)
    assert e.value.device == "magnet" and e.value.command == "set magnet_position_mm 5.0"
    assert "OSError" in e.value.hint and "COM3" in e.value.hint and isinstance(e.value.__cause__, OSError)
    new = events.events()[n:]
    assert [x.kind for x in new] == ["device_error"] and new[0].extra["stage"] == stage


# --- item 2: the write path is not in the public API ---------------------------------------------------------------

def test_public_api_has_no_write_path():
    for name in ("propose_change", "activate", "Pending", "RecommissioningReport", "ADMIN"):
        assert not hasattr(safety, name) and not hasattr(api, name)
    code = "import sys, mtpy.api; print('mtpy.admin' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True)
    assert out.stdout.strip() == "False"


@pytest.fixture
def session():
    with events.as_caller("gui"):
        return admin.open_admin_session("new magnet mount")


@pytest.mark.parametrize("who", ["script:x@1", "plugin:det", "ai:autonomous", "ai:run_approved", "unknown"])
def test_admin_session_refused_for_untrusted_callers(who, session):
    with events.as_caller(who) if who != "unknown" else nullcontext():
        with pytest.raises(SafetyRefused, match="rig-admin settings screen"):
            admin.open_admin_session("x")
        with pytest.raises(SafetyRefused, match="rig-admin settings screen"):     # a leaked session does not help
            admin.propose_change(session, _wider_magnet(), by="x", reason="y")
    assert events.events()[-1].kind == "refused"
    assert safety.profile()["version"] == 1


def test_admin_session_needs_reason_and_factory(session):
    with events.as_caller("gui"):
        with pytest.raises(SafetyRefused, match="reason"):
            admin.open_admin_session("  ")
        with pytest.raises(SafetyRefused, match="open_admin_session"):
            admin.AdminSession(object(), "gui", "forged")
        with pytest.raises(SafetyRefused, match="AdminSession"):
            admin.propose_change(None, _wider_magnet(), by="x", reason="y")
        with pytest.raises(SafetyRefused, match="propose_change"):
            admin._Pending(object(), safety.profile())
    assert session.who == "gui" and session.reason == "new magnet mount"
    opened = [e for e in events.events() if e.request == {"action": "open_admin_session"}][-1]
    assert opened.caller == "gui" and opened.extra["reason"] == "new magnet mount"


# --- item 3: activate() recomputes and re-validates ----------------------------------------------------------------

def _wider_magnet():
    limits = json.loads(json.dumps(safety._thaw(safety.profile()["limits"])))
    limits["magnet_position_mm"]["max"] = 45.0
    return limits


def _report(*checked):
    return admin.RecommissioningReport(by="admin", checked={q: True for q in checked})


def test_activate_needs_report_and_keeps_history(config, session):
    with events.as_caller("gui"):
        pending = admin.propose_change(session, _wider_magnet(), by="admin", reason="new magnet mount")
        with pytest.raises(SafetyRefused, match="magnet_position_mm"):
            admin.activate(session, pending, _report())
        with pytest.raises(SafetyRefused, match="RecommissioningReport"):
            admin.activate(session, pending, {"magnet_position_mm": True})
        p = admin.activate(session, pending, _report("magnet_position_mm"))
        with pytest.raises(SafetyRefused, match="propose again"):       # stale proposal
            admin.activate(session, pending, _report("magnet_position_mm"))
    assert p["version"] == 2 and p["base_version"] == 1 and safety.versions() == [1, 2]
    assert json.loads((config / "safety_profiles" / "1.json").read_text())["limits"]["magnet_position_mm"]["max"] == 39
    assert safety.load_active()["limits"]["magnet_position_mm"]["max"] == 45.0      # survives a reload from disk
    safety.check("magnet_position_mm", 44.0)


def _tampered(pending, edit):
    p = safety._thaw(pending.profile)
    edit(p)
    pending.profile = safety._freeze(p)
    return pending


def test_activate_recomputes_the_diff(session):
    with events.as_caller("gui"):
        pending = admin.propose_change(session, _wider_magnet(), by="admin", reason="new magnet mount")
        _tampered(pending, lambda p: p["limits"]["stage_x_mm"].update(max=20.0))   # sneaked in after the proposal
        with pytest.raises(SafetyRefused, match="stage_x_mm"):
            admin.activate(session, pending, _report("magnet_position_mm"))
    assert safety.profile()["version"] == 1


@pytest.mark.parametrize("edit, match", [
    (lambda p: p["limits"]["magnet_position_mm"].update(min=50.0), "not valid"),          # min > max
    (lambda p: p.update(unverified=[]), "not valid"),                                     # list drifts from flags
    (lambda p: p.update(version=3, base_version=2), "propose again"),                     # not based on active v1
])
def test_activate_revalidates_the_candidate(session, edit, match):
    with events.as_caller("gui"):
        pending = _tampered(admin.propose_change(session, _wider_magnet(), by="a", reason="r"), edit)
        with pytest.raises(SafetyRefused, match=match):
            admin.activate(session, pending, _report("magnet_position_mm"))
    assert safety.profile()["version"] == 1


# --- item 4: unverified limits -------------------------------------------------------------------------------------

def test_shipped_profile_refuses_unverified_limits():
    p = safety.profile()
    assert p["allow_unverified"] is False and "rotor_turns" in p["unverified"]
    m = Motor()
    with pytest.raises(SafetyRefused, match="not verified"):
        acting("rotor_turns", 1.0, m.do, m.readback, tol=0.01, origin=0.0)
    assert m.sent == []


def _allow_unverified_on_disk(config):
    """allow_unverified true written straight to the active file (activate() refuses false -> true for now)."""
    path = config / "safety_profile.json"
    p = json.loads(path.read_text(encoding="utf-8"))
    p["allow_unverified"] = True
    path.write_text(json.dumps(p), encoding="utf-8")
    safety.load_active()


def test_allowed_unverified_limit_logs_warning(config):
    _allow_unverified_on_disk(config)
    m = Motor()
    n = len(events.events())
    assert acting("rotor_turns", 1.0, m.do, m.readback, tol=0.01, origin=0.0) == 1.0
    assert acting("magnet_position_mm", 5.0, m.do, m.readback, tol=0.01) == 5.0
    new = events.events()[n:]
    assert [e.kind for e in new] == ["unverified-limit", "act", "act"]
    assert new[0].extra["level"] == "warning" and new[0].request["quantity"] == "rotor_turns"
    with pytest.raises(SafetyRefused, match="outside"):
        safety.check("rotor_turns", 5.5, origin=0.0)                  # the window itself still holds


@pytest.mark.parametrize("edit", [lambda p: p.pop("allow_unverified"), lambda p: p.update(unverified=["rotor_turns"])])
def test_load_rejects_profile_without_unverified_policy(config, edit):
    path = config / "safety_profile.json"
    p = json.loads(path.read_text(encoding="utf-8"))
    edit(p)
    path.write_text(json.dumps(p), encoding="utf-8")
    with pytest.raises((TypeError, ValueError), match="allow_unverified|unverified"):
        safety.load_active()


# --- review l2s-wp1-r2 ---------------------------------------------------------------------------------------------

def test_failing_subscriber_isolated_and_device_error_preserved():
    """(a) one broken subscriber: the others still get every event, the acting call's own DeviceError reaches the
    caller, and the failure is recorded once per event as `subscriber_error` (no recursion)."""
    def broken(ev):
        raise RuntimeError("disk full")
    seen = []
    unsub = [events.subscribe(broken), events.subscribe(seen.append)]
    m = Motor(offset=0.5)
    n = len(events.events())
    with pytest.raises(DeviceError, match="5.5"):
        acting("magnet_position_mm", 5.0, m.do, m.readback, tol=0.01)
    with pytest.raises(SafetyRefused, match="outside"):
        acting("magnet_position_mm", 40.0, m.do, m.readback, tol=0.01)
    for u in unsub:
        u()
    new = events.events()[n:]
    assert [e.kind for e in new] == ["device_error", "subscriber_error", "refused", "subscriber_error"]
    assert new[1].extra["event_kind"] == "device_error" and "disk full" in new[1].extra["error"]
    assert new[1].extra["subscriber"].endswith("broken")
    assert [e.kind for e in seen if e in new] == [e.kind for e in new]   # healthy subscriber got all four


def test_subscriber_error_not_recursive():
    """(a) a subscriber that also fails on `subscriber_error` events does not cause a second record or a loop."""
    def always_broken(ev):
        raise ValueError("bad")
    unsub = events.subscribe(always_broken)
    n = len(events.events())
    try:
        events.log("note")
    finally:
        unsub()
    assert [e.kind for e in events.events()[n:]] == ["note", "subscriber_error"]


@pytest.mark.parametrize("who", ["script:x@1", "plugin:det", "ai:autonomous", "ai:run_approved", "unknown"])
def test_estop_clear_refused_for_untrusted_callers(who):
    """(b) only 'gui' or 'rig-admin' may release the emergency stop."""
    estop.engage()
    with (events.as_caller(who) if who != "unknown" else nullcontext(),
          pytest.raises(SafetyRefused, match="emergency stop")):
        estop.clear()
    assert estop.active() and events.events()[-1].kind == "refused"
    with events.as_caller("rig-admin"):
        estop.clear()
    assert not estop.active()


def test_activate_refuses_allow_unverified_false_to_true(session):
    """(c) false -> true refused for now (owner decision pending); the active profile is unchanged."""
    with events.as_caller("gui"):
        pending = admin.propose_change(session, safety._thaw(safety.profile()["limits"]), by="admin",
                                       reason="rotor tests on the bench", allow_unverified=True)
        with pytest.raises(SafetyRefused, match="allow_unverified"):
            admin.activate(session, pending, _report())
    assert events.events()[-1].kind == "refused"
    assert safety.profile()["version"] == 1 and safety.profile()["allow_unverified"] is False


def test_activate_allows_allow_unverified_true_to_false(config, session):
    """(c) switching unverified limits OFF is allowed."""
    _allow_unverified_on_disk(config)
    with events.as_caller("gui"):
        pending = admin.propose_change(session, safety._thaw(safety.profile()["limits"]), by="admin",
                                       reason="bench tests over", allow_unverified=False)
        assert admin.activate(session, pending, _report())["allow_unverified"] is False
    assert safety.profile()["version"] == 2


def test_huge_int_is_not_finite():
    """(d) 10**400 does not overflow: SafetyRefused with a `refused` event, nothing sent."""
    assert not safety._is_number(10**400) and safety._is_number(10**20)
    m = Motor()
    for kwargs in ({"value": 10**400, "tol": 0.01}, {"value": 5.0, "tol": 10**400}):
        n = len(events.events())
        with pytest.raises(SafetyRefused):
            acting("magnet_position_mm", kwargs["value"], m.do, m.readback, tol=kwargs["tol"])
        assert [e.kind for e in events.events()[n:]] == ["refused"]
    with pytest.raises(SafetyRefused, match="finite"):
        safety.check("magnet_position_mm", -10**400)
    with pytest.raises(SafetyRefused, match="not given"):
        safety.check("stage_x_mm", 10.0, origin=10**400)
    assert m.sent == []
    with pytest.raises(DeviceError, match="not a finite number"):
        acting("magnet_position_mm", 5.0, m.do, lambda: 10**400, tol=0.01)
