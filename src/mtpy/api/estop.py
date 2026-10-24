"""The emergency-stop flag (decision 0007). While it is engaged every acting call raises NotReady.

The dedicated safety thread that sends stop commands to each device belongs to the device layer (phase 5, later
work packages); it engages this flag first so nothing new starts.
"""
import threading

from . import events
from .errors import SafetyRefused

_engaged = threading.Event()


def engage(reason="button"):
    _engaged.set()
    events.log("estop", extra={"action": "engage", "reason": reason})


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
