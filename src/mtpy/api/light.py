"""Lasers, manual on / off (U24). The illumination sequence run by the Arduino (load / start / stop) comes later.

    api.light.set("532", True)     # -> True read back
"""
from ._act import acting
from .devices import service
from .errors import SafetyRefused


def set(laser, on):
    """Switch one laser ("532" or "637") on or off and return the state read back. Refused for an unknown laser or a
    non-bool `on`; emergency stop -> NotReady. Example: `api.light.set("637", False)`."""
    svc = service("light")
    dev = svc.require()

    def check(v):
        if laser not in dev.LASERS or not isinstance(v, bool):
            raise SafetyRefused(f"light.set needs laser in {dev.LASERS} and on True/False; got {laser!r}, {v!r}")
        return True
    return acting(f"light_{laser}", on, lambda v: svc.call(dev.set, laser, v, what=f"{laser} {'on' if v else 'off'}"),
                  lambda: svc.call(dev.get, laser, what=f"read {laser}"), 0.0, device="light", check=check,
                  match=lambda got: got is on)
