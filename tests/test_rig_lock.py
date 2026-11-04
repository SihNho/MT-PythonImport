"""Decision 0026: the program holds the shared rig lock itself (api.rig), taken by devices.connect for any backend
but `sim`, released by disconnect only after every cleanup succeeded. Against the in-memory FakeRiglock (conftest)."""
import os
from pathlib import Path

import pytest
from test_devices import _config

from mtpy import api
from mtpy.api import estop, events, rig, safety
from mtpy.api.errors import DeviceError, NotReady
from mtpy.devices.sim import make_rig


@pytest.fixture
def fake_real(tmp_path, monkeypatch):
    """A 'real-test' backend built from the simulators, so connect takes the lock path without hardware."""
    _config(tmp_path, monkeypatch, True)
    import mtpy.devices as devs
    real_make = devs.make
    monkeypatch.setattr(devs, "make", lambda r: make_rig() if r.get("backend") == "real-test" else real_make(r))
    with events.as_caller("gui"):
        estop.clear()
    yield
    with events.as_caller("gui"):
        if api.devices.status():
            try:
                api.devices.disconnect()
            except DeviceError:
                pass
        rig.release()
        estop.clear()


def test_sim_backend_takes_no_lock(fake_real, fake_riglock):
    api.devices.connect({"backend": "sim"})
    assert fake_riglock.log == [] and not rig.status()["held"]
    api.devices.disconnect()


def test_real_backend_acquires_and_releases(fake_real, fake_riglock):
    api.devices.connect({"backend": "real-test"})
    assert fake_riglock.log == ["acquire"] and os.environ["RIGLOCK_TOKEN"] == "fake-token"
    assert rig.status() == {"held": True, "own": True, "holder": fake_riglock.holder, "holder_alive": True, "rig_state": "assembled"}
    api.devices.disconnect()
    assert fake_riglock.log == ["acquire", "release"] and "RIGLOCK_TOKEN" not in os.environ
    assert not rig.status()["held"]


def test_refused_lock_connects_nothing(fake_real, fake_riglock):
    fake_riglock.refuse = "rig_state is 'experiment'"
    with pytest.raises(NotReady, match="experiment"):
        api.devices.connect({"backend": "real-test"})
    assert api.devices.status() == {} and fake_riglock.log == []


def test_failed_cleanup_keeps_the_lock(fake_real, fake_riglock, monkeypatch):
    api.devices.connect({"backend": "real-test"})
    dev = api.devices.service("magnet").device

    def bad_close():
        raise ConnectionError("PI magnet return: POS 3.0, not within 0.01 of 0 mm; limits NOT released")
    monkeypatch.setattr(dev, "close", bad_close)
    with pytest.raises(DeviceError, match="cleanup incomplete"):
        api.devices.disconnect()
    assert fake_riglock.log == ["acquire"] and rig.status()["held"]       # RULES.md 3: lock kept, reported
    rig.release()
    assert fake_riglock.log == ["acquire", "release"]


def test_wrapper_token_is_adopted_not_released(fake_real, fake_riglock, monkeypatch):
    fake_riglock.acquire("V6-chat", "wrapper")
    monkeypatch.setenv("RIGLOCK_TOKEN", "fake-token")
    api.devices.connect({"backend": "real-test"})
    assert rig.status()["own"] is False and fake_riglock.log == ["acquire"]
    api.devices.disconnect()
    assert fake_riglock.holder is not None and fake_riglock.log == ["acquire"]     # the wrapper releases it
    fake_riglock.release("fake-token")


def test_lost_permission_engages_the_stop(fake_real, fake_riglock, monkeypatch):
    monkeypatch.setattr(rig, "HEARTBEAT_S", 0.05)
    api.devices.connect({"backend": "real-test"})
    fake_riglock.state = "experiment"
    import time
    t_end = time.monotonic() + 3.0
    while not estop.active() and time.monotonic() < t_end:
        time.sleep(0.02)
    assert estop.active()


def test_mode_chooses_the_devices(fake_real):
    """Owner 2026-10-30: MT = tracking alone, MT-TIRF = everything; the mode is on the connect event and in mode()."""
    st = api.devices.connect({"backend": "sim", "mode": "MT"})
    assert sorted(st) == ["camera", "focus", "magnet", "rotor", "stage"] and api.devices.mode() == "MT"
    api.devices.disconnect()
    assert api.devices.mode() is None
    st = api.devices.connect({"backend": "sim"})
    assert len(st) == 8 and api.devices.mode() == "MT-TIRF"
    api.devices.disconnect()
    with pytest.raises(NotReady, match="mode"):
        api.devices.connect({"backend": "sim", "mode": "FRET"})


def test_stale_lock_is_taken_over_on_the_users_words_and_connect_works_again(fake_real, fake_riglock, monkeypatch, tmp_path):
    """Owner 2026-11-04: "how does the program work again after a stale lock? I cannot ask the agent every time" -
    api.rig.recover_stale(reason) takes a dead holder's lock over (riglock logs the reason), records the recovery,
    releases, and the next connect is normal. A live holder is never taken; no reason, no take-over."""
    monkeypatch.setattr(rig, "RECOVERY_DIR", tmp_path / "recovery")
    fake_riglock.holder = {"name": "mtpy", "purpose": "bench", "token": "old", "pid": 2808, "since": "yesterday"}
    fake_riglock.alive = True
    with pytest.raises(NotReady, match="live process"):
        rig.recover_stale("owner: take over")
    fake_riglock.alive = False
    assert rig.stale()["pid"] == 2808
    with pytest.raises(NotReady, match="own words"):
        rig.recover_stale("")
    with pytest.raises(NotReady, match="rig lock refused"):
        api.devices.connect({"backend": "real-test", "mode": "MT"})
    res = rig.recover_stale("owner via GUI 'Take over'")
    assert res["old_holder"]["pid"] == 2808 and fake_riglock.holder is None
    assert fake_riglock.log[-3:] == ["take-stale", "acquire", "recovered"] or fake_riglock.log[-4:] == ["take-stale", "acquire", "recovered", "release"]
    rec = tmp_path / "recovery"
    assert any((d / "devices_closed.json").exists() and (d / "limits_released.json").exists() for d in rec.iterdir())
    with pytest.raises(NotReady, match="no stale lock"):
        rig.recover_stale("again")
    with events.as_caller("gui"):
        st = api.devices.connect({"backend": "real-test", "mode": "MT"})
    assert st and rig.status()["held"]


def test_rig_set_limit_tool_activates_one_quantity(tmp_path, monkeypatch):
    """tools/rig_set_limit.py (rig 2026-11-05: rotor_speed_turns_s had max None, every rotation refused): the
    quantity gets its value through the admin flow, the version goes up, the others stay."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from test_devices import _config
    _config(tmp_path, monkeypatch, test_limits=False)
    import rig_set_limit
    before = safety.profile()
    p = rig_set_limit.set_limit("rotor_speed_turns_s", hi=2.0, reason="test")
    assert p["version"] == before["version"] + 1 and p["limits"]["rotor_speed_turns_s"]["max"] == 2.0
    assert p["limits"]["rotor_speed_turns_s"]["verified"] and p["limits"]["magnet_position_mm"] == dict(before["limits"]["magnet_position_mm"])
    assert safety.profile()["limits"]["rotor_speed_turns_s"]["max"] == 2.0
