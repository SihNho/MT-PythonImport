"""Device interfaces, device services and simulators (phase 5, WP2). Used through `mtpy.api`, never directly by
scripts, plug-ins or the AI gateway.

`make(rig)` builds the devices named by a rig preset: `{"backend": "sim"}` (every device simulated) or
`{"backend": "real"}` (phase 6: the real JAI camera through IMAQdx under the rig lock, `jai.py`; motors simulated) or
`{"backend": "real-motors"}` (phase 7: the camera and the PI / ASI / Autonics drivers `pi.py`, `asi.py`,
`autonics.py` = the project's motion gate, docs/design/motion-gate.md; Arduino and lights still simulated). Real
drivers take the shared rig lock before every send (CLAUDE.md "The rig").

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
    if backend == "real-motors":
        # phase 7: the motion gate (docs/design/motion-gate.md) - only after the owner's approval of that page
        from .asi import AsiFocus, AsiStage
        from .autonics import AutonicsRotor
        from .jai import JaiCamera
        from .pi import PiMagnet
        return {**make_rig(), "camera": JaiCamera(), "magnet": PiMagnet(), "stage": AsiStage(), "focus": AsiFocus(),
                "rotor": AutonicsRotor()}
    raise NotImplementedError(f"device backend {backend!r} does not exist; use the rig preset "
                              "{'backend': 'sim'}, {'backend': 'real'} (camera) or {'backend': 'real-motors'}")


__all__ = ["IMMEDIATE", "NAMES", "NEEDS_PAUSE", "Device", "DeviceService", "Motion", "make"]
