"""The magnet (PI C-863): position is the raw quantity, force is derived from a calibration (decisions 0010, 0018).

    m = api.magnet.move_to(5.0)          # mm; a position outside the magnet position limit is coerced (0018 item 5)
    m.wait(timeout_s=10)                 # -> position read back (mm)
    api.magnet.set_touch_position(20.0)  # 'Mag pos when touched to glass' (mm) for the force equation
    m = api.magnet.set_force(5.0)        # m.applied_pN: the force actually set (coerced into the reachable range)

Decision 0018 (refines 0017 item 2): the default calibration is the LabVIEW force equation computed live
(`mtpy.forcecal.M270_V3`, needs the touch position); a recorded table (`use_force_table`) is the swappable
alternative (0010). The only magnet safety limit is the profile's `magnet_position_mm` (0017). A force outside the
reachable range [F(limit min), F(limit max)] and a position outside the limit are COERCED to the nearest reachable
value - no alarm, no refusal - and a `coerced` event records requested, applied, reason and calibration. Second
safeguard (0018 item 4): the position sent to the device is coerced into the limit in the last step before sending.
The speed is checked as before (refused above `magnet_speed_mm_s`). A `magnet_force_pN` entry left in an older
profile (v1-v4) is ignored.
"""
import contextvars
import threading
import time

from mtpy import forcecal

from . import estop, events, safety
from .devices import _move, service
from .errors import DeviceError, MagnetStall, MtpyError, NotReady, SafetyRefused

COERCE_TOL = 1e-9        # |applied - requested| at or below this is numerical noise: applied, not logged as coerced
STALL_ERROR = -1024      # PI: "position error too large, servo switched off" (decision 0019)
RETURN_TIMEOUT_S = 60.0  # the stall return: 39 mm at >= 1 mm/s, with margin
_STALL_LOCK = threading.Lock()   # one stall check / response at a time (one magnet)


def move_to(position_mm, speed_mm_s=None, _stall_return=False):
    """Move the magnet to position_mm (0 = top, larger = closer to the sample) and return a Motion.

    Position (decision 0018 item 5): outside the profile's `magnet_position_mm` it is coerced to the nearest limit
    (no alarm; a `coerced` event); the Motion carries `requested_mm`, `applied_mm` and `coerced`, so a GUI field can
    be rewritten with the applied value. The position actually sent is coerced into the limit once more right
    before sending (0018 item 4). A position that is not a finite number is refused (SafetyRefused).
    Speed: inside `magnet_speed_mm_s`, ALWAYS: a given speed_mm_s is checked, and when it is omitted the speed the
    controller would apply is read back (`VEL?`) and checked (review l2s-wp2-r1); the checked speed is then sent with
    the move, so the move runs at exactly the speed that was checked. A profile without a speed limit (the shipped
    v1: `magnet_speed_mm_s` has no max) refuses every magnet move until a rig-admin sets it. Emergency stop ->
    NotReady. Read back within the device's tolerance or DeviceError (from wait()).
    Example: `api.magnet.move_to(5.0).wait(10)`.
    The request is made at the first line: an emergency stop engaged from here on (even while the speed is read
    back, and even if released again) voids it (re-review l2s-wp2-r2).
    Stall (decision 0019): the read-back also reads the controller error; a stall is handled at once (return to
    0 mm) and wait() raises MagnetStall. While the magnet is locked after an unverified return, every move is refused
    (NotReady) until clear_stall().
    """
    gen = estop.generation()
    svc = service("magnet")
    dev = svc.require()
    if getattr(svc, "stall_locked", None) is not None and not _stall_return:
        reason = ("the magnet is locked after a stall whose return to 0 mm was not verified (decision 0019); "
                  "api.magnet.clear_stall() first")
        events.log("refused", request={"quantity": "magnet_position_mm", "value": position_mm}, reason=reason)
        raise NotReady(reason)
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
    applied = _coerce_position(position_mm)
    n_stall = getattr(svc, "stall_count", 0)
    m = _move("magnet", "magnet_position_mm", applied, lambda: _read_checked(svc, dev, n_stall, _stall_return),
              gen=gen, send=lambda v: _send(svc, dev, v, speed), read_on_caller=True)
    m.requested_mm, m.applied_mm = position_mm, applied
    m.coerced = applied is not position_mm and abs(applied - position_mm) > COERCE_TOL
    return m


