"""The project's motion gate (phase 7, docs/design/motion-gate.md) against the fake controllers: limits set and read
back at open, refusals before anything is written, the magnet home before the release, the lock check."""
import pytest
from fake_controllers import FakeAsi, FakePi, FakeRotor

from mtpy.api import safety
from mtpy.devices import asi, autonics, gate, pi
from mtpy.devices.gate import Line

LIMITS = {"magnet_position_mm": {"min": 0.0, "max": 39.0, "relative_to": None, "verified": True},
          "stage_x_mm": {"min": -2.0, "max": 2.0, "relative_to": "session_start", "verified": True},
          "stage_y_mm": {"min": -2.0, "max": 2.0, "relative_to": "session_start", "verified": True},
          "rotor_turns": {"min": -5.0, "max": 5.0, "relative_to": "session_start", "verified": False}}


@pytest.fixture(autouse=True)
def _rig(monkeypatch):
    monkeypatch.setattr(gate, "permitted", lambda what="": None)
    monkeypatch.setattr(safety, "profile", lambda: {"limits": {k: {"unit": "", "source": "", **v}
                                                               for k, v in LIMITS.items()}})
    monkeypatch.setattr(pi.time, "sleep", lambda s: None)
    monkeypatch.setattr(autonics.time, "sleep", lambda s: None)


def _pi(**kw):
    ctl = FakePi(**kw)
    return ctl, pi.PiMagnet(line=Line(ctl, b"\n", 0.1))


def test_pi_open_sets_limits_references_and_verifies():
    ctl, dev = _pi()
    dev.open()
    assert (ctl.tmn, ctl.tmx) == (0.0, 39.0) and ctl.frf == 1 and ctl.svo == 1
    assert "FNL 1" in ctl.log and "MOV 1 2" in ctl.log and ctl.pos == 0.0
    assert dev.position() == 0.0 and dev.speed() == 15.0
    dev.move_to(5.0)
    assert ctl.pos == 5.0 and not dev.moving()


def test_pi_refuses_outside_limits_before_writing_and_controller_refuses_too():
    ctl, dev = _pi()
    dev.open()
    n = len(ctl.log)
    with pytest.raises(ValueError, match="ERR 7"):
        dev.move_to(40.0)
    assert not any(c.startswith("MOV") for c in ctl.log[n:])
    ctl.tmx = 52.0                     # someone changed the controller limit behind the gate's back
    with pytest.raises(ValueError, match="not the session's"):
        dev.move_to(5.0)
    ctl.tmx = 39.0
    ctl.frf = 0
    with pytest.raises(ValueError, match="not referenced"):
        dev.move_to(5.0)


def test_pi_close_homes_then_releases_and_a_failed_home_releases_nothing():
    ctl, dev = _pi()
    dev.open()
    dev.move_to(30.0)
    dev.close()
    assert ctl.pos == 0.0 and (ctl.tmn, ctl.tmx) == (0.0, 52.0) and ctl.closed
    ctl, dev = _pi()
    dev.open()
    dev.move_to(30.0)
    real = ctl.handle

    def stuck(c):          # the MOV is accepted but the axis does not arrive
        if c.startswith("MOV"):
            return None
        return real(c)
    ctl.handle = stuck
    with pytest.raises(ConnectionError, match="NOT released"):
        dev.close()
    assert (ctl.tmn, ctl.tmx) == (0.0, 39.0)


def test_pi_stop_and_speed_write():
    ctl, dev = _pi()
    dev.open()
    dev.move_to(3.0, speed=10.0)
    assert ctl.vel == 10.0 and "VEL 1 10" in ctl.log
    dev.stop()
    assert ctl.halted == 1


def test_pi_open_needs_a_verified_profile_limit(monkeypatch):
    monkeypatch.setattr(safety, "profile", lambda: {"limits": {"magnet_position_mm": {**LIMITS["magnet_position_mm"], "verified": False}}})
    ctl, dev = _pi()
    with pytest.raises(PermissionError):
        dev.open()
    assert ctl.log == []


def test_lock_required_before_any_port(monkeypatch):
    monkeypatch.delenv("RIGLOCK_TOKEN", raising=False)
    monkeypatch.undo()
    ctl = FakePi()
    with pytest.raises(PermissionError, match="RIGLOCK_TOKEN"):
        pi.PiMagnet(line=Line(ctl, b"\n", 0.1)).open()
    assert ctl.log == []


def _asi():
    ctl = FakeAsi()
    line = Line(ctl, b"\r", 0.1)
    line.eol_in = b"\r\n"
    return ctl, asi.AsiStage(line=line), asi.AsiFocus(line=line)


def test_asi_stage_window_set_relative_and_released():
    ctl, st, _ = _asi()
    st.open()
    assert ctl.sl["X"] == pytest.approx(-1.8475 - 2.0) and ctl.su["Y"] == pytest.approx(-2.7744 + 2.0)
    assert st.position() == pytest.approx((-1.8475, -2.7744))
    st.move_to((-1.5, -2.5))
    assert ctl.p["X"] == -15000 and ctl.p["Y"] == -25000 and not st.moving()
    n = len(ctl.log)
    with pytest.raises(ValueError, match="outside the controller window"):
        st.move_to((1.0, -2.5))
    assert not any(c.startswith("M ") for c in ctl.log[n:])
    ctl.su["X"] = 10.0
    with pytest.raises(ValueError, match="not the session's"):
        st.move_to((-1.5, -2.5))
    ctl.su["X"] = -1.8475 + 2.0
    st.close()
    assert ctl.sl["X"] == -500.0 and ctl.su["Y"] == 500.0


def test_asi_focus_reads_the_controller_z_window_and_never_writes_it():
    ctl, _, fz = _asi()
    fz.open()
    assert fz.window == (-500.0, 500.0) and fz.position() == 10.0
    fz.move_to(20.0)
    assert ctl.p["Z"] == 200.0 and "M Z=200" in ctl.log
    with pytest.raises(ValueError, match="outside"):
        fz.move_to(100.0)
    assert not any(c.startswith(("SL Z=", "SU Z=")) for c in ctl.log)
    fz.stop()
    assert ctl.halted == 1
    fz.close()


def _rotor(pos=-10):
    ctl = FakeRotor(pos)
    line = Line(ctl, b"\r", 0.1)
    line.eol_in = b"\r"
    return ctl, autonics.AutonicsRotor(line=line)


def test_rotor_signed_hex_window_and_refusals():
    ctl, r = _rotor(-10)
    r.open()
    assert r.window == (-2510, 2490) and r.position() == pytest.approx(-0.02)
    r.move_to(2.0)
    assert ctl.pos == 1000 and ctl.spd == 100 and ctl.log[-2:] == ["SPD 100", "PAB 1000"]
    n = len(ctl.log)
    with pytest.raises(ValueError, match="outside the session window"):
        r.move_to(5.0)                    # 2500 > 2490
    assert not any(c.startswith("PAB") for c in ctl.log[n:])
    assert not r.moving()
    r.stop()
    assert ctl.stopped == 1
    r.close()
    assert ctl.closed
