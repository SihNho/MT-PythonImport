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


def test_catalogue_ranges_follow_the_camera(monkeypatch):
    """Owner 2026-11-13: the frame-rate maximum in the settings panel stayed at the full frame's after the ROI was
    halved; the ranges are read at every catalogue() call, the attribute list once."""
    from mtpy.devices import jai

    class Fake:
        rate_max, listed = 248.0, 0

        def attributes(self, root, vis=None):
            Fake.listed += 1
            return [("CameraAttributes::AcquisitionControl::AcquisitionFrameRate", jai.F64, True, True)]

        def text(self, fn, name):
            return ""

        def limit(self, fn, name, t):
            return {"IMAQdxGetAttributeMinimum": 1.0, "IMAQdxGetAttributeMaximum": self.rate_max}.get(fn, 0.0)

    cam = JaiCamera()
    cam.cam = Fake()
    assert cam.catalogue()[0]["max"] == 248.0
    n = Fake.listed
    Fake.rate_max = 555.0                         # what the driver answers once the ROI is 640 x 512
    assert cam.catalogue()[0]["max"] == 555.0 and Fake.listed == n
