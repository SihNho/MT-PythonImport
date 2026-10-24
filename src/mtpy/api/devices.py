"""Device connection and status (docs/design/api.md 2.2; ui-requirements U8).

`connect(rig_preset)` builds and opens every device of the rig preset, each owned by its own DeviceService thread.
Only `{"backend": "sim"}` exists (optionally `"fixture": <folder of img*.tif>` for the simulated camera); real
backends raise NotImplementedError until phases 6/7. Example:

    api.devices.connect({"backend": "sim"})
    api.devices.status()["magnet"]["state"]      # 'connected'
"""
from mtpy import devices as _devices

from . import events
from ._act import acting, precheck
from .errors import DeviceError, NotReady

_services = {}


def connect(rig_preset):
    """Open every device of the rig preset; a device that fails to open stays listed with its error (U8). Returns
    status(). NotReady if already connected; NotImplementedError for a backend other than 'sim'."""
    if _services:
        raise NotReady("devices are already connected; api.devices.disconnect() first")
    built = _devices.make(rig_preset)
    for name, dev in built.items():
        _services[name] = svc = _devices.DeviceService(dev)
        try:
            svc.open()
        except DeviceError:
            pass                                    # recorded in svc.status(); reconnect(name) retries
    events.log("devices", action="connect", backend=rig_preset.get("backend"))
    return status()


def disconnect():
    """Close every device and end the service threads (end of session; the session-start origins are dropped)."""
    try:
        for svc in _services.values():
            try:
                svc.shutdown()
            except DeviceError:
                pass
    finally:
        _services.clear()
        events.log("devices", action="disconnect")


def service(name):
    """The DeviceService of `name` (internal to the device functions)."""
    if name not in _services:
        raise NotReady(f"device {name!r} is not available: call api.devices.connect(rig_preset) first"
                       if not _services else f"no device {name!r}; devices: {sorted(_services)}")
    return _services[name]


def status():
    """{device: {state: connected | disconnected | error | slow, last_reply_t, last_reply_ms, last_error}} (U8)."""
    return {name: svc.status() for name, svc in _services.items()}


def info(name):
    """Identity, settings read back, controller limits, rig-safety-profile limits, calibration in use, session-start
    origin, recent errors (U8 details; read-only)."""
    from . import safety
    svc = service(name)
    d = svc.info()
    lim = safety.profile()["limits"]
    d["profile_limits"] = {q: safety._thaw(lim[q]) for q in svc.device.quantities if q in lim}
    return d


def reconnect(name):
    """Close and reopen one device without restarting the program, then re-apply what an open resets (the camera's
    last preset, U15). Returns its status()."""
    svc = service(name)
    svc.reconnect()
    events.log("device", device=name, action="reconnect")
    if svc.reapply is not None:
        svc.reapply()
    return svc.status()


def self_check():
    """{device: [{step: open | reply | read, ok, detail}]}; each device stops at its first failed step (U8)."""
    return {name: svc.self_check() for name, svc in _services.items()}


def _move(name, quantity, value, read, send=None, origin=None, check=None, match=None):
    """Start a Motion: refuse at once (caller's thread) if e-stopped or outside the profile, then on the motion thread
    send, wait for arrival, read back and compare through acting()."""
    svc = service(name)
    dev = svc.require()
    precheck(quantity, value, dev.tol, origin, check)
    send = send or (lambda v: svc.call(dev.move_to, v, what=f"move to {v!r}"))

    def body(motion):
        def readback():
            motion.wait_arrival(dev.moving)
            return svc.call(read, what="position")
        return acting(quantity, value, send, readback, dev.tol, origin, name, check, match)
    return _devices.Motion(svc, body, what=f"{name} move to {value!r}")
