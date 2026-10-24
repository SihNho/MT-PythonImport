"""The safety behaviour inside every acting function (docs/design/api.md section 3), in one place.

Device functions call `acting(...)` instead of talking to the device service directly:
emergency stop -> profile check -> act -> read back and compare -> event. The device service runs on its own thread,
never on the frame acquisition path.
"""
from . import estop, events, safety
from .errors import DeviceError, NotReady, SafetyRefused


def acting(quantity, value, do, readback, tol, origin=None, device=None):
    """Request `value` for `quantity` and return what the device read back.

    do(value): sends the command. readback(): returns the device's value. tol: largest accepted |readback - value|.
    origin: the session-start position for a relative window. device: the name in DeviceError (default: the
    quantity's first word). Raises NotReady (emergency stop), SafetyRefused (outside the profile; nothing is sent),
    DeviceError (read-back mismatch).
    """
    request = {"quantity": quantity, "value": value}
    if origin is not None:
        request["origin"] = origin
    if estop.active():
        events.log("refused", request=request, reason="emergency stop active")
        raise NotReady(f"emergency stop is active; {quantity} {value!r} not sent")
    try:
        safety.check(quantity, value, origin)
    except SafetyRefused as e:
        events.log("refused", request=request, reason=str(e))
        raise
    do(value)
    got = readback()
    if abs(got - value) > tol:
        events.log("device_error", request=request, readback=got, tol=tol)
        raise DeviceError(device or quantity.split("_")[0], f"set {quantity} {value!r}",
                          f"read back {got!r}, more than {tol!r} away; check the device and its cable")
    events.log("act", request=request, readback=got)
    return got
