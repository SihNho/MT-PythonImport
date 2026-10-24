"""The magnet rotor (Autonics PMC-2HS), in signed turns.

    api.rotor.rotate(2.0).wait(timeout_s=10)     # two turns from where it is now; -> position read back (turns)
"""
from . import estop, events, safety
from ._act import precheck
from .devices import _move, service
from .errors import SafetyRefused


def rotate(turns, speed_turns_s=None):
    """Turn the rotor by `turns` (signed, relative to the position read now) and return a Motion.

    Safety: the TARGET (position now + turns) must lie inside the profile's `rotor_turns` window around the
    session-start position (kept by the device layer, never supplied by the caller); a given speed_turns_s inside
    `rotor_speed_turns_s` (None = the controller's current speed). The shipped profile v1 refuses every rotor move
    until a rig-admin verifies the window. Example: `api.rotor.rotate(-1.5).wait(10)`.
    The request is made at the first line: an emergency stop engaged from here on (even while the position is read,
    and even if released again) voids it (re-review l2s-wp2-r2).
    """
    gen = estop.generation()
    svc = service("rotor")
    dev = svc.require()
    if speed_turns_s is not None:
        try:
            safety.check("rotor_speed_turns_s", speed_turns_s)
        except SafetyRefused as e:
            events.log("refused", request={"quantity": "rotor_speed_turns_s", "value": speed_turns_s}, reason=str(e))
            raise
    if not safety._is_number(turns):
        precheck("rotor_turns", turns, origin=svc.origin)              # refuses with a `refused` event
    target = svc.call(dev.position, what="POS") + turns
    return _move("rotor", "rotor_turns", target, dev.position, origin=svc.origin, gen=gen,
                 send=lambda v: svc.call(dev.move_to, v, speed_turns_s, what=f"PAB {v!r} turns"))


def position():
    """The rotor position read back, turns (controller frame). Example: `api.rotor.position()`."""
    svc = service("rotor")
    return svc.call(svc.require().position, what="POS")
