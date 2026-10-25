"""Decision 0019: a magnet stall (PI error -1024, servo off) on the simulated PI magnet: detection after a move and on
the acquisition poller, the one-shot return to 0 mm, the lock when it fails, the e-stop interplay and the run-file
record. No hardware."""
import time

import pytest
from test_acq import _connect
from test_devices import SYNTHETIC_TABLE, _rig

from mtpy import api
from mtpy.api import estop, events
from mtpy.api.errors import MagnetStall, NotReady
from mtpy.data import read_run
from mtpy.protocol import parse

HEAD = 'grammar 0.1\nprotocol "t"\n'


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(api.protocol, "_engine", None)
    gen = _rig(tmp_path, monkeypatch, test_limits=True)
    yield next(gen)["magnet"].device
    if api.protocol.running():
        api.protocol.stop()
        api.protocol.wait(10)
    next(gen, None)


@pytest.fixture
def cam(tmp_path, monkeypatch):
    monkeypatch.setattr(api.protocol, "_engine", None)
    gen = _connect(tmp_path, monkeypatch)
    next(gen)
    yield api.devices.service("magnet").device
    if api.protocol.running():
        api.protocol.stop()
        api.protocol.wait(10)
    next(gen, None)


def _stalls(n):
    return [e for e in events.events()[n:] if e.kind == "magnet_stall"]


def _until(cond, timeout_s=15.0):
    t_end = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < t_end, "condition not reached"
        time.sleep(0.02)


def test_no_stall_nothing_changes(rig):
    n = len(events.events())
    assert api.magnet.move_to(5.0).wait(5) == pytest.approx(5.0, abs=0.01)
    assert api.magnet.check_stall() is None
    assert api.magnet.stall_status() == {"locked": None, "last": None, "count": 0} and not _stalls(n)


def test_stall_during_a_move_returns_to_zero_and_raises(rig):
    n = len(events.events())
    rig.inject_stall(at_mm=4.0)
    m = api.magnet.move_to(10.0)
    with pytest.raises(MagnetStall, match="returned to 0 mm, verified") as e:
        m.wait(20)
    rec = e.value.record
    assert rec["position_mm"] == pytest.approx(4.0, abs=0.01) and rec["controller_error"] == -1024
    assert rec["return_attempted"] and rec["return_verified"] and not rec["locked"]
    assert abs(rec["position_after_mm"]) <= 0.01 and api.magnet.position() == pytest.approx(0.0, abs=0.01)
    [ev] = _stalls(n)
    assert ev.extra["level"] == "error" and ev.extra["return_verified"] is True and ev.readback == rec["position_mm"]
    assert api.magnet.move_to(2.0).wait(5) == pytest.approx(2.0, abs=0.01)      # not locked: moves go on


def test_stall_with_failing_return_locks_the_magnet_until_cleared(rig):
    n = len(events.events())
    rig.fail_servo_on = True
    rig.inject_stall(at_mm=3.0)
    with pytest.raises(MagnetStall, match="NOT verified") as e:
        api.magnet.move_to(8.0).wait(20)
    rec = e.value.record
    assert rec["return_attempted"] and not rec["return_verified"] and rec["locked"]
    assert "servo did not switch on" in rec["reason"]
    assert [x.extra["return_verified"] for x in _stalls(n)] == [False]
    assert api.magnet.position() == pytest.approx(3.0, abs=0.01)                # nothing moved after the stall
    with pytest.raises(NotReady, match="locked after a stall"):
        api.magnet.move_to(1.0)
    api.magnet.use_force_table(SYNTHETIC_TABLE)
    with pytest.raises(NotReady, match="locked after a stall"):
        api.magnet.set_force(1.0)
    with pytest.raises(MagnetStall, match="NOT verified"):                     # the user's clear fails the same way
        api.magnet.clear_stall()
    assert api.magnet.stall_status()["locked"] is not None
    rig.fail_servo_on = False
    st = api.magnet.clear_stall()                                               # explicit user action
    assert st["locked"] is None and api.magnet.position() == pytest.approx(0.0, abs=0.01)
    assert [x.extra["result"] for x in events.events()[n:] if x.kind == "magnet_stall_clear"] == ["failed", "cleared"]
    assert api.magnet.move_to(1.0).wait(5) == pytest.approx(1.0, abs=0.01)


def test_position_not_valid_after_stall_flag_locks_without_a_return(rig):
    rig.position_valid_after_stall = False
    rig.inject_stall(at_mm=2.0)
    with pytest.raises(MagnetStall) as e:
        api.magnet.move_to(6.0).wait(20)
    assert not e.value.record["return_attempted"] and e.value.record["locked"]
    assert "reference move" in e.value.record["reason"]
    assert api.magnet.position() == pytest.approx(2.0, abs=0.01)


def test_stall_during_estop_no_return_until_the_user_clears(rig):
    api.magnet.move_to(3.0).wait(5)
    with events.as_caller("gui"):
        estop.engage("test")
    rig.inject_stall()
    with pytest.raises(MagnetStall) as e:
        api.magnet.check_stall()
    rec = e.value.record
    assert not rec["return_attempted"] and rec["locked"] and "emergency stop engaged" in rec["reason"]
    assert api.magnet.position() == pytest.approx(3.0, abs=0.01)
    with pytest.raises(NotReady, match="emergency stop"):
        api.magnet.clear_stall()
    with events.as_caller("gui"):
        estop.clear()
    time.sleep(0.1)
    assert api.magnet.position() == pytest.approx(3.0, abs=0.01)                # no return by itself after release
    with pytest.raises(NotReady, match="locked after a stall"):
        api.magnet.move_to(1.0)
    assert api.magnet.clear_stall()["locked"] is None
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)


def test_stall_during_a_protocol_move_aborts_returns_and_is_recorded(cam, tmp_path):
    api.magnet.use_force_table(SYNTHETIC_TABLE)                 # 1 pN at 10 mm
    api.acq.start(record=True, name="stall", folder=tmp_path)
    n = len(events.events())
    cam.inject_stall(at_mm=5.0)
    api.protocol.run(parse(HEAD + 'hold f=1 t=0.2\nmark "never"\n', "s.mtprot"))
    st = api.protocol.wait(30)
    assert st["state"] == "aborted" and "magnet stall" in st["reason"], st
    _until(lambda: _stalls(n))
    [ev] = _stalls(n)
    assert ev.extra["return_verified"] is True and ev.extra["position_mm"] == pytest.approx(5.0, abs=0.01)
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)
    assert not [e for e in events.events()[n:] if e.kind == "mark"]
    assert api.acq.stop()["sink_failures"] == 0
    run = read_run(tmp_path / "stall.h5")
    assert run["attrs"]["magnet_stalls"] == 1
    rec = run["events"]["magnet_stall"]["data"][0]
    assert rec["controller_error"] == -1024 and rec["return_verified"] is True and rec["level"] == "error"


def test_poller_catches_a_stall_while_idle(cam, tmp_path):
    api.magnet.move_to(4.0).wait(5)
    api.acq.start(record=True, name="idle", folder=tmp_path)
    api.acq.wait_frames(5, 5)
    n = len(events.events())
    cam.inject_stall()                                          # no move running: only the poller can see it
    _until(lambda: _stalls(n))
    [ev] = _stalls(n)
    assert ev.extra["detected_by"] == "poll" and ev.extra["return_verified"] is True
    assert ev.extra["position_mm"] == pytest.approx(4.0, abs=0.01)
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)
    api.acq.stop()
    assert read_run(tmp_path / "idle.h5")["attrs"]["magnet_stalls"] == 1
