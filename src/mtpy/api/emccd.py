"""EMCCD (Andor iXon Ultra) settings: the five core parameters the owner asked for on 2026-10-30 - exposure, frame
rate, EM gain mode, EM gain, sensor temperature - each sent, read back and verified like a camera setting
(`mtpy.devices.ixon`). The EMCCD has no acquisition pipeline yet (plan phase 10a); `snap()` grabs one frame.

    api.emccd.apply_preset({"name": "tirf", "exposure_ms": 30.0, "rate_Hz": 20.0, "em_gain": 100, "temperature_C": -70})
    api.emccd.set_exposure(50.0)        # -> 50.0 read back (ms)
"""
from . import events
from ._act import acting
from .devices import service

FIELDS = ("em_gain_mode", "em_gain", "exposure_ms", "rate_Hz", "temperature_C")      # the order they are applied in


def _set(name, value, rate_Hz=None, exposure_ms=None):
    svc = service("emccd")
    dev = svc.require()
    s = svc.call(dev.settings, what="read settings")
    rate = s["rate_Hz"] if rate_Hz is None else rate_Hz
    exp = s["exposure_ms"] if exposure_ms is None else exposure_ms

    def check(v):
        dev.check_setting(name, v, rate, exp)
        return True
    return acting(f"emccd_{name}", value, lambda v: svc.call(dev.set, name, v, what=f"set {name} {v!r}"),
                  lambda: svc.call(dev.get, name, what=f"read {name}"), dev.tol(name, value), device="emccd",
                  check=check)


def set_exposure(exposure_ms):
    """Exposure in ms; must not exceed the frame period. Returns the read-back (the SDK's real exposure)."""
    return _set("exposure_ms", exposure_ms)


def set_rate(rate_Hz):
    """Frame rate in Hz (kinetic cycle 1 / rate). A rate the camera cannot reach reads back lower -> DeviceError."""
    return _set("rate_Hz", rate_Hz)


def set_gain_mode(mode):
    """EM gain mode 0 = 8 bit DAC, 1 = 12 bit DAC, 2 = linear, 3 = real EM gain; the gain range follows the mode."""
    return _set("em_gain_mode", mode)


def set_gain(em_gain):
    """EM gain within the camera's range for the mode in force (gain above the range stays locked)."""
    return _set("em_gain", em_gain)


def set_temperature(temperature_C):
    """Cooling set point in deg C (integer) and cooler on. The sensor temperature is in settings()."""
    return _set("temperature_C", temperature_C)


def settings():
    """Read back: the five settings plus sensor_temperature_C, cooler status and acquiring."""
    svc = service("emccd")
    return svc.call(svc.require().settings, what="read settings")


def apply_preset(preset):
    """Apply {"name": str, and any of FIELDS} in the order gain mode, gain, exposure, rate, temperature; each is read
    back and verified (U15). Remembered and re-applied after a reconnect. Returns the read-back values."""
    extra = set(preset) - set(FIELDS) - {"name"}
    if extra or not isinstance(preset.get("name"), str):
        raise ValueError(f"emccd preset needs a 'name' and only the fields {FIELDS}; got {sorted(preset)}")
    svc = service("emccd")
    got = {k: _set(k, preset[k], preset.get("rate_Hz"), preset.get("exposure_ms")) for k in FIELDS if k in preset}
    svc.reapply = lambda: apply_preset(preset)
    svc.preset = dict(preset)
    events.log("preset", device="emccd", name=preset["name"], readback=got)
    return got


def snap():
    """One frame (uint16 array h x w) from the EMCCD: the acquisition is started if it is not running."""
    svc = service("emccd")
    return svc.call(svc.require().snap, what="snap", timeout_s=15.0)