def _coerce_position(position_mm):
    """Decision 0018 item 5: a finite position outside the absolute position limit -> the nearest limit, with a
    `coerced` event. Anything else (not a number, no usable limit) is returned unchanged for the profile check to
    refuse with its own message."""
    if not safety._is_number(position_mm):
        return position_mm
    try:
        lo, hi, v = _position_limit()
    except SafetyRefused:
        return position_mm
    applied = float(min(max(position_mm, lo), hi))
    if abs(applied - position_mm) <= COERCE_TOL:
        return position_mm if lo <= position_mm <= hi else applied
    events.log("coerced", request={"quantity": "magnet_position_mm", "value": position_mm}, applied=applied,
               reason=f"outside the magnet position limit [{lo:g}, {hi:g}] mm of the rig safety profile v{v}; set to "
                      "the nearest limit (decision 0018 item 5)")
    return applied


def _send(svc, dev, position_mm, speed):
    """The last step before the device (decision 0018 item 4): whatever the caller computed, the position sent is
    coerced into the magnet position limit (a `coerced` event, stage "send", when it had to be). Runs on the motion
    thread inside acting()'s guarded send; the controller's TMN / TMX stay set as the hardware layer below."""
    if not safety._is_number(position_mm):
        raise SafetyRefused(f"magnet position {position_mm!r} is not a finite number; nothing sent")
    lo, hi, v = _position_limit()
    sent = float(min(max(position_mm, lo), hi))
    if sent != position_mm:
        events.log("coerced", request={"quantity": "magnet_position_mm", "value": position_mm}, applied=sent,
                   stage="send", reason=f"last-step coercion into the magnet position limit [{lo:g}, {hi:g}] mm of "
                                        f"the rig safety profile v{v} before sending (decision 0018 item 4)")
    return svc.call(dev.move_to, sent, speed, what=f"VEL 1 {speed!r}; MOV 1 {sent!r}")


def position():
    """The magnet position read back, mm. Example: `api.magnet.position()`."""
    svc = service("magnet")
    return svc.call(svc.require().position, what="POS?")


# --- stall: the extinguisher (decision 0019) -----------------------------------------------------------------------

def _read_error(svc, dev):
    fn = getattr(dev, "error", None)
    return 0 if fn is None else svc.call(fn, what="ERR?")


def _read_checked(svc, dev, n_stall, returning):
    """The magnet move's read-back (motion thread): the controller error first, then the position. A stall (-1024)
    is handled here (return to 0 mm) and raised as MagnetStall; so is a stall the poller handled during this move.
    During the stall return itself (`returning`) a new stall is only raised, never handled again (one shot)."""
    if returning:
        err = _read_error(svc, dev)
        if err == STALL_ERROR:
            raise MagnetStall(svc.last_stall, hint=f"a new stall (controller error {err}) during the return to 0 mm")
        return svc.call(dev.position, what="POS?")
    with _STALL_LOCK:
        if getattr(svc, "stall_count", 0) != n_stall:
            raise MagnetStall(svc.last_stall)
        err = _read_error(svc, dev)
        if err != STALL_ERROR:
            return svc.call(dev.position, what="POS?")
        svc.stall_count = getattr(svc, "stall_count", 0) + 1
        rec = _respond(svc, dev, err, svc.call(dev.position, what="POS?"), "move read-back")
    raise MagnetStall(rec)


def _abort_protocol(reason):
    from . import protocol as _protocol
    eng = _protocol._engine
    if eng is not None and not eng.done:
        eng.abort(reason)


