"""Device connection and status (docs/design/api.md 2.2; ui-requirements U8).

`connect(rig_preset)` builds and opens every device of the rig preset, each owned by its own DeviceService thread.
Only `{"backend": "sim"}` exists (optionally `"fixture": <folder of img*.tif>` for the simulated camera); real
backends raise NotImplementedError until phases 6/7. Example:

    api.devices.connect({"backend": "sim"})
    api.devices.status()["magnet"]["state"]      # 'connected'
"""
from mtpy import devices as _devices

from . import estop, events, rig
from ._act import acting, precheck
from .errors import DeviceError, NotReady

_services = {}
CLOSE_ORDER = ("magnet", "rotor", "stage", "focus", "emccd", "camera", "arduino", "light")   # docs/design/shutdown.md
# Owner 2026-10-30: "MT, MT-TIRF 모드 구분이 필요함". MT = tracking alone (the JAI, the motors, the sync box);
# MT-TIRF = everything (plan phase 10a: the iXon, the lasers / light gating). The mode chooses which devices a
# connect opens and is written into every run file; the default keeps today's behaviour.
MODES = {"MT": ("camera", "magnet", "rotor", "stage", "focus", "arduino"), "MT-TIRF": _devices.NAMES}
DEFAULT_MODE = "MT-TIRF"
_mode = None


def connect(rig_preset):
    """Open every device of the rig preset; a device that fails to open stays listed with its error (U8). Returns
    status(). NotReady if already connected; NotImplementedError for a backend other than 'sim'."""
    global _mode
    if _services:
        raise NotReady("devices are already connected; api.devices.disconnect() first")
    backend = rig_preset.get("backend")
    mode = rig_preset.get("mode", DEFAULT_MODE)
    if mode not in MODES:
        raise NotReady(f"mode {mode!r} does not exist; use one of {sorted(MODES)}")
    if backend != "sim":
        rig.acquire(f"mtpy {backend}")             # decision 0026: the program holds the rig lock itself
    try:
        built = _devices.make(rig_preset)
    except Exception:
        rig.release()
        raise
    _mode = mode
    for name, dev in built.items():
        if name not in MODES[mode]:
            continue                                # not part of this mode: never opened
        _services[name] = svc = _devices.DeviceService(dev)
        try:
            svc.open()
        except DeviceError:
            pass                                    # recorded in svc.status(); reconnect(name) retries
    events.log("devices", action="connect", backend=backend, mode=mode)
    return status()


def mode():
    """The mode of the current connection ("MT" | "MT-TIRF"), None when disconnected."""
    return _mode if _services else None


def close(name):
    """Close one device and end its service thread (a step of the shutdown sequence, docs/design/shutdown.md).
    DeviceError when its cleanup fails: the device then STAYS listed, so a retry closes it again (the rig is not
    clean until it is gone)."""
    svc = _services.get(name)
    if svc is None:
        return
    if not svc._thread.is_alive():          # an earlier close failed and ended the service: reopen, then close again
        svc = _services[name] = _devices.DeviceService(svc.device)
        svc.open()
    svc.shutdown()
    _services.pop(name, None)


def disconnect():
    """Close every device in CLOSE_ORDER and end the service threads (end of session; the session-start origins are
    dropped); then release the rig lock - only when every cleanup succeeded (RULES.md 3)."""
    failed = []
    try:
        for name in sorted(_services, key=lambda n: CLOSE_ORDER.index(n) if n in CLOSE_ORDER else len(CLOSE_ORDER)):
            try:
                close(name)
            except DeviceError as e:
                failed.append(str(e))
    finally:
        _services.clear()
        events.log("devices", action="disconnect", failed=failed)
    if failed:
        # phase 7: a real motor's close is the session end (magnet home, limits released) - a failure must be seen;
        # the rig lock stays held so the lock file says the rig is not clean (RULES.md 3)
        raise DeviceError("devices", "disconnect", "cleanup incomplete: " + "; ".join(failed))
    rig.release()


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
    last preset, U15). Returns its status(). The camera while acquisition runs (WP6): the reconnect ends the segment
    and acquisition restarts in a new one (`api.acq` "camera reconnect")."""
    svc = service(name)
    from . import acq
    if name == "camera" and acq.running():
        return acq._reconnect_camera(svc)
    svc.reconnect()
    events.log("device", device=name, action="reconnect")
    if svc.reapply is not None:
        svc.reapply()
    return svc.status()


def self_check():
    """{device: [{step: open | reply | read, ok, detail}]}; each device stops at its first failed step (U8)."""
    return {name: svc.self_check() for name, svc in _services.items()}


def _move(name, quantity, value, read, send=None, origin=None, check=None, match=None, gen=None,
          read_on_caller=False):
    """Start a Motion: refuse at once (caller's thread) if e-stopped or outside the profile, then on the motion thread
    send, wait for arrival, read back and compare through acting().

    gen: the emergency-stop generation recorded on the FIRST line of the public move function, before any device
    pre-read (magnet speed, rotor position; re-review l2s-wp2-r2), so an engage -> clear during a pre-read voids the
    move. None = now (a move function without pre-reads). read_on_caller (decision 0019): read() runs on the motion
    thread and makes its own service calls (the magnet's read-back also reads the controller error); else it runs
    on the service thread."""
    svc = service(name)
    dev = svc.require()
    if gen is None:
        gen = estop.generation()        # the request is made now: an emergency stop after this voids it for good
    precheck(quantity, value, dev.tol, origin, check, gen)
    send = send or (lambda v: svc.call(dev.move_to, v, what=f"move to {v!r}"))

    def body(motion):
        def readback():
            motion.wait_arrival(dev.moving, gen)
            return read() if read_on_caller else svc.call(read, what="position")
        return acting(quantity, value, send, readback, dev.tol, origin, name, check, match, gen=gen,
                      cancel=motion.cancel_flag)
    return _devices.Motion(svc, body, what=f"{name} move to {value!r}")
