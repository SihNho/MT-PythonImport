"""The sample stage x/y (ASI Tiger), in mm.

    api.stage.move_to(-1.5, -2.5).wait(timeout_s=10)    # -> (x, y) read back, mm
"""
import math

from . import safety
from .devices import _move, service


def move_to(x_mm, y_mm):
    """Move the stage to (x_mm, y_mm) and return a Motion.

    Safety: x and y each inside the profile's `stage_x_mm` / `stage_y_mm` window around the session-start position
    (kept by the device layer). At a controller limit (SL/SU) the stage stops without an error, so the read-back
    differs and wait() raises DeviceError. Example: `api.stage.move_to(-1.8, -2.7).wait(10)`.
    """
    svc = service("stage")
    dev = svc.require()
    ox, oy = svc.origin

    def check(v):
        return safety.check("stage_x_mm", v[0], ox) & safety.check("stage_y_mm", v[1], oy)

    def match(got):
        return all(math.isfinite(g) and abs(g - w) <= dev.tol for g, w in zip(got, (x_mm, y_mm)))
    return _move("stage", "stage_xy_mm", (x_mm, y_mm), dev.position, origin=svc.origin, check=check, match=match)


def position():
    """The stage (x, y) read back, mm. Example: `api.stage.position()`."""
    svc = service("stage")
    return svc.call(svc.require().position, what="WHERE X Y")