def _return_to_zero(svc, dev):
    """Servo on again, move to 0 mm through the normal path (speed check, coercion, last-step coercion), verify the
    position within the device tolerance. Returns the position read; raises on any failure (never retried)."""
    svc.call(dev.set_servo, True, what="SVO 1 1")
    if not svc.call(dev.servo_on, what="SVO? 1"):
        raise DeviceError("magnet", "SVO 1 1", "the servo did not switch on again after the stall")
    move_to(0.0, _stall_return=True).wait(RETURN_TIMEOUT_S)
    p = svc.call(dev.position, what="POS?")
    if not (safety._is_number(p) and abs(p) <= dev.tol):
        raise DeviceError("magnet", "POS?", f"read {p!r} mm after the return, not 0 mm within {dev.tol} mm")
    return p


def _respond(svc, dev, err, pos, source):
    """Decision 0019, under _STALL_LOCK, once per stall: stop the move and the protocol, return to 0 mm unless that
    is not allowed (emergency stop engaged) or not possible (position not valid after a stall per the device layer),
    verify; otherwise lock the magnet. Logs one `magnet_stall` event (level error) and returns its content."""
    valid = bool(getattr(dev, "position_valid_after_stall", True))
    rec = {"t_stall": time.time(), "position_mm": pos, "controller_error": err, "detected_by": source,
           "position_valid_after_stall": valid, "return_attempted": False, "return_verified": False,
           "position_after_mm": None, "locked": False, "reason": None}
    svc.last_stall = rec
    try:
        dev.stop()                     # directly, as the emergency stop does (the servo is off already)
    except Exception:  # noqa: BLE001, S110 - the stop is best effort; the return below is what counts
        pass
    _abort_protocol(f"magnet stall at {pos!r} mm (controller error {err}, decision 0019)")
    if estop.active():
        rec["reason"] = ("emergency stop engaged: no return move; after the release the user returns the magnet "
                         "with api.magnet.clear_stall()")
    elif not valid:
        rec["reason"] = ("the device layer says the position is not valid after a stall (a reference move would be "
                         "needed first, not implemented): no return move")
    else:
        rec["return_attempted"] = True
        try:
            rec["position_after_mm"] = _return_to_zero(svc, dev)
            rec["return_verified"] = True
        except Exception as e:  # noqa: BLE001 - any failure of the return locks the magnet
            rec["reason"] = f"return to 0 mm failed: {type(e).__name__}: {e}"
    if not rec["return_verified"]:
        rec["locked"] = True
        svc.stall_locked = rec
    events.log("magnet_stall", request={"quantity": "magnet_position_mm"}, readback=pos, level="error", **rec)
    return rec


def _poll_respond(svc, dev, err, pos):
    try:
        _respond(svc, dev, err, pos, "poll")
    finally:
        _STALL_LOCK.release()


def poll_position():
    """For the acquisition's motor poller (decision 0019): the position, after reading the controller error. A stall
    is handled on its own thread (the poller keeps reading); the reading is still returned (the stall position)."""
    svc = service("magnet")
    dev = svc.require()
    if not _STALL_LOCK.acquire(blocking=False):      # a stall is being handled: just read
        return position()
    try:
        try:
            err = _read_error(svc, dev)
        except MtpyError:          # a failed ERR? is not a reading error of its own: the position read decides
            err = None
        pos = position()
    except BaseException:
        _STALL_LOCK.release()
        raise
    if err != STALL_ERROR:
        _STALL_LOCK.release()
        return pos
    svc.stall_count = getattr(svc, "stall_count", 0) + 1     # before the thread: a running move sees it at once
    threading.Thread(target=contextvars.copy_context().run, args=(_poll_respond, svc, dev, err, pos),
                     name="magnet-stall", daemon=True).start()
    return pos


def check_stall():
    """Read the controller error now; on a stall respond (decision 0019) and raise MagnetStall. Returns None when
    there is none. Example: `api.magnet.check_stall()`."""
    svc = service("magnet")
    dev = svc.require()
    with _STALL_LOCK:
        err = _read_error(svc, dev)
        if err != STALL_ERROR:
            return
        svc.stall_count = getattr(svc, "stall_count", 0) + 1
        rec = _respond(svc, dev, err, svc.call(dev.position, what="POS?"), "check_stall")
    raise MagnetStall(rec)


