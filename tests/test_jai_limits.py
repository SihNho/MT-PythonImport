"""The real camera's frame-rate cap follows the driver's maximum at the ROI in force (owner 2026-11-01: the maximum
rate of a half-size ROI); without a session it is the simulator's single cap."""
import pytest

from mtpy.api.errors import SafetyRefused
from mtpy.devices.jai import JaiCamera
from mtpy.devices.sim.camera import RATE_MAX_HZ


def test_rate_cap_is_the_drivers_maximum_when_known():
    cam = JaiCamera()
    cam._rate_max = 480.0                       # what settings() reads from IMAQdxGetAttributeMaximum at 640 x 512
    cam.check_setting("rate_Hz", 400.0, 90.0, 1.9)
    assert cam.limits()["rate_Hz"] == (1.0, 480.0)
    with pytest.raises(SafetyRefused):
        cam.check_setting("rate_Hz", 500.0, 90.0, 1.9)
    with pytest.raises(SafetyRefused):             # the exposure must still fit the frame period
        cam.check_setting("rate_Hz", 400.0, 90.0, 3.0)


def test_rate_cap_is_the_simulators_without_a_session():
    cam = JaiCamera()
    assert cam.limits()["rate_Hz"] == (1.0, RATE_MAX_HZ)
    with pytest.raises(SafetyRefused):
        cam.check_setting("rate_Hz", 400.0, 90.0, 1.9)
