"""The emergency-stop flag (decision 0007). While it is engaged every acting call raises NotReady.

The dedicated safety thread that sends stop commands to each device belongs to the device layer (phase 5, later
work packages); it engages this flag first so nothing new starts.
"""
import threading

from . import events

_engaged = threading.Event()


def engage(reason="button"):
    _engaged.set()
    events.log("estop", extra={"action": "engage", "reason": reason})


def clear():
    _engaged.clear()
    events.log("estop", extra={"action": "clear"})


def active():
    return _engaged.is_set()
