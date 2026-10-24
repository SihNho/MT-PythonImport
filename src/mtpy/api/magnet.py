"""The magnet (PI C-863): position is the raw quantity, force is derived from a recorded table (decision 0010).

    m = api.magnet.move_to(5.0)          # mm; refused outside the rig safety profile's magnet travel
    m.wait(timeout_s=10)                 # -> position read back (mm)
"""
import numpy as np

from . import events, safety
from .devices import _move, service
from .errors import NotReady, SafetyRefused


def move_to(position_mm, speed_mm_s=None):
    """Move the magnet to position_mm (0 = top, larger = closer to the sample) and return a Motion.

    Safety: position_mm inside the profile's `magnet_position_mm`; the speed inside `magnet_speed_mm_s`, ALWAYS:
    a given speed_mm_s is checked, and when it is omitted the speed the controller would apply is read back
    (`VEL?`) and checked (review l2s-wp2-r1); the checked speed is then sent with the move, so the move runs at
    exactly the speed that was checked. A profile without a speed limit (the shipped v1: `magnet_speed_mm_s` has
    no max) refuses every magnet move until a rig-admin sets it. Emergency stop -> NotReady. Read back within the
    device's tolerance or DeviceError (from wait()). Example: `api.magnet.move_to(5.0).wait(10)`.
    """
    svc = service("magnet")
    dev = svc.require()
    omitted = speed_mm_s is None
    speed = svc.call(dev.speed, what="VEL? 1") if omitted else speed_mm_s
    request = {"quantity": "magnet_speed_mm_s", "value": speed}
    if omitted:
        request["source"] = "controller speed read back (speed_mm_s omitted)"
    try:
        safety.check("magnet_speed_mm_s", speed)
    except SafetyRefused as e:
        events.log("refused", request=request, reason=str(e))
        raise
    return _move("magnet", "magnet_position_mm", position_mm, dev.position,
                 send=lambda v: svc.call(dev.move_to, v, speed, what=f"VEL 1 {speed!r}; MOV 1 {v!r}"))


def position():
    """The magnet position read back, mm. Example: `api.magnet.position()`."""
    svc = service("magnet")
    return svc.call(svc.require().position, what="POS?")


def _valid_table(t):
    try:
        pos = np.asarray(t["position_mm"], dtype=float)
        f = np.asarray(t["force_pN"], dtype=float)
        ok = (isinstance(t["name"], str) and t["name"] and "version" in t and pos.ndim == 1 and pos.shape == f.shape
              and pos.size >= 2 and np.all(np.isfinite(pos)) and np.all(np.isfinite(f)) and np.all(np.diff(f) > 0))
    except (KeyError, TypeError, ValueError):
        ok = False
    if not ok:
        raise SafetyRefused("a force table needs name, version, position_mm and force_pN (same length >= 2, finite, "
                            "force strictly increasing)")
    return pos, f


def use_force_table(table):
    """Load the recorded position-to-force table for this session (0010): {"name", "version", "position_mm": [...],
    "force_pN": [...]} with force strictly increasing. Its name and version show as the calibration in use."""
    svc = service("magnet")
    _valid_table(table)
    svc.calibration = {"force_table": {"name": table["name"], "version": table["version"]}}
    svc.force_table = table
    events.log("calibration", device="magnet", force_table=table["name"], version=table["version"])


def set_force(force_pN, table=None):
    """Move the magnet to the position that gives force_pN by the position-to-force table (0010); returns a Motion.

    table: a table for this call, else the one from use_force_table(). No table -> NotReady (no physics is
    invented). Safety: force_pN inside the profile's `magnet_force_pN` and inside the table's range, then the
    position goes through move_to(). Example: `api.magnet.set_force(2.0).wait(30)`.
    """
    svc = service("magnet")
    table = table if table is not None else getattr(svc, "force_table", None)
    if table is None:
        raise NotReady("no position-to-force table is loaded; use api.magnet.use_force_table(table) (decision 0010)")
    pos, f = _valid_table(table)
    request = {"quantity": "magnet_force_pN", "value": force_pN, "table": table["name"]}
    try:
        if not safety.check("magnet_force_pN", force_pN):
            events.log("unverified-limit", request=request, level="warning",
                       reason="magnet_force_pN relies on a limit marked unverified in the rig safety profile")
        if not f[0] <= force_pN <= f[-1]:
            raise SafetyRefused(f"magnet force {force_pN:g} pN is outside the table {table['name']!r} range "
                                f"[{f[0]:g}, {f[-1]:g}] pN")
    except SafetyRefused as e:
        events.log("refused", request=request, reason=str(e))
        raise
    target = float(np.interp(force_pN, f, pos))
    events.log("force_request", request=request, position_mm=target, table_version=table["version"])
    return move_to(target)