def stall_status():
    """{"locked": the record that locked the magnet or None, "last": the last stall record or None, "count"}."""
    svc = service("magnet")
    return {"locked": getattr(svc, "stall_locked", None), "last": getattr(svc, "last_stall", None),
            "count": getattr(svc, "stall_count", 0)}


def clear_stall(return_to_zero=True):
    """The user's explicit action after a stall that locked the magnet (decision 0019): return_to_zero (default)
    re-enables the servo, moves to 0 mm and verifies it, then unlocks; False unlocks without moving (the user has
    made the magnet safe by hand). Refused (NotReady) while the emergency stop is engaged. A failed return keeps the
    lock and raises MagnetStall. Logs `magnet_stall_clear`. Returns stall_status()."""
    svc = service("magnet")
    dev = svc.require()
    rec = getattr(svc, "stall_locked", None)
    if rec is None:
        return stall_status()
    with _STALL_LOCK:
        p = None
        if return_to_zero:
            if estop.active():
                raise NotReady("the emergency stop is engaged; release it before returning the magnet")
            try:
                p = _return_to_zero(svc, dev)
            except MtpyError as e:
                why = f"return to 0 mm failed: {type(e).__name__}: {e}"
                events.log("magnet_stall_clear", result="failed", reason=why, level="error")
                raise MagnetStall({**rec, "return_attempted": True, "return_verified": False, "reason": why}) from e
        svc.stall_locked = None
        events.log("magnet_stall_clear", result="cleared", return_to_zero=return_to_zero, position_after_mm=p)
    return stall_status()


# --- force calibration (decisions 0010, 0017, 0018) --------------------------------------------------------------

def _state(svc=None):
    """(calibration, touch_mm) of this session: the default is the live equation without a touch position."""
    svc = svc or service("magnet")
    return getattr(svc, "force_state", None) or (forcecal.DEFAULT, None)


def _set_state(cal, touch):
    svc = service("magnet")
    svc.force_state = (cal, touch)              # one tuple: a reader (poller, display) never sees a mixed state
    calib = {"force": cal.describe(touch)}
    if cal.kind == "table":
        calib["force_table"] = {"name": cal.name, "version": cal.version}
    svc.calibration = calib
    events.log("calibration", device="magnet", force_calibration=cal.name, calibration_kind=cal.kind, touch_mm=touch,
               **({"force_table": cal.name, "version": cal.version} if cal.kind == "table" else {}))


def _as_table(table):
    try:
        return forcecal.TableCalibration(table)
    except ValueError as e:
        raise SafetyRefused(str(e)) from None


def _resolve(table):
    """(calibration, touch) for a call: `table` None = the session's; a table dict or a calibration object for this
    call only (touch from the session). NotReady when the calibration needs a touch position that is not set."""
    cal, touch = _state()
    if table is not None:
        cal = table if hasattr(table, "position") and hasattr(table, "domain") else _as_table(table)
    if cal.needs_touch and touch is None:
        raise NotReady(f"the force calibration {cal.name!r} needs the touch position ('Mag pos when touched to "
                       "glass'); api.magnet.set_touch_position(mm) first (decision 0018)")
    return cal, touch


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


def _reach(cal, touch):
    """The reachable force range of `cal` inside the magnet position limit (decision 0017), as force_range()."""
    lo, hi, v = _position_limit()
    d0, d1 = cal.domain()
    a, b = max(lo, d0), min(hi, d1)
    if a > b:
        raise SafetyRefused(f"the force calibration {cal.name!r} covers magnet positions [{d0:g}, {d1:g}] mm, none "
                            f"inside the magnet position limit [{lo:g}, {hi:g}] mm of the rig safety profile v{v}; no "
                            "force is reachable")
    ends = sorted([(cal.force(a, touch), float(a)), (cal.force(b, touch), float(b))])
    r = {"force_pN": (ends[0][0], ends[1][0]), "position_mm": (ends[0][1], ends[1][1]),
         "limited_by": tuple("position limit" if p in (lo, hi) else "table end" for _, p in ends),
         "position_limit_mm": (float(lo), float(hi)), "calibration": cal.name, "kind": cal.kind,
         "touch_mm": touch, "profile_version": v}
    if cal.kind == "table":
        r.update(table=cal.name, table_version=cal.version)
    else:
        r["touch_beyond_limit"] = touch is not None and touch < hi      # open point, see api.md (not decided)
    return r


