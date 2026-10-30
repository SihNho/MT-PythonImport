"""Decision 0026: the program holds the shared rig lock itself (api.rig), taken by devices.connect for any backend
but `sim`, released by disconnect only after every cleanup succeeded. Against the in-memory FakeRiglock (conftest)."""
import os

import pytest
from test_devices import _config

from mtpy import api
from mtpy.api import estop, events, rig
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
    assert rig.status() == {"held": True, "own": True, "holder": fake_riglock.holder, "rig_state": "assembled"}
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
    assert sorted(st) == ["arduino", "camera", "focus", "magnet", "rotor", "stage"] and api.devices.mode() == "MT"
    api.devices.disconnect()
    assert api.devices.mode() is None
    st = api.devices.connect({"backend": "sim"})
    assert len(st) == 8 and api.devices.mode() == "MT-TIRF"
    api.devices.disconnect()
    with pytest.raises(NotReady, match="mode"):
        api.devices.connect({"backend": "sim", "mode": "FRET"})
