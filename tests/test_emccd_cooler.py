"""The iXon cooler as the rig showed it on 2026-10-30: CoolerOFF does nothing, the set point does; a camera left
cooling by a previous owner is adopted at open; a warm-up that does not move fails fast."""
import pytest

from mtpy.devices import ixon


def _open(fake):
    dev = ixon.SimEmccd()
    dev.sdk_factory = lambda: fake
    dev.open()
    return dev


def test_camera_found_cooling_is_adopted_and_warmed_through_the_set_point():
    fake = ixon.FakeAndor()
    fake.cooler, fake.set_c = True, -80                  # what LabVIEW left behind
    dev = _open(fake)
    assert dev.identity()["found_at_open"] == {"sensor_temperature_C": -80, "cooler": "stabilized"}
    assert dev.settings()["temperature_C"] == -80 and dev.cooler_on
    n = len(fake.calls)
    dev.close()
    tail = fake.calls[n:]
    i = tail.index("SetTemperature")
    assert fake.set_c == 20 and tail[i + 1] == "CoolerON" and tail[-2:] == ["CoolerOFF", "ShutDown"]
    assert fake.shut and dev.sdk is None


def test_warm_up_that_does_not_move_fails_fast_without_shutdown():
    fake = ixon.FakeAndor()
    dev = _open(fake)
    assert "found_at_open" in dev.identity() and dev.settings()["temperature_C"] is None   # warm camera: nothing adopted
    fake.stuck_c, dev.stall_s = -80, 0.0
    with pytest.raises(TimeoutError, match=r"did not warm up within 0 s of SetTemperature\(20\) \+ CoolerON"):
        dev.close()
    assert not fake.shut and dev.sdk is not None        # D1: the handle is kept for the retry, no Initialize again
    fake.stuck_c = None
    n = len(fake.calls)
    dev.close()
    assert fake.shut and dev.sdk is None and "Initialize" not in fake.calls[n:]
