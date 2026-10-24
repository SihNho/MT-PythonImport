"""The safety behaviour inside every acting function (docs/design/api.md section 3), in one place.

Device functions call `acting(...)` instead of talking to the device service directly:
emergency stop -> tolerance and profile check -> act -> read back and compare -> event. The device service runs on
its own thread, never on the frame acquisition path.
"""
from . import estop, events, safety
from .errors import DeviceError, NotReady, SafetyRefused


def _device_error(request, device, command, hint, stage, cause=None, **extra):
    events.log("device_error", request=request, stage=stage, hint=hint, **extra)
    raise DeviceError(device, command, hint) from cause


def precheck(quantity, value, tol=0.0, origin=None, check=None, gen=None):
    """Steps 5 and 1 of acting() alone: NotReady while the emergency stop is active (or, with `gen`, when it was
    engaged since generation `gen`), SafetyRefused (with a `refused` event) for a bad tol or a value outside the
    profile / check(). Returns (request, verified). A Motion calls it on the caller's thread so a refusal reaches the
    caller at once, not only at wait()."""
    request = {"quantity": quantity, "value": value}
    if origin is not None:
        request["origin"] = origin
    if estop.active() or (gen is not None and gen != estop.generation()):
        events.log("refused", request=request, reason="emergency stop active or engaged since the request was made")
        raise NotReady(f"emergency stop is active or was engaged since the request was made; {quantity} {value!r} "
                       "not sent")
    try:
        if not (safety._is_number(tol) and tol >= 0):
            raise SafetyRefused(f"tolerance {tol!r} for {quantity} must be a finite number >= 0; nothing sent")
        verified = check(value) if check is not None else safety.check(quantity, value, origin)
    except SafetyRefused as e:
        events.log("refused", request=request, reason=str(e))
        raise
    return request, verified


def acting(quantity, value, do, readback, tol, origin=None, device=None, check=None, match=None, gen=None,
           cancel=None):
    """Request `value` for `quantity` and return what the device read back.

    do(value): sends the command. readback(): returns the device's value. tol: largest accepted |readback - value|
    (a finite number >= 0). origin: the session-start position for a relative window. device: the name in
    DeviceError (default: the quantity's first word).
    check(value) (WP2): replaces the rig-safety-profile check for a setting that is not a profile quantity (camera
    exposure, ROI, laser on/off, sync ratio) or that spans several quantities (stage x/y): it raises SafetyRefused
    with the allowed range or returns True (verified) / False (unverified). match(got) (WP2): replaces the numeric
    tol comparison for a non-scalar read-back (ROI, a preset, x/y); True when the read-back is what was asked.
    Raises NotReady (emergency stop; also passed through unchanged, with a `cancelled` event, when do/readback
    raise it, e.g. a Motion cancelled or stopped by the emergency stop), SafetyRefused (bad tol or outside the
    profile; nothing is sent), DeviceError (the send or the read-back raised, the read-back is not a finite number,
    or it is more than tol away / does not match).
    Only a read-back that passed is logged as an 'act' event. A limit marked unverified (allowed by the profile)
    logs an 'unverified-limit' warning event before the command is sent.
    Send window (review l2s-wp2-r1): gen is the emergency-stop generation when the request was made (default: now)
    and cancel the Motion's cancel flag (threading.Event or None). do() runs inside `estop.guarded_send(gen,
    cancel)`, so the device service checks both right before each send (void -> nothing sent) and right after it
    (void -> the device thread stops the device again); either way do() raises NotReady, which ends the call with a
    `cancelled` event and no `act` event. A request made before an emergency stop never runs after clear().
    """
    gen = estop.generation() if gen is None else gen
    request, verified = precheck(quantity, value, tol, origin, check, gen)
    if not verified:
        events.log("unverified-limit", request=request, level="warning",
                   reason=f"{quantity} relies on a limit marked unverified in the rig safety profile "
                          f"v{safety.profile()['version']} (allow_unverified true)")
    name, command = device or quantity.split("_")[0], f"set {quantity} {value!r}"
    try:
        with estop.guarded_send(gen, cancel):
            do(value)
    except NotReady as e:
        events.log("cancelled", request=request, reason=str(e))
        raise
    except Exception as e:  # noqa: BLE001 - any device failure must become a DeviceError with an event
        _device_error(request, name, command, f"send failed: {type(e).__name__}: {e}", "send", e)
    why = estop.invalid((gen, cancel))
    if why:                       # voided after the service's own check: the stop that voided it halts the device
        events.log("cancelled", request=request, reason=why)
        raise NotReady(f"{quantity} {value!r}: {why}")
    try:
        got = readback()
    except NotReady as e:
        events.log("cancelled", request=request, reason=str(e))
        raise
    except Exception as e:  # noqa: BLE001 - any device failure must become a DeviceError with an event
        _device_error(request, name, command, f"read-back failed: {type(e).__name__}: {e}", "readback", e)
    if match is not None:
        if not match(got):
            _device_error(request, name, command, f"read back {got!r}, not what was asked; check the device and "
                          "its cable", "compare", readback=repr(got))
        events.log("act", request=request, readback=got)
        return got
    if not safety._is_number(got):
        _device_error(request, name, command, f"read back {got!r}, not a finite number; check the device and its "
                      "cable", "readback", readback=repr(got))
    if abs(got - value) > tol:
        _device_error(request, name, command, f"read back {got!r}, more than {tol!r} away; check the device and "
                      "its cable", "compare", readback=got, tol=tol)
    events.log("act", request=request, readback=got)
    return got
