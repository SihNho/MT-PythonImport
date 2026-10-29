"""Device interfaces, device services and simulators (phase 5, WP2). Used through `mtpy.api`, never directly by
scripts, plug-ins or the AI gateway.

`make(rig)` builds the devices named by a rig preset: `{"backend": "sim"}` (every device simulated) or
`{"backend": "real"}` (phase 6: the real JAI camera through IMAQdx under the rig lock, `jai.py`; the motors, Arduino
and lights stay simulated until phase 7). Real drivers (PI C-863, ASI Tiger, Autonics PMC-2HS, Arduino, OBIS) must
take the shared rig lock and go through the approved motion gate (CLAUDE.md "The rig").

Import order (WP6, the WP3 carry "mtpy.api <-> mtpy.devices cycle"): `mtpy.devices.base` uses `mtpy.api.estop` /
`events`, and `mtpy.api` uses this package. `mtpy.api` is therefore loaded first here, and `mtpy.api.camera` takes
NEEDS_PAUSE from `mtpy.devices.base`, so `import mtpy.devices` and `import mtpy.api` both work in either order
(test `test_import_order_devices_first_works`).
"""
import mtpy.api  # noqa: F401 - must load before .base (see above)

from .base import IMMEDIATE, NEEDS_PAUSE, Device, DeviceService, Motion

NAMES = ("camera", "magnet", "rotor", "stage", "focus", "arduino", "light")


def make(rig):
    """{name: Device} for the rig preset. `{"backend": "sim", "fixture": <folder or None>}` or `{"backend": "real"}`;
    others raise NotImplementedError."""
    backend = rig.get("backend")
    from .sim import make_rig
    if backend == "sim":
        return make_rig(fixture=rig.get("fixture"))
    if backend == "real":
        from .jai import JaiCamera
        return {**make_rig(), "camera": JaiCamera()}
    raise NotImplementedError(f"device backend {backend!r} does not exist (real motors come in phase 7); "
                              "use the rig preset {'backend': 'sim'} or {'backend': 'real'}")


__all__ = ["IMMEDIATE", "NAMES", "NEEDS_PAUSE", "Device", "DeviceService", "Motion", "make"]
