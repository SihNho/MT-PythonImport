"""Protocols (docs/design/api.md 2.6, docs/format/grammar.md), WP5: load, check, run, pause, resume, stop, edit.

    p = api.protocol.load("D:/protocols/clamp.mtprot")   # parse only: nothing runs, nothing moves
    api.protocol.check(p)              # {"ok", "errors", "warnings", "min_duration_s"}; errors as file:line:col
    api.protocol.run(p)                # checks again with the rig state, then runs on its own thread
    api.protocol.pause(); api.protocol.resume(); api.protocol.stop()
    api.protocol.wait(timeout_s=600)   # -> the final status()

The engine (`mtpy.protocol.engine`) calls only this public layer, so every step passes the rig safety profile, the
emergency stop and the read-back checks exactly like a manual action. One protocol runs at a time.
"""
import threading
from pathlib import Path

from . import estop, events
from .errors import NotReady, ScriptError, Timeout

EXTENSIONS = (".mtprot", ".mtseq", ".mtrec")
_engine = None
_draft = None
# One run at a time (review l2s-wp5-r1): the running() check, the check and the engine start happen under this lock,
# so two concurrent run() calls never both start and a running engine is never overwritten.
_run_lock = threading.Lock()


def load(script_or_path, file=None):
    """Parse a script (protocol, illumination sequence or analysis recipe) without executing anything.

    script_or_path: a `pathlib.Path`, a path string ending in .mtprot / .mtseq / .mtrec, or the script text.
    file: the name used in error messages (default: the file name, or "<text>"). Returns a `mtpy.protocol.Script`;
    raises ScriptError with every error as `<file>:<line>:<column>: <message>`."""
    from mtpy.protocol import parse
    s = script_or_path
    if isinstance(s, Path) or (isinstance(s, str) and "\n" not in s and s.strip().endswith(EXTENSIONS)):
        path = Path(s)
        return parse(path.read_text(encoding="utf-8"), file or path.name)
    return parse(s, file or "<text>")


def _script(s):
    return load(s) if isinstance(s, (str, Path)) else s


def check(script, devices=None):
    """Validate a protocol before it runs: every statement against the API (functions, argument units) and the rig
    safety profile; with devices (default: when devices are connected) also the rig state (devices connected, force
    table loaded and covering every force, focus window from the current position, acquisition running for
    `record`). Only reads. Returns {"ok", "errors", "warnings", "min_duration_s"}."""
    from mtpy.protocol.check import check as _check

    from . import devices as _devices
    if devices is None:
        devices = bool(_devices.status())
    return _check(_script(script), devices=devices)


def running():
    return _engine is not None and not _engine.done


def run(script, motion_timeout_s=120.0, ramp_step_s=0.5):
    """Check the protocol with the rig state and start it on the engine thread; returns status().

    Refused before anything runs: ScriptError (check errors, with a `refused` event), NotReady (a protocol is already
    running, or the emergency stop is engaged). motion_timeout_s: the longest wait for one move; ramp_step_s: the
    time between the force increments of a `ramp` (WP5 decision)."""
    global _engine, _draft
    from mtpy.protocol.check import require_ok
    from mtpy.protocol.engine import Engine
    script = _script(script)
    request = {"protocol": script.name, "file": script.file, "sha256": script.sha256}
    with _run_lock:                      # review l2s-wp5-r1: one run at a time, never overwritten
        if running():
            events.log("refused", request=request, reason=f"protocol {_engine.script.name!r} is already running")
            raise NotReady("a protocol is already running; api.protocol.stop() first")
        if estop.active():
            events.log("refused", request=request, reason="emergency stop engaged")
            raise NotReady("the emergency stop is engaged; release it before starting a protocol")
        report = check(script, devices=True)
        if not report["ok"]:
            events.log("refused", request=request, reason="protocol check failed",
                       errors=[str(d) for d in report["errors"]])
            require_ok(report)
        eng = Engine(script, motion_timeout_s, ramp_step_s)
        eng.start()
        _engine, _draft = eng, None
    return status()


