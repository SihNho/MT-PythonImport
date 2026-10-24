"""In-process event log and the caller context (docs/design/api.md sections 1 and 3).

Every acting call logs an Event with the caller that made it. Subscribers (the HDF5 writer of WP4, the GUI log view)
receive each event as it is logged. Who calls is held in a context variable, so a script, a plug-in or the AI gateway
runs inside `as_caller(...)` and every event it causes carries its name.
"""
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

# 'unknown' is the honest default: code that did not declare itself is logged as such, never as the GUI.
_CALLER_FORMS = re.compile(r"^(unknown|gui|rig-admin|script:[^@\s]+@[^@\s]+|plugin:\S+|"
                           r"ai:(read|propose|run_approved|autonomous))$")
_caller = ContextVar("mtpy_caller", default="unknown")


def caller():
    """Who is calling now: 'gui', 'rig-admin', 'script:<name>@<version>', 'plugin:<name>', 'ai:<tier>' or 'unknown'."""
    return _caller.get()


@contextmanager
def as_caller(name):
    """Run a block as `name`. Example: `with as_caller("script:cleavage@1.2"): api.magnet.move_to(5.0)`."""
    if not _CALLER_FORMS.match(name):
        raise ValueError(f"caller {name!r} is not one of 'gui', 'rig-admin', 'script:<name>@<version>', "
                         "'plugin:<name>', 'ai:<read|propose|run_approved|autonomous>'")
    token = _caller.set(name)
    try:
        yield
    finally:
        _caller.reset(token)


@dataclass(frozen=True)
class Event:
    t: float                      # time.time() when logged
    kind: str                     # 'act', 'refused', 'device_error', 'estop', 'safety_profile', ...
    caller: str
    request: object = None        # what was asked, e.g. {"quantity": "magnet_position_mm", "value": 5.0}
    readback: object = None       # what the device read back
    extra: dict = field(default_factory=dict)


_lock = threading.Lock()
_events = []
_subscribers = []


def _append(ev):
    with _lock:
        _events.append(ev)
        return list(_subscribers)


def log(kind, request=None, readback=None, **extra):
    """Append an event (caller from the current context), hand it to every subscriber, return it.

    Never raises because of a subscriber: an exception from one subscriber does not stop delivery to the others and
    does not reach the acting call (whose own SafetyRefused / DeviceError is what the caller must see). Each failure
    is recorded once as a `subscriber_error` event; that event is delivered to the subscribers that did not fail,
    and a failure while delivering it is swallowed, not recorded again (no recursion).
    """
    ev = Event(time.time(), kind, caller(), request, readback, extra)
    subs = _append(ev)
    failed = []
    for fn in subs:
        try:
            fn(ev)
        except Exception as e:  # noqa: BLE001 - a broken subscriber must never break the acting call
            failed.append((fn, e))
    for fn, e in failed:
        err = Event(time.time(), "subscriber_error", ev.caller, None, None,
                    {"subscriber": getattr(fn, "__qualname__", repr(fn)), "event_kind": ev.kind,
                     "error": f"{type(e).__name__}: {e}"})
        _append(err)
        for other in subs:
            if all(other is not f for f, _ in failed):
                try:
                    other(err)
                except Exception:  # noqa: BLE001, S110 - recorded once only, never recursively
                    pass
    return ev


def events(since=None):
    """All events, or those logged after time `since` (seconds, time.time())."""
    with _lock:
        return [e for e in _events if since is None or e.t > since]


def subscribe(fn):
    """Call fn(event) for every event logged from now on. Returns a function that unsubscribes."""
    with _lock:
        _subscribers.append(fn)

    def unsubscribe():
        with _lock:
            if fn in _subscribers:
                _subscribers.remove(fn)
    return unsubscribe