def use_force_calibration(calibration=forcecal.DEFAULT.name):
    """Use a force calibration for this session: the name of a known equation (`mtpy.forcecal.EQUATIONS`; default
    the LabVIEW M270 v3 case 1) or a calibration object. The touch position set before is kept. Logs `calibration`."""
    cal = forcecal.EQUATIONS.get(calibration) if isinstance(calibration, str) else calibration
    if cal is None or not (hasattr(cal, "position") and hasattr(cal, "describe")):
        raise SafetyRefused(f"unknown force calibration {calibration!r}; known: {sorted(forcecal.EQUATIONS)}")
    _set_state(cal, _state()[1])


def set_touch_position(touch_mm):
    """Set 'Mag pos when touched to glass' (mm) for this session: the force equation's d = touch_mm - position.
    Changes the reachable force range (not the profile). Logs `calibration`."""
    if not safety._is_number(touch_mm):
        raise SafetyRefused(f"touch position {touch_mm!r} is not a finite number")
    _set_state(_state()[0], float(touch_mm))


def use_force_table(table):
    """Load a recorded position-to-force table for this session (0010, the swappable alternative to the equation):
    {"name", "version", "position_mm": [...], "force_pN": [...]} with force strictly increasing and position strictly
    monotonic. Its name and version show as the calibration in use."""
    _set_state(_as_table(table), _state()[1])


def force_calibration():
    """The calibration in use (read only): name, kind, equation and constants (or the table), touch_mm, plus
    "ready" (False while an equation lacks the touch position) and "why". The run file records it (0010)."""
    cal, touch = _state()
    d = cal.describe(touch)
    d["ready"] = not (cal.needs_touch and touch is None)
    d["why"] = None if d["ready"] else "the touch position is not set (api.magnet.set_touch_position)"
    return d


def force_table():
    """The table in use (a copy: name, version, position_mm, force_pN) when the calibration is a table, else None."""
    cal, _ = _state()
    if cal.kind != "table":
        return None
    t = cal.table
    return {"name": t["name"], "version": t["version"], "position_mm": [float(x) for x in t["position_mm"]],
            "force_pN": [float(x) for x in t["force_pN"]]}


def force_range(table=None):
    """The force range reachable inside the magnet position limit with the calibration in use (decision 0017).
    Read only. {"force_pN": (min, max), "position_mm": (position at min, position at max), "limited_by": ("position
    limit" | "table end", ...), "position_limit_mm", "calibration", "kind", "touch_mm", "profile_version"} (+ "table",
    "table_version" for a table; "touch_beyond_limit" for an equation). table: a table (or calibration) for this call.
    NotReady when the equation has no touch position. Example: `api.magnet.force_range()`."""
    return _reach(*_resolve(table))