def _require_engine():
    if _engine is None:
        raise NotReady("no protocol has been run; api.protocol.run(script) first")
    return _engine


def pause():
    """Pause at the next point the engine can hold: time stops counting in holds and waits (within ~20 ms), a move
    already sent finishes, the next step does not start. Returns status()."""
    eng = _require_engine()
    if eng.done:
        raise NotReady(f"the protocol is not running ({eng.state})")
    eng.pause()
    events.log("protocol", action="pause", name=eng.script.name)
    return status()


def resume():
    """Continue a paused protocol. Refused (NotReady) once the run has ended - in particular a run aborted by the
    emergency stop is never resumed: start it again. Returns status()."""
    eng = _require_engine()
    if eng.done or estop.active():
        why = eng.reason if eng.done else "the emergency stop is engaged"
        events.log("refused", request={"protocol": "resume", "name": eng.script.name}, reason=why)
        raise NotReady(f"the protocol cannot resume ({eng.state}): {why}")
    eng.resume()
    events.log("protocol", action="resume", name=eng.script.name)
    return status()


def stop():
    """Stop the protocol: the running move is stopped in place and no further step starts; the magnet, rotor,
    recording and lasers stay as they are (0007). Returns status() (call wait() for the final one)."""
    eng = _require_engine()
    if not eng.done:
        eng.request_stop()
        events.log("protocol", action="stop_requested", name=eng.script.name)
    return status()


def wait(timeout_s):
    """Wait until the protocol ends; returns the final status(). Timeout after timeout_s (the run continues)."""
    eng = _require_engine()
    if not eng.wait(timeout_s):
        raise Timeout(f"the protocol did not end within {timeout_s:g} s (state {eng.state})")
    return status()


def status():
    """{"state": idle | running | paused | completed | stopped | refused | failed | aborted, "reason", "name",
    "current" (the running step: step, line, statement, loop, target), "steps_done", "protocol_version",
    "edit_pending", "edits", ...}."""
    if _engine is None:
        return {"state": "idle"}
    return _engine.status()


def edit(draft):
    """Check a new version of the running protocol (U18) and keep it as the draft; it changes nothing until
    apply_edits(). Returns the check report.

    Refused (ScriptError, with a `protocol_edit` refused event), review l2s-wp5-r1:
    - a structural change against the version in force: only in-place value edits are allowed (same count, kind,
      form and nesting of every statement); inserting, deleting or moving a statement - also an identical repeated
      line, also after the running position - is refused, never ignored;
    - a check error (e.g. a force above the profile); the focus check uses the running protocol's own reference (the
      focus position read when it started), and a focus step in a run without that reference is refused."""
    global _draft
    from mtpy.protocol.check import check as _check
    from mtpy.protocol.check import structure_diff
    from mtpy.protocol.grammar import Diagnostic

    from . import devices as _devices
    eng = _require_engine()
    if eng.done:
        raise NotReady(f"the protocol is not running ({eng.state}); nothing to edit")
    script = _script(draft)
    diff = structure_diff(eng.script, script)
    if diff is not None:
        events.log("protocol_edit", action="refused", reason=diff[1], new_sha256=script.sha256)
        raise ScriptError([Diagnostic(script.file, diff[0], 1, diff[1])])
    report = _check(script, devices=bool(_devices.status()), run_focus_z0=eng.focus_z0)
    if not report["ok"]:
        events.log("protocol_edit", action="refused", reason="check failed", errors=[str(d) for d in report["errors"]])
        raise ScriptError(report["errors"], report["warnings"])
    _draft = script
    return report


def apply_edits():
    """Commit the checked draft: the engine takes it at the next step boundary (steps not started take it now, steps
    done in this loop pass from the next pass; the running step is locked). The engine logs `protocol_edit`
    applied - or refused, when the draft's structure differs from the version in force. Returns status()."""
    global _draft
    eng = _require_engine()
    if _draft is None:
        raise NotReady("no checked draft: api.protocol.edit(draft) first")
    if eng.done:
        raise NotReady(f"the protocol is not running ({eng.state})")
    eng.offer_edit(_draft)
    _draft = None
    return status()
