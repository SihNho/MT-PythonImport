"""The Andor iXon Ultra EMCCD through `api.emccd` (owner 2026-10-30: exposure, frame rate, EM gain mode, EM gain and
temperature adjustable, each read back): the real driver on the fake SDK, which is also the simulator."""
import pytest
from test_devices import _rig

from mtpy import api
from mtpy.api.errors import SafetyRefused
from mtpy.devices import ixon


@pytest.fixture
def rig(tmp_path, monkeypatch):
    yield from _rig(tmp_path, monkeypatch, test_limits=True)


def test_emccd_core_parameters_set_and_read_back(rig):
    dev = rig["emccd"].device
    assert isinstance(dev, ixon.SimEmccd)
    st = api.devices.info("emccd")
    assert st["identity"]["model"] == "DU897_BV" and st["identity"]["detector"] == (512, 512)
    assert st["limits"]["em_gain"] == (0, 255) and st["limits"]["temperature_C"] == (-120, 20)
    assert api.emccd.set_gain_mode(3) == 3 and dev.gain_range == (1, 300)
    assert api.emccd.set_gain(100) == 100
    assert api.emccd.set_exposure(30.0) == pytest.approx(30.0)
    assert api.emccd.set_rate(20.0) == pytest.approx(20.0, rel=0.01)
    assert api.emccd.set_temperature(-70) == -70
    s = api.emccd.settings()
    assert s["sensor_temperature_C"] == -70 and s["cooler"] == "stabilized" and s["temperature_C"] == -70


def test_emccd_refusals_and_unreachable_rate(rig):
    with pytest.raises(SafetyRefused, match=r"outside the camera's range \[0, 255\]"):
        api.emccd.set_gain(300)                              # mode 0 range; gain above the range stays locked
    assert api.emccd.set_gain_mode(3) == 3 and api.emccd.set_gain(0) == 0   # 0 = off, allowed below the range
    with pytest.raises(SafetyRefused, match=r"not 0..3"):
        api.emccd.set_gain_mode(4)
    with pytest.raises(SafetyRefused, match=r"outside the camera's range \[-120, 20\]"):
        api.emccd.set_temperature(-150)
    api.emccd.set_exposure(100.0)
    with pytest.raises(SafetyRefused, match=r"shorten the exposure first"):
        api.emccd.set_rate(50.0)
    api.emccd.set_exposure(1.0)
    with pytest.raises(SafetyRefused, match=r"outside \[0.01, 52.9\d+\] Hz"):   # 1 / (1 + 17.9 ms readout)
        api.emccd.set_rate(100.0)
    assert api.emccd.set_rate(50.0) == pytest.approx(50.0, rel=0.01)
    with pytest.raises(SafetyRefused, match=r"lower the rate first"):
        api.emccd.set_exposure(10.0)                         # 20 ms period - 17.9 ms readout = 2.1 ms at most


def test_emccd_preset_reapplied_after_reconnect_and_snap(rig):
    sdk = rig["emccd"].device.sdk
    got = api.emccd.apply_preset({"name": "tirf", "em_gain_mode": 2, "em_gain": 50, "exposure_ms": 30.0,
                                  "rate_Hz": 20.0, "temperature_C": -60})
    assert got["em_gain"] == 50 and got["temperature_C"] == -60
    api.devices.reconnect("emccd")                           # close: cooler off, warm, ShutDown; open re-applies
    assert sdk.shut and not sdk.cooler
    s = api.emccd.settings()
    assert s["em_gain"] == 50 and s["temperature_C"] == -60 and s["cooler"] == "stabilized"
    img = api.emccd.snap()
    assert img.shape == (512, 512) and img.dtype.name == "uint16" and img.max() > 0
    api.emccd.set_exposure(25.0)                             # a set while acquiring: abort, apply, restart
    assert api.emccd.settings()["acquiring"]
    with pytest.raises(ValueError, match="only the fields"):
        api.emccd.apply_preset({"name": "x", "roi": (0, 0, 1, 1)})


def test_emccd_frame_transfer_mode_and_reading_frames(rig):
    sdk = rig["emccd"].device.sdk
    assert api.emccd.set_frame_transfer(1) == 1
    assert rig["emccd"].device.readout_ms == pytest.approx(15.0)
    with pytest.raises(SafetyRefused, match=r"outside \[0.01, 66.6\d+\] Hz"):      # 1 / 15 ms
        api.emccd.set_rate(100.0)
    with pytest.raises(SafetyRefused, match=r"set the rate instead"):
        api.emccd.set_exposure(5.0)
    assert api.emccd.set_rate(50.0) == pytest.approx(50.0, rel=0.01)
    assert api.emccd.settings()["exposure_ms"] == pytest.approx(20.0, rel=0.01)      # exposure = period
    api.emccd.start()
    import time
    time.sleep(0.25)
    first, last, frames = api.emccd.read_new()
    assert first == 1 and last >= 8 and frames.shape == (last, 512, 512)
    time.sleep(0.1)
    first2, last2, _f = api.emccd.read_new()
    assert first2 == last + 1 and api.emccd.total_acquired() >= last2
    api.emccd.stop()
    assert not api.emccd.settings()["acquiring"] and sdk.read_to == last2
    assert api.emccd.set_frame_transfer(0) == 0 and rig["emccd"].device.readout_ms == pytest.approx(17.9)


def test_emccd_shutter_closed_until_start_and_closed_again_at_stop(rig):
    dev = rig["emccd"].device
    assert dev.has_shutter and api.emccd.settings()["shutter"] == 2 and dev.sdk.shutter == 2
    api.emccd.start()
    assert api.emccd.settings()["shutter"] == 1 and dev.sdk.shutter == 1
    api.emccd.stop()
    assert dev.sdk.shutter == 2
    r0 = dev.readout_ms
    assert api.emccd.set_shutter(0) == 0 and dev.readout_ms == pytest.approx(r0 + 100.0)   # auto: transfer times
    with pytest.raises(SafetyRefused, match=r"not 0 \(auto\)"):
        api.emccd.set_shutter(3)
    api.emccd.set_shutter(1)
    sdk = dev.sdk
    rig["emccd"].close()
    assert sdk.shutter == 2 and sdk.shut
