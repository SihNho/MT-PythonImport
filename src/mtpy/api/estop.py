"""The emergency-stop flag (decision 0007). While it is engaged every acting call raises NotReady.

engage() raises the flag and the generation number first (nothing new starts, and every request made before it is
void even after clear()), then calls each device's stop directly on the engaging thread, not through the device
queues (WP2, `add_stopper`), and only after every stop attempt logs its events (a slow event subscriber never delays
a stop). The GUI button and the keyboard backup (0007) come later.

Send guard (review l2s-wp2-r1): an acting call records the generation number (and its Motion's cancel flag) when it
is made and runs its device send inside `guarded_send(...)`; the device service checks `invalid(guard)` right before
the send (invalid -> nothing is sent) and right after it (invalid -> the device is stopped again).
"""
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from . import events
from .errors import SafetyRefused

_engaged = threading.Event()
_stoppers = []
_gen_lock = threading.Lock()
_generation = 0
_send_guard = ContextVar("mtpy_send_guard", default=None)


def add_stopper(fn):
    """Register fn() to be called directly (not through a device queue) when the stop is engaged. The device layer
    registers each device's stop here. Returns a function that removes it."""
    _stoppers.append(fn)

    def remove():
        if fn in _stoppers:
            _stoppers.remove(fn)
    return remove


def engage(reason="button"):
    """Raise the flag and the generation number, then call every registered stop directly, each on its own so one
    failure does not skip the others, and only then log the `estop` event and one `estop_error` event per failed
    stopper (subscribers are notified after every stop was attempted)."""
    global _generation
    with _gen_lock:
        _generation += 1
        _engaged.set()
    failed = []
    for fn in _stoppers.copy():
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - one failed stop must not keep the other devices moving
            failed.append((fn, e))
    events.log("estop", extra={"action": "engage", "reason": reason})
    for fn, e in failed:
        events.log("estop_error", stopper=getattr(fn, "__qualname__", repr(fn)), error=f"{type(e).__name__}: {e}")


_CLEAR_CALLERS = ("gui", "rig-admin")


def clear():
    """Release the emergency stop. Only the GUI (the operator's release button) or 'rig-admin' may do this.

    A script, a plug-in, the AI gateway or undeclared code ('unknown') gets SafetyRefused and a `refused` event; the
    stop stays engaged. Like the admin-session check this is a guard against mistakes, NOT real protection: any code
    in the process can set its own caller name. Real protection (GUI login, rig-admin role) is phase 8 work.
    The generation number is NOT reset: a request made before the stop stays void after the release.
    """
    who = events.caller()
    if who not in _CLEAR_CALLERS:
        events.log("refused", request={"estop": "clear"}, reason=f"caller {who!r} may not clear the emergency stop")
        raise SafetyRefused(f"only the operator (GUI) or rig-admin may clear the emergency stop, not {who!r}")
    _engaged.clear()
    events.log("estop", extra={"action": "clear"})


def active():
    return _engaged.is_set()


def generation():
    """How many times the stop has been engaged in this process; a request made at generation g is void once this
    differs from g."""
    return _generation


@contextmanager
def guarded_send(gen, cancel=None):
    """Run a block whose device sends are checked against generation `gen` and the threading.Event `cancel`."""
    token = _send_guard.set((gen, cancel))
    try:
        yield
    finally:
        _send_guard.reset(token)


def send_guard():
    """The (generation, cancel) guard of the current context, or None outside an acting call's send."""
    return _send_guard.get()


def invalid(guard):
    """Why a send made under `guard` must not happen or must be undone, or None while it is still valid."""
    gen, cancel = guard
    if _engaged.is_set() or _generation != gen:
        return "emergency stop engaged since the request was made"
    if cancel is not None and cancel.is_set():
        return "cancelled"
    return None
