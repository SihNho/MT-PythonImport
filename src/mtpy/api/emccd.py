"""EMCCD (Andor iXon Ultra) settings: the five core parameters the owner asked for on 2026-10-30 - exposure, frame
rate, EM gain mode, EM gain, sensor temperature - each sent, read back and verified like a camera setting
(`mtpy.devices.ixon`). The EMCCD has no acquisition pipeline yet (plan phase 10a); `snap()` grabs one frame.

    api.emccd.apply_preset({"name": "tirf", "exposure_ms": 30.0, "rate_Hz": 20.0, "em_gain": 100, "temperature_C": -70})
    api.emccd.set_exposure(50.0)        # -> 50.0 read back (ms)
"""
from . import events
from ._act import acting
from .devices import service

FIELDS = ("frame_transfer", "shutter", "em_gain_mode", "em_gain", "exposure_ms", "rate_Hz", "temperature_C")   # applied in this order


def _set(name, value, rate_Hz=None, exposure_ms=None):
    svc = service("emccd")
    dev = svc.require()
    s = svc.call(dev.settings, what="read settings")
    rate = s["rate_requested_Hz"] if rate_Hz is None else rate_Hz      # None: no rate requested yet
    exp = s["exposure_ms"] if exposure_ms is None else exposure_ms

    def check(v):
        dev.check_setting(name, v, rate, exp)
        return True
    return acting(f"emccd_{name}", value, lambda v: svc.call(dev.set, name, v, what=f"set {name} {v!r}"),
                  lambda: svc.call(dev.get, name, what=f"read {name}"), dev.tol(name, value), device="emccd",
                  check=check)


def set_frame_transfer(on):
    """0: period = exposure + readout (exposure and rate independent). 1: the exposure overlaps the readout, so the
    exposure equals the frame period and only the rate is set (up to 1 / readout)."""
    return _set("frame_transfer", on)


def set_shutter(mode):
    """Internal shutter 0 auto (the SDK adds both 50 ms transfer times to every frame), 1 open, 2 closed. start()
    opens it and stop() / disconnect close it, as the LabVIEW program did (owner 2026-10-30)."""
    return _set("shutter", mode)


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


def exercise_shutter(cycles=100, pause_s=0.1):
    """Cycle the internal shutter open / closed `cycles` times, `pause_s` after each call (owner 2026-10-30: the
    blade was stiff after long disuse and freed up under cycling); stops at the first SDK error; the shutter is
    left closed. Returns {"calls_ok", "cycles", "stopped_at"}."""
    svc = service("emccd")
    r = svc.call(svc.require().cycle_shutter, cycles, pause_s, what=f"exercise shutter {cycles} x {pause_s} s",
                 timeout_s=2.0 * cycles * pause_s + 30.0)
    events.log("emccd_shutter_exercise", device="emccd", **r)
    return r


def start():
    """Shutter open, then the run-till-abort acquisition into the SDK's circular buffer (read it with read_new())."""
    svc = service("emccd")
    svc.call(svc.require().start_acquisition, what="start acquisition")


def stop():
    svc = service("emccd")
    svc.call(svc.require().stop_acquisition, what="stop acquisition")


def read_new():
    """(first, last, frames n x h x w uint16) not yet read, or None; a jump in first over the last read = loss."""
    svc = service("emccd")
    return svc.call(svc.require().read_new, what="read new frames")


def total_acquired():
    svc = service("emccd")
    return svc.call(svc.require().total_acquired, what="frames acquired")


def snap():
    """One frame (uint16 array h x w) from the EMCCD: the acquisition is started if it is not running."""
    svc = service("emccd")
    return svc.call(svc.require().snap, what="snap", timeout_s=15.0)


def catalogue():
    """The EMCCD's settings as a catalogue like api.camera.catalogue() (owner 2026-11-04: the same panel for both
    cameras): frame transfer, shutter, exposure, rate, EM gain mode and gain, temperature, with the ranges the device
    reports. The SDK is not attribute-based, so this is the program's table; a setting outside it is set by code."""
    svc = service("emccd")
    dev = svc.require()
    lim = svc.call(dev.limits, what="limits")
    gain = lim.get("em_gain") if isinstance(lim.get("em_gain"), (tuple, list)) else (0, 1000)
    temp = lim.get("temperature_C") if isinstance(lim.get("temperature_C"), (tuple, list)) else (-120, 20)
    rows = [
        {"name": "frame_transfer", "category": "Readout", "type": "enum", "values": [0, 1], "description": str(lim.get("frame_transfer", ""))},
        {"name": "shutter", "category": "Readout", "type": "enum", "values": [0, 1, 2], "description": str(lim.get("shutter", ""))},
        {"name": "exposure_ms", "category": "Acquisition", "type": "float", "min": 0.001, "max": 100000.0, "step": 1.0, "description": str(lim.get("exposure_ms", ""))},
        {"name": "rate_Hz", "category": "Acquisition", "type": "float", "min": 0.01, "max": 1000.0, "step": 1.0, "description": str(lim.get("rate_Hz", ""))},
        {"name": "em_gain_mode", "category": "Gain", "type": "enum", "values": [0, 1, 2, 3], "description": str(lim.get("em_gain_mode", ""))},
        {"name": "em_gain", "category": "Gain", "type": "int", "min": int(gain[0]), "max": int(gain[1]), "step": 1, "description": "EM gain in the mode's unit"},
        {"name": "temperature_C", "category": "Cooling", "type": "int", "min": int(temp[0]), "max": int(temp[1]), "step": 1, "description": "set-point; the cooler runs towards it"},
    ]
    for r in rows:
        r.update(access="rw", visibility="beginner")
    return rows


def get_attribute(name):
    return settings()[name]


_SETTERS = {"frame_transfer": lambda v: set_frame_transfer(int(v)), "shutter": lambda v: set_shutter(int(v)),
            "exposure_ms": set_exposure, "rate_Hz": set_rate, "em_gain_mode": lambda v: set_gain_mode(int(v)),
            "em_gain": lambda v: set_gain(int(v)), "temperature_C": lambda v: set_temperature(int(v))}


def set_attribute(name, value, confirm=False):
    """Write one catalogue entry through its setter (each reads back); confirm is accepted for the panel's sake."""
    if name not in _SETTERS:
        raise ValueError(f"emccd has no attribute {name!r}; the catalogue has {sorted(_SETTERS)}")
    return _SETTERS[name](value)
