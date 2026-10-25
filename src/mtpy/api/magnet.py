"""The magnet (PI C-863): position is the raw quantity, force is derived from a recorded table (decision 0010).

    m = api.magnet.move_to(5.0)          # mm; refused outside the rig safety profile's magnet travel
    m.wait(timeout_s=10)                 # -> position read back (mm)

Decision 0017: there is no separate maximum force. A force is converted to a magnet position through the force table
in use and that position is checked against the profile's `magnet_position_mm` limit; the reachable force range is
the table's force at the position-limit ends (`force_range()`). A `magnet_force_pN` entry left in an older profile
(v1-v4) is ignored.
"""
import numpy as np

from . import estop, events, safety
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
    The request is made at the first line: an emergency stop engaged from here on (even while the speed is read
    back, and even if released again) voids it (re-review l2s-wp2-r2).
    """
    gen = estop.generation()
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
    return _move("magnet", "magnet_position_mm", position_mm, dev.position, gen=gen,
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
              and pos.size >= 2 and np.all(np.isfinite(pos)) and np.all(np.isfinite(f)) and np.all(np.diff(f) > 0)
              and (np.all(np.diff(pos) > 0) or np.all(np.diff(pos) < 0)))
    except (KeyError, TypeError, ValueError):
        ok = False
    if not ok:
        raise SafetyRefused("a force table needs name, version, position_mm and force_pN (same length >= 2, finite, "
                            "force strictly increasing, position strictly monotonic)")
    return pos, f


def _position_limit():
    """(min, max, profile version) of the profile's absolute `magnet_position_mm` limit. SafetyRefused (the profile's
    own message) when it is missing, unset, or unverified while unverified limits are not allowed."""
    p = safety.profile()
    e = p["limits"].get("magnet_position_mm")
    safety.check("magnet_position_mm", e["min"] if e and safety._is_number(e["min"]) else 0.0)
    if e["relative_to"]:
        raise SafetyRefused("a force needs an absolute magnet position limit; the profile's magnet_position_mm is "
                            f"relative to {e['relative_to']}")
    return e["min"], e["max"], p["version"]


def _reach(table):
    """The reachable force range of `table` inside the magnet position limit (decision 0017), as force_range()."""
    pos, f = _valid_table(table)
    lo, hi, v = _position_limit()
    if pos[0] > pos[-1]:
        pos, f = pos[::-1], f[::-1]
    a, b = max(lo, pos[0]), min(hi, pos[-1])
    if a > b:
        raise SafetyRefused(f"the force table {table['name']!r} covers magnet positions [{pos[0]:g}, {pos[-1]:g}] mm, "
                            f"none inside the magnet position limit [{lo:g}, {hi:g}] mm of the rig safety profile "
                            f"v{v}; no force is reachable")
    ends = sorted([(float(np.interp(a, pos, f)), float(a)), (float(np.interp(b, pos, f)), float(b))])
    return {"force_pN": (ends[0][0], ends[1][0]), "position_mm": (ends[0][1], ends[1][1]),
            "limited_by": tuple("position limit" if p in (lo, hi) else "table end" for _, p in ends),
            "position_limit_mm": (float(lo), float(hi)), "table": table["name"], "table_version": table["version"],
            "profile_version": v}


def _table(table):
    if table is not None:
        return table
    table = getattr(service("magnet"), "force_table", None)
    if table is None:
        raise NotReady("no position-to-force table is loaded; use api.magnet.use_force_table(table) (decision 0010)")
    return table


def force_range(table=None):
    """The force range reachable inside the magnet position limit with the force table in use (decision 0017).
    Read only. {"force_pN": (min, max), "position_mm": (position at min, position at max), "limited_by": ("position
    limit" | "table end", ...), "position_limit_mm", "table", "table_version", "profile_version"}.
    table: a table for this call, else the loaded one (none -> NotReady). Example: `api.magnet.force_range()`."""
    return _reach(_table(table))


def force_position(force_pN, table=None):
    """The magnet position (mm) that gives force_pN by the force table in use, checked against the magnet position
    limit (decision 0017). Read only: nothing moves and nothing is logged. SafetyRefused when the force is reachable
    only outside the position limit (or not at all), with the requested force, the table's force at the limit end
    and the position; NotReady without a table. The protocol checker uses it before a run."""
    table = _table(table)
    if not safety._is_number(force_pN):
        raise SafetyRefused(f"magnet force {force_pN!r} is not a finite number")
    pos, f = _valid_table(table)
    r = _reach(table)
    (fmin, fmax), (pmin, pmax), (lo, hi) = r["force_pN"], r["position_mm"], r["position_limit_mm"]
    if fmin <= force_pN <= fmax:
        return float(np.interp(force_pN, f, pos))
    end_f, end_p, end_by = (fmax, pmax, r["limited_by"][1]) if force_pN > fmax else (fmin, pmin, r["limited_by"][0])
    reach = (f"the table gives {end_f:g} pN at the {'limit' if end_by == 'position limit' else 'table'} end "
             f"{end_p:g} mm (reachable force [{fmin:g}, {fmax:g}] pN with the magnet position limit [{lo:g}, {hi:g}] "
             f"mm of the rig safety profile v{r['profile_version']}, decision 0017)")
    if f[0] <= force_pN <= f[-1]:
        need = float(np.interp(force_pN, f, pos))
        raise SafetyRefused(f"magnet force {force_pN:g} pN needs magnet position {need:g} mm by the force table "
                            f"{table['name']!r}, outside the magnet position limit [{lo:g}, {hi:g}] mm; {reach}")
    raise SafetyRefused(f"magnet force {force_pN:g} pN is outside the table {table['name']!r} range "
                        f"[{f[0]:g}, {f[-1]:g}] pN (no position for it); {reach}")


def use_force_table(table):
    """Load the recorded position-to-force table for this session (0010): {"name", "version", "position_mm": [...],
    "force_pN": [...]} with force strictly increasing. Its name and version show as the calibration in use."""
    svc = service("magnet")
    _valid_table(table)
    svc.calibration = {"force_table": {"name": table["name"], "version": table["version"]}}
    svc.force_table = table
    events.log("calibration", device="magnet", force_table=table["name"], version=table["version"])


def force_table():
    """The position-to-force table loaded with use_force_table() (a copy: name, version, position_mm, force_pN), or
    None. Read only; the protocol checker (WP5) uses it to refuse a force outside the table before a run starts."""
    t = getattr(service("magnet"), "force_table", None)
    if t is None:
        return None
    return {"name": t["name"], "version": t["version"], "position_mm": [float(x) for x in t["position_mm"]],
            "force_pN": [float(x) for x in t["force_pN"]]}


def set_force(force_pN, table=None):
    """Move the magnet to the position that gives force_pN by the position-to-force table (0010); returns a Motion.

    table: a table for this call, else the one from use_force_table(). No table -> NotReady (no physics is
    invented). Safety (decision 0017): no separate maximum force; the force is converted to a position through the
    table and that position must be inside the profile's `magnet_position_mm` limit (force_position()), else
    SafetyRefused before anything moves; then the position goes through move_to() (speed and position checked
    again). Example: `api.magnet.set_force(2.0).wait(30)`.
    """
    table = _table(table)
    _valid_table(table)
    request = {"quantity": "magnet_force_pN", "value": force_pN, "table": table["name"]}
    try:
        target = force_position(force_pN, table)
    except SafetyRefused as e:
        events.log("refused", request=request, reason=str(e))
        raise
    events.log("force_request", request=request, position_mm=target, table_version=table["version"])
    return move_to(target)
