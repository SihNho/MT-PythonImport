"""The focus z (ASI Tiger Z), in um. Focus moves invalidate nothing but are logged (U35).

    api.focus.move_to(3.5).wait(timeout_s=5)     # -> z read back, um
"""
from . import events
from .devices import _move, service


def move_to(z_um):
    """Move the focus to z_um and return a Motion.

    Safety: z_um inside the profile's `focus_z_um` window around the session-start position (kept by the device
    layer). The shipped profile v1 has no focus window yet, so every focus move is refused until a rig-admin sets
    one. Example: `api.focus.move_to(3.5).wait(5)`.
    """
    svc = service("focus")
    dev = svc.require()
    return _move("focus", "focus_z_um", z_um, dev.position, origin=svc.origin)


def position():
    """The focus z read back, um. Example: `api.focus.position()`."""
    svc = service("focus")
    return svc.call(svc.require().position, what="WHERE Z")


def speed():
    """The focus drive's speed read back (mm/s on the ASI Tiger)."""
    svc = service("focus")
    return svc.call(svc.require().speed, what="S Z?")


def set_speed(mm_s):
    """Set the focus drive's speed (mm/s); the device refuses faster than the speed it opened with and restores that
    speed at close. Owner 2026-11-01: the bench compares the current speed with 1/10 of it. Returns the read-back."""
    if not (isinstance(mm_s, (int, float)) and not isinstance(mm_s, bool) and mm_s > 0):
        raise ValueError(f"focus speed {mm_s!r} must be a positive number (mm/s)")
    svc = service("focus")
    got = svc.call(svc.require().set_speed, mm_s, what=f"S Z={mm_s}")
    events.log("setting", device="focus", speed_mm_s=mm_s, readback=got)
    return got
