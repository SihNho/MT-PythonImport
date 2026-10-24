"""Camera settings (JAI SP-5000M-USB): immediate (exposure, gain) and "needs a short pause" (rate, ROI) kinds (U17),
presets applied with read-back (U15).

    api.camera.apply_preset({"name": "tracking 150 Hz", "rate_Hz": 150.0, "exposure_ms": 5.0})
    api.camera.set_exposure(4.0)        # -> 4.0 read back (ms)

Rate and ROI change how data are read: while recording they need confirm=True and log a `guarded_change` event.
While acquiring they stop acquisition, apply, read back and restart; if the read-back fails, acquisition stays
stopped (U15: a mismatch is shown and acquisition does not start).
"""
from mtpy.devices import NEEDS_PAUSE

from . import acq, events
from ._act import acting, precheck
from .devices import service
from .errors import SafetyRefused

PRESET_FIELDS = ("roi", "rate_Hz", "exposure_ms", "gain_dB")


def _guard(svc, dev, names, value, confirm):
    guarded = [n for n in names if dev.settings_kinds[n][1]]
    if guarded and svc.recording:
        if not confirm:
            events.log("refused", request={"camera": dict(value) if isinstance(value, dict) else value},
                       reason=f"{guarded} change how data are read; confirm=True needed while recording")
            raise SafetyRefused(f"camera {guarded} change how data are read; while recording pass confirm=True")
        events.log("guarded_change", device="camera", settings=guarded, value=value)


def _run(svc, dev, names, act):
    """Run act() inside a pause when a 'needs a short pause' setting changes during acquisition."""
    if not (any(dev.settings_kinds[n][0] == NEEDS_PAUSE for n in names)
            and svc.call(dev.acquiring, what="acquiring?")):
        return act()
    svc.call(dev.stop_acquisition, what="stop acquisition")
    acq._camera_paused()                            # WP3: close the segment (frames still buffered are taken first)
    events.log("acquisition", device="camera", action="pause", settings=list(names))
    got = act()                                     # raises -> acquisition stays stopped
    acq._camera_restarting(svc.call(dev.settings, what="read settings"))   # next segment, settings read back
    svc.call(dev.start_acquisition, what="start acquisition")
    events.log("acquisition", device="camera", action="restart")
    return got


def _set(name, value, confirm=False):
    svc = service("camera")
    dev = svc.require()
    s = svc.call(dev.settings, what="read settings")

    def check(v):
        dev.check_setting(name, v, s["rate_Hz"], s["exposure_ms"])
        return True
    quantity, tol = f"camera_{name}", dev.tol(name, value)
    match = (lambda got: tuple(got) == tuple(value)) if name == "roi" else None
    precheck(quantity, value, tol, check=check)     # refuse before anything stops
    _guard(svc, dev, [name], value, confirm)
    return _run(svc, dev, [name], lambda: acting(
        quantity, value, lambda v: svc.call(dev.set, name, v, what=f"set {name} {v!r}"),
        lambda: svc.call(dev.get, name, what=f"read {name}"), tol, device="camera", check=check, match=match))


def set_exposure(exposure_ms):
    """Exposure in ms (1 us steps), immediate; must not exceed the frame period. Returns the read-back."""
    return _set("exposure_ms", exposure_ms)


def set_gain(gain_dB):
    """Gain in dB, immediate. Returns the read-back."""
    return _set("gain_dB", gain_dB)


def set_rate(rate_Hz, confirm=False):
    """Frame rate in Hz (frame period in 1 us steps, so 150 reads back 149.9925); needs a short pause. Returns the
    read-back."""
    return _set("rate_Hz", rate_Hz, confirm)


def set_roi(x, y, w, h, confirm=False):
    """ROI in binned pixels (w step 8, h step 2, inside 1280 x 1024); needs a short pause. Returns the read-back."""
    return _set("roi", (x, y, w, h), confirm)


def apply_preset(preset, confirm=False):
    """Apply a camera preset, read every field back and verify (U15); DeviceError on a mismatch. Returns the
    read-back values. The preset is remembered and re-applied after every reconnect (the JAI resets on open).

    preset: {"name": str, and any of "roi": (x, y, w, h), "rate_Hz", "exposure_ms", "gain_dB"}. Until api.presets
    exists (later WP) the preset content is passed, not its name. Example:
    `api.camera.apply_preset({"name": "tracking 150 Hz", "rate_Hz": 150.0, "exposure_ms": 5.0})`.
    """
    svc = service("camera")
    dev = svc.require()
    extra = set(preset) - set(PRESET_FIELDS) - {"name"}
    values = {k: tuple(preset[k]) if k == "roi" else preset[k] for k in PRESET_FIELDS if k in preset}
    s = svc.call(dev.settings, what="read settings")
    rate, exp = values.get("rate_Hz", s["rate_Hz"]), values.get("exposure_ms", s["exposure_ms"])

    def check(v):
        if extra or not isinstance(preset.get("name"), str):
            raise SafetyRefused(f"camera preset needs a 'name' and only the fields {PRESET_FIELDS}; got {sorted(preset)}")
        for k, x in v.items():
            dev.check_setting(k, x, rate, exp)
        return True

    shorter = isinstance(exp, (int, float)) and exp <= s["exposure_ms"]
    order = ["roi"] + (["exposure_ms", "rate_Hz"] if shorter else ["rate_Hz", "exposure_ms"]) + ["gain_dB"]

    def do(v):
        for k in order:
            if k in v:
                svc.call(dev.set, k, v[k], what=f"set {k} {v[k]!r}")

    def readback():
        got = svc.call(dev.settings, what="read settings")
        return {k: got[k] for k in values}

    def match(got):
        return all(got[k] == v if k == "roi" else abs(got[k] - v) <= dev.tol(k, v) for k, v in values.items())

    precheck("camera_preset", values, check=check)
    _guard(svc, dev, list(values), values, confirm)
    got = _run(svc, dev, list(values), lambda: acting("camera_preset", values, do, readback, 0.0, device="camera",
                                                       check=check, match=match))
    svc.reapply = lambda: apply_preset(preset, confirm=True)
    events.log("preset", device="camera", name=preset["name"], readback=got)
    return got
