"""The focus z (ASI Tiger Z), in um. Focus moves invalidate nothing but are logged (U35).

    api.focus.move_to(3.5).wait(timeout_s=5)     # -> z read back, um
"""
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
