"""The emergency-stop flag (decision 0007). While it is engaged every acting call raises NotReady.

engage() sets the flag first (nothing new starts), then calls each device's stop directly on the engaging thread,
not through the device queues (WP2, `add_stopper`). The GUI button and the keyboard backup (0007) come later.
"""
import threading

from . import events
from .errors import SafetyRefused

_engaged = threading.Event()
_stoppers = []


def add_stopper(fn):
    """Register fn() to be called directly (not through a device queue) when the stop is engaged. The device layer
    registers each device's stop here. Returns a function that removes it."""
    _stoppers.append(fn)

    def remove():
        if fn in _stoppers:
            _stoppers.remove(fn)
    return remove


def engage(reason="button"):
    """Set the flag first (nothing new starts), then call every registered stop directly. A stopper that fails is
    logged as an `estop_error` event and does not keep the others from running."""
    _engaged.set()
    events.log("estop", extra={"action": "engage", "reason": reason})
    for fn in _stoppers.copy():
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - one failed stop must not keep the other devices moving
            events.log("estop_error", stopper=getattr(fn, "__qualname__", repr(fn)), error=f"{type(e).__name__}: {e}")


_CLEAR_CALLERS = ("gui", "rig-admin")


def clear():
    """Release the emergency stop. Only the GUI (the operator's release button) or 'rig-admin' may do this.

    A script, a plug-in, the AI gateway or undeclared code ('unknown') gets SafetyRefused and a `refused` event; the
    stop stays engaged. Like the admin-session check this is a guard against mistakes, NOT real protection: any code
    in the process can set its own caller name. Real protection (GUI login, rig-admin role) is phase 8 work.
    """
    who = events.caller()
    if who not in _CLEAR_CALLERS:
        events.log("refused", request={"estop": "clear"}, reason=f"caller {who!r} may not clear the emergency stop")
        raise SafetyRefused(f"only the operator (GUI) or rig-admin may clear the emergency stop, not {who!r}")
    _engaged.clear()
    events.log("estop", extra={"action": "clear"})


def active():
    return _engaged.is_set()
