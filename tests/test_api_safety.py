"""WP1: the rig safety profile, the acting-call safety behaviour, the event log and the emergency stop (no hardware)."""
import json
import shutil
from pathlib import Path

import pytest

from mtpy import api
from mtpy.api import estop, events, safety
from mtpy.api._act import acting
from mtpy.api.errors import DeviceError, NotReady, SafetyRefused

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    """A copy of the shipped profile in a temporary config folder, loaded fresh for each test."""
    shutil.copytree(REPO_CONFIG, tmp_path / "config")
    monkeypatch.setattr(safety, "CONFIG", tmp_path / "config")
    safety.load_active()
    estop.clear()
    yield tmp_path / "config"
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


def test_version_and_shipped_profile_is_valid():
    assert api.VERSION == "0.1.0"
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
    estop.clear()
    assert acting("magnet_position_mm", 5.0, m.do, m.readback, tol=0.01) == 5.0


def _wider_magnet():
    limits = json.loads(json.dumps(safety._thaw(safety.profile()["limits"])))
    limits["magnet_position_mm"]["max"] = 45.0
    return limits


@pytest.mark.parametrize("who", ["script:x@1", "plugin:det", "ai:autonomous", "gui", "unknown"])
def test_profile_write_refused_for_non_admin(who):
    if who == "unknown":
        with pytest.raises(SafetyRefused):
            safety.propose_change(_wider_magnet(), by="x", reason="y")
        return
    with events.as_caller("rig-admin"):
        pending = safety.propose_change(_wider_magnet(), by="admin", reason="new magnet mount")
    report = safety.RecommissioningReport(by="admin", checked={"magnet_position_mm": True})
    with events.as_caller(who):
        with pytest.raises(SafetyRefused, match="rig-admin"):
            safety.propose_change(_wider_magnet(), by="x", reason="y")
        with pytest.raises(SafetyRefused, match="rig-admin"):
            safety.activate(pending, report)
    assert safety.profile()["version"] == 1


def test_activate_needs_report_and_keeps_history(config):
    with events.as_caller("rig-admin"):
        pending = safety.propose_change(_wider_magnet(), by="admin", reason="new magnet mount")
        assert pending.changed == ("magnet_position_mm",)
        with pytest.raises(SafetyRefused, match="magnet_position_mm"):
            safety.activate(pending, safety.RecommissioningReport(by="admin", checked={}))
        with pytest.raises(SafetyRefused, match="RecommissioningReport"):
            safety.activate(pending, {"magnet_position_mm": True})
        p = safety.activate(pending, safety.RecommissioningReport(by="admin", checked={"magnet_position_mm": True}))
        with pytest.raises(SafetyRefused, match="propose again"):       # stale proposal
            safety.activate(pending, safety.RecommissioningReport(by="admin", checked={"magnet_position_mm": True}))
    assert p["version"] == 2 and safety.versions() == [1, 2]
    assert json.loads((config / "safety_profiles" / "1.json").read_text())["limits"]["magnet_position_mm"]["max"] == 39
    assert safety.load_active()["limits"]["magnet_position_mm"]["max"] == 45.0      # survives a reload from disk
    safety.check("magnet_position_mm", 44.0)
