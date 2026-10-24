"""Device interfaces, device services and simulators (phase 5, WP2). Used through `mtpy.api`, never directly by
scripts, plug-ins or the AI gateway.

`make(rig)` builds the devices named by a rig preset. Only `{"backend": "sim"}` exists; real drivers (JAI / IMAQdx,
PI C-863, ASI Tiger, Autonics PMC-2HS, Arduino, OBIS) come in phases 6/7 and must take the shared rig lock and go
through the approved motion gate (CLAUDE.md "The rig").
"""
from .base import IMMEDIATE, NEEDS_PAUSE, Device, DeviceService, Motion

NAMES = ("camera", "magnet", "rotor", "stage", "focus", "arduino", "light")


def make(rig):
    """{name: Device} for the rig preset. `{"backend": "sim", "fixture": <folder or None>}`; others raise
    NotImplementedError until the real drivers exist."""
    backend = rig.get("backend")
    if backend != "sim":
        raise NotImplementedError(f"device backend {backend!r} does not exist yet (real drivers come in phases 6/7); "
                                  "use the rig preset {'backend': 'sim'}")
    from .sim import make_rig
    return make_rig(fixture=rig.get("fixture"))


__all__ = ["IMMEDIATE", "NAMES", "NEEDS_PAUSE", "Device", "DeviceService", "Motion", "make"]
