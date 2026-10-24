"""The Arduino frame divider (decision 0005): N JAI frames per EMCCD frame.

    api.sync.set_ratio(10)      # -> 10 read back
"""
import numbers

from ._act import acting
from .devices import service
from .errors import SafetyRefused


def set_ratio(n):
    """Set the divider ratio N (integer 1 .. 65536) and return the value read back. It changes how EMCCD frames map
    to JAI buffers, so it is refused while recording. Example: `api.sync.set_ratio(10)`."""
    svc = service("arduino")
    dev = svc.require()

    def check(v):
        if not (isinstance(v, numbers.Integral) and not isinstance(v, bool) and 1 <= v <= dev.RATIO_MAX):
            raise SafetyRefused(f"sync ratio {v!r} must be an integer in [1, {dev.RATIO_MAX}] (JAI frames per EMCCD "
                                "frame)")
        if svc.recording:
            raise SafetyRefused("the sync ratio cannot change while recording (no PC communication during a run, "
                                "decision 0005)")
        return True
    return acting("sync_ratio", n, lambda v: svc.call(dev.set_ratio, v, what=f"set N {v}"),
                  lambda: svc.call(dev.get_ratio, what="read N"), 0, device="arduino", check=check)