def coerce_force(force_pN, table=None):
    """Decision 0018: the force actually applied for a requested force, read only (nothing moves, nothing logged).
    {"requested_pN", "applied_pN", "position_mm", "coerced", "reason", "calibration", "touch_mm"}: a force outside
    the reachable range becomes the nearest reachable force (the force at the position-limit end). SafetyRefused only
    for a value that is not a finite number (or no reachable force at all); NotReady without a touch position."""
    cal, touch = _resolve(table)
    if not safety._is_number(force_pN):
        raise SafetyRefused(f"magnet force {force_pN!r} is not a finite number")
    r = _reach(cal, touch)
    (fmin, fmax), (pmin, pmax) = r["force_pN"], r["position_mm"]
    applied, reason = float(force_pN), None
    if force_pN > fmax + COERCE_TOL or force_pN < fmin - COERCE_TOL:
        hi = force_pN > fmax
        applied, pos, by = (fmax, pmax, r["limited_by"][1]) if hi else (fmin, pmin, r["limited_by"][0])
        lo_l, hi_l = r["position_limit_mm"]
        reason = (f"magnet force {force_pN:g} pN is {'above' if hi else 'below'} the reachable range [{fmin:g}, "
                  f"{fmax:g}] pN of {cal.name!r}"
                  + (f" at touch {touch:g} mm" if touch is not None else "")
                  + f" inside the magnet position limit [{lo_l:g}, {hi_l:g}] mm (rig safety profile "
                    f"v{r['profile_version']}); set to {applied:g} pN at the {by} ({pos:g} mm) (decision 0018)")
    else:
        applied = min(max(applied, fmin), fmax)
        pos = cal.position(applied, min(pmin, pmax), max(pmin, pmax), touch)
    return {"requested_pN": force_pN, "applied_pN": applied, "position_mm": float(pos),
            "coerced": reason is not None, "reason": reason, "calibration": cal.name, "touch_mm": touch}


def force_position(force_pN, table=None):
    """The magnet position (mm) for force_pN after coercion into the reachable range (decision 0018); always inside
    the magnet position limit. Read only. See coerce_force()."""
    return coerce_force(force_pN, table)["position_mm"]


def force_at(position_mm, table=None):
    """The force (pN) at a magnet position by the calibration in use, computed live (decision 0018 item 1). Read
    only, no device call: cheap enough for a poller or display per reading, never called on the acquisition path.
    NotReady while the equation has no touch position. Example: `api.magnet.force_at(api.magnet.position())`."""
    cal, touch = _resolve(table)
    return cal.force(position_mm, touch)


def live_force(position_mm):
    """For the motor poller and the live display (decision 0018 item 1): {"force_pN", "force_calibration",
    "touch_mm"} at position_mm by the calibration in use, or None while it is not ready. Never raises for a missing
    touch position; pure arithmetic (no device call, no lock), so it costs microseconds off the frame path."""
    cal, touch = _state()
    if cal.needs_touch and touch is None:
        return None
    return {"force_pN": cal.force(position_mm, touch), "force_calibration": cal.name, "touch_mm": touch}


def set_force(force_pN, table=None):
    """Move the magnet to the position that gives force_pN by the calibration in use; returns a Motion.

    Decision 0018: a force outside the reachable range (the force at the magnet position-limit ends, 0017) is coerced
    to the nearest reachable force - no alarm - and a `coerced` event records requested, applied, reason and
    calibration. The Motion carries `requested_pN`, `applied_pN`, `coerced` and `position_mm`, so the GUI can rewrite
    the typed field with the applied value. table: a table (or calibration) for this call, else the session's (the
    live equation by default; it needs the touch position, else NotReady). The position then goes through move_to()
    (speed checked, position coerced again in the last step). Example: `api.magnet.set_force(2.0).wait(30)`.
    """
    cal, _ = _resolve(table)
    request = {"quantity": "magnet_force_pN", "value": force_pN, "calibration": cal.name}
    try:
        r = coerce_force(force_pN, table)
    except SafetyRefused as e:
        events.log("refused", request=request, reason=str(e))
        raise
    if r["coerced"]:
        events.log("coerced", request=request, applied=r["applied_pN"], position_mm=r["position_mm"],
                   reason=r["reason"], calibration=cal.name, touch_mm=r["touch_mm"])
    events.log("force_request", request=request, applied_pN=r["applied_pN"], position_mm=r["position_mm"],
               touch_mm=r["touch_mm"], **({"table_version": cal.version} if cal.kind == "table" else {}))
    m = move_to(r["position_mm"])
    m.requested_pN, m.applied_pN, m.coerced, m.position_mm = force_pN, r["applied_pN"], r["coerced"], r["position_mm"]
    return m
