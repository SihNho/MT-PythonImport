"""The protocol engine (decision 0012, grammar.md section 3; WP5): runs a checked protocol step by step on its own
thread, ONLY through the public function layer `mtpy.api` - it never calls a device, so every rig-safety check
(profile, emergency stop, refusals) applies to each step exactly as to a manual action.

- **Events:** `protocol` (action start / pause / resume / stop_requested / end; `warning` before `zero`, WP6),
  `protocol_step` (phase start / end / refused / failed / stopped / aborted, with the line, the statement, the loop
  iteration and the protocol version) and `protocol_edit` (applied / refused; `replaced` when a pending draft is
  replaced by a newer one, WP6). They go through `api.events.log`, so while recording they reach the HDF5
  `/events` like every other event. The run's caller is `script:<name>@<sha256[:12]>`.
- **Refusal:** a step the API refuses (SafetyRefused) ends the run as `refused`; a device error, a time-out or any
  other API error ends it as `failed`. Nothing is skipped silently and the next step never starts.
- **Emergency stop (0007):** the API stops every axis directly; the engine sees the stop (flag or generation number
  changed since the run started), ends the run as `aborted` and never moves anything afterwards - not after the
  stop is released, and `resume()` cannot restart it.
- **Stop:** the running move is cancelled (stopped in place, 0007 "graceful abort"); nothing else is changed: the
  magnet, rotor, recording and lasers stay as they are.
- **Pause:** time stops counting in holds, waits and between ramp increments within ~20 ms; a move already sent
  finishes; the next step does not start until resume. The magnet stays where it is.
- **Waits:** every move is waited for with `Motion.wait` in short slices (so stop and the emergency stop are seen)
  up to `motion_timeout_s`; past it the move is cancelled and the run fails with Timeout.
- **Mid-run edits (U18, minimal; review l2s-wp5-r1):** only in-place VALUE edits: the new version must keep the
  count, kind, form and nesting of every statement. It is applied at the next step boundary (or loop-pass
  boundary); steps not started take it at once, steps already done in this loop pass take it in the next pass (each
  statement is looked up in the version in force when it starts). The running step is locked. Any structural
  change (a statement inserted, deleted or moved, anywhere - also an identical repeated line, also after the running
  position) is refused with a `protocol_edit` event and the run continues unchanged.
- **Run scope (review l2s-wp5-r1):** the whole run runs inside `api.estop.run_scope(generation at start)`, so every
  request of the run is void - nothing is sent - once an emergency stop was engaged after the run started, even when
  the request itself was made after the release (e.g. during a step-start event or a device pre-read).
"""
import math
import threading
import time

from mtpy import api

from .check import structure_diff, walk

FINAL = ("completed", "stopped", "refused", "failed", "aborted")


class _End(Exception):
    def __init__(self, state, reason):
        super().__init__(reason)
        self.state, self.reason = state, reason


_READ = object()


class Engine:
    def __init__(self, script, motion_timeout_s=120.0, ramp_step_s=0.5, gen=None, focus_z0=_READ):
        """gen: the emergency-stop generation of the run (api.protocol.run passes the one in force when it was
        called, WP6; None = read in start()). focus_z0: the focus reference read once by api.protocol.run (WP6;
        None = the run has no reference); left out, start() reads it when the script has a focus step."""
        if not (motion_timeout_s > 0 and ramp_step_s > 0):
            raise ValueError("motion_timeout_s and ramp_step_s must be > 0")
        self.script, self.version, self.caller = script, 0, script.caller
        self.motion_timeout_s, self.ramp_step_s = float(motion_timeout_s), float(ramp_step_s)
        self._lock = threading.Lock()
        self._stop, self._pause, self._done = threading.Event(), threading.Event(), threading.Event()
        self._abort = None        # decision 0019: the reason a magnet stall aborted the run (set from any thread)
        self._pending = None
        self._pos = []            # per nesting level: the index of the statement (ancestors: the running loops)
        self._gen = gen
        self._ordinal = self._ordinals(script)
        self.state, self.reason, self.current = "ready", None, None
        self.steps_done, self.edits = 0, []
        self._read_focus, self.focus_z0 = focus_z0 is _READ, None if focus_z0 is _READ else focus_z0
        self.t_start = self.t_end = None

    @staticmethod
    def _ordinals(script):
        return {id(s): n for n, s in enumerate(walk(script.body), 1)}

    # --- control (any thread) -------------------------------------------------------------------------------------
    def start(self):
        if self._gen is None:
            self._gen = api.estop.generation()       # an emergency stop from here on aborts the run for good
        if self._read_focus and any(x.kind == "focus" for x in walk(self.script.body)):
            # `focus um=` is relative to this; read before the thread starts, so a mid-run edit is always checked
            # against the same reference the engine uses (review l2s-wp5-r1). None = this run has no reference.
            self.focus_z0 = api.focus.position()
        self.state, self.t_start = "running", time.time()
        threading.Thread(target=self._main, name="protocol-engine", daemon=True).start()

    def request_stop(self):
        self._stop.set()

    def abort(self, reason):
        """Decision 0019 (magnet stall): end the run as `aborted` at the next check; the running move is NOT
        cancelled from here (the stall response moves the magnet itself), and no further step starts."""
        self._abort = reason

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    def offer_edit(self, script):
        """Queue a checked new version; applied (or refused) at the next step boundary. A draft still pending is
        replaced by the new one, and that replacement is a `protocol_edit` event (action `replaced`, WP6 carry), so
        a draft that never ran is never dropped silently."""
        with self._lock:
            old, self._pending = self._pending, script
        if old is not None:
            api.events.log("protocol_edit", action="replaced", reason="a newer draft was offered before this one was "
                           "applied; it is never applied", old_sha256=old.sha256, new_sha256=script.sha256,
                           protocol_version=self.version)

    def wait(self, timeout_s):
        return self._done.wait(timeout_s)

    @property
    def done(self):
        return self._done.is_set()

    def status(self):
        with self._lock:
            return {"state": self.state, "reason": self.reason, "name": self.script.name, "file": self.script.file,
                    "sha256": self.script.sha256, "protocol_version": self.version, "caller": self.caller,
                    "current": dict(self.current) if self.current else None, "steps_done": self.steps_done,
                    "paused_requested": self._pause.is_set(), "stop_requested": self._stop.is_set(),
                    "edit_pending": self._pending is not None, "edits": list(self.edits),
                    "t_start": self.t_start, "t_end": self.t_end}

    # --- engine thread --------------------------------------------------------------------------------------------
    def _main(self):
        # run_scope: every acting call of this run (moves, their pre-reads and the device sends) is void once the
        # run's generation is no longer current, composed with each request's own generation (review l2s-wp5-r1)
        with api.events.as_caller(self.caller), api.estop.run_scope(self._gen):
            s = self.script
            api.events.log("protocol", action="start", name=s.name, file=s.file, sha256=s.sha256, grammar=s.grammar,
                           type=s.meta.get("type"), text=s.text, rules=len(s.rules),
                           rules_evaluated=False if s.rules else None, focus_z0=self.focus_z0)
            state, reason = "completed", None
            try:
                self._block(0, ())
            except _End as e:
                state, reason = e.state, e.reason
            except Exception as e:  # noqa: BLE001 - an engine bug must still end the run visibly
                state, reason = "failed", f"engine error: {type(e).__name__}: {e}"
            with self._lock:
                self.state, self.reason, self.current, self.t_end = state, reason, None, time.time()
            api.events.log("protocol", action="end", state=state, reason=reason, name=s.name,
                           protocol_version=self.version, steps_done=self.steps_done)
            self._done.set()

    def _set_state(self, state):
        if self.state != state:
            with self._lock:
                self.state = state

    def _estopped(self):
        return api.estop.active() or api.estop.generation() != self._gen

    def _check(self):
        if self._estopped():
            raise _End("aborted", "emergency stop engaged: the run is aborted and never resumes motion by itself; "
                                  "start the protocol again after the stop is released")
        if self._abort:
            raise _End("aborted", f"{self._abort}: the run is aborted; the magnet stall response returns the "
                                  "magnet to 0 mm")
        if self._stop.is_set():
            raise _End("stopped", "stopped by the operator; magnet, rotor, recording and lasers left as they are")

    def _body_at(self, depth):
        body = self.script.body
        for idx in self._pos[:depth]:
            body = body[idx].body
        return body

    def _boundary(self):
        """Between steps (or loop passes): stop / emergency stop, a pending edit, pause."""
        self._check()
        self._apply_edit()
        while self._pause.is_set():
            self._set_state("paused")
            time.sleep(0.02)
            self._check()
            self._apply_edit()
        self._set_state("running")

    def _block(self, depth, loops):
        self._pos.append(0)
        try:
            i = 0
            while True:
                self._pos[depth] = i
                self._boundary()
                body = self._body_at(depth)
                if i >= len(body):
                    return
                st = body[i]
                if st.kind == "loop":
                    k = 0
                    while True:
                        if k:
                            self._boundary()
                        st = self._body_at(depth)[i]            # the version in force at each pass
                        if k >= st.args["n"].value:
                            break
                        self._block(depth + 1, (*loops, k + 1))
                        k += 1
                else:
                    self._step(st, loops)
                i += 1
        finally:
            self._pos.pop()

    # --- mid-run edits ----------------------------------------------------------------------------------------------
    def _apply_edit(self):
        """Review l2s-wp5-r1: only in-place value edits are applied. The structure (count, kind, form and nesting
        of every statement) must be the same as the version in force - api.protocol.edit refuses a structural change
        first; this re-check at the boundary keeps the rule if a draft reaches the engine another way."""
        with self._lock:
            new, self._pending = self._pending, None
        if new is None:
            return
        diff = structure_diff(self.script, new)
        why = None if diff is None else f"structural change refused: {diff[1]}"
        old = self.script
        if why:
            rec = {"result": "refused", "reason": why, "sha256": new.sha256}
            api.events.log("protocol_edit", action="refused", reason=why, new_sha256=new.sha256,
                           protocol_version=self.version)
        else:
            with self._lock:
                self.script, self.version = new, self.version + 1
                self._ordinal = self._ordinals(new)
            rec = {"result": "applied", "new_version": self.version, "sha256": new.sha256}
            api.events.log("protocol_edit", action="applied", new_version=self.version, old_sha256=old.sha256,
                           new_sha256=new.sha256, old_text=old.text, new_text=new.text,
                           applies_from="next step not yet started; steps done in this loop pass from the next pass",
                           path=list(self._pos))
        with self._lock:
            self.edits.append(rec)

    # --- steps ------------------------------------------------------------------------------------------------------
    def _info(self, st, loops):
        target = {k: a.value for k, a in st.args.items()}
        if st.pos:
            target["args"] = [a.value for a in st.pos]
        if st.form:
            target["form"] = st.form
        return {"step": self._ordinal.get(id(st), -1), "line": st.line, "statement": st.text,
                "loop": loops[-1] if loops else -1, "loops": list(loops), "path": list(self._pos),
                "protocol_version": self.version, "target": target}

    def _step(self, st, loops):
        info = self._info(st, loops)
        with self._lock:
            self.current = info
        api.events.log("protocol_step", phase="start", **info)
        try:
            extra = getattr(self, f"_do_{st.kind}", self._not_runnable)(st) or {}
        except _End as e:
            api.events.log("protocol_step", phase=e.state, reason=e.reason, **info)
            raise
        except api.MtpyError as e:
            if self._estopped():
                end = _End("aborted", f"emergency stop engaged during line {st.line} '{st.text}': the run is aborted "
                                      f"and never resumes motion by itself ({type(e).__name__}: {e})")
            elif isinstance(e, api.MagnetStall) or self._abort:
                end = _End("aborted", f"magnet stall during line {st.line} '{st.text}' (decision 0019): {e}")
            elif self._stop.is_set():
                end = _End("stopped", f"stopped by the operator during line {st.line} '{st.text}'")
            elif isinstance(e, api.SafetyRefused):
                end = _End("refused", f"line {st.line} '{st.text}' was refused by the API: {e}")
            else:
                end = _End("failed", f"line {st.line} '{st.text}' failed: {type(e).__name__}: {e}")
            api.events.log("protocol_step", phase=end.state, reason=end.reason, error=type(e).__name__, **info)
            raise end from e
        api.events.log("protocol_step", phase="end", **info, **extra)
        with self._lock:
            self.steps_done += 1

    def _motion(self, start):
        """Start a move (an API call returning a Motion) and wait for it in short slices; stop -> cancel."""
        m = start()
        t_end = time.monotonic() + self.motion_timeout_s
        while True:
            if self._stop.is_set() and not m.done:
                m.cancel()
                try:
                    m.wait(5.0)
                except api.MtpyError:
                    pass
                self._check()
            try:
                return m.wait(0.05)
            except api.Timeout:
                if time.monotonic() > t_end:
                    m.cancel()
                    try:
                        m.wait(5.0)
                    except api.MtpyError:
                        pass
                    raise api.Timeout(f"{m.what} not finished within {self.motion_timeout_s:g} s; stopped in "
                                      "place") from None

    def _sleep(self, t):
        """Wait t seconds of protocol time: paused time does not count; stop / emergency stop end it."""
        remaining, last = float(t), time.monotonic()
        while True:
            self._check()
            now = time.monotonic()
            if self._pause.is_set():
                self._set_state("paused")
            else:
                self._set_state("running")
                remaining -= now - last
            last = now
            if remaining <= 0:
                return
            time.sleep(min(0.02, remaining))

    def _a(self, st, key, default=None):
        a = st.args.get(key)
        return default if a is None else a.value

    def _do_zero(self, st):
        # WP6 carry: said BEFORE the move, so nobody takes `zero` for the U12 tracking zero (owner question open)
        api.events.log("protocol", action="warning", line=st.line, name=self.script.name, level="warning",
                       reason="'zero' moves the magnet to 0 mm only (decision 0016 item 2); the tracking zero (U12) "
                              "is NOT set")
        self._motion(lambda: api.magnet.move_to(0.0))
        self._sleep(self._a(st, "t"))
        return {"note": "magnet at 0 mm (top); the tracking zero is NOT set: api.tracking.zero does not exist yet"}

    def _do_hold(self, st):
        self._motion(lambda: api.magnet.set_force(self._a(st, "f")))
        self._sleep(self._a(st, "t"))

    def _do_ramp(self, st):
        f0, f1, t = self._a(st, "from"), self._a(st, "to"), self._a(st, "t")
        n = max(1, math.ceil(t / self.ramp_step_s - 1e-9))
        self._motion(lambda: api.magnet.set_force(f0))
        for k in range(1, n + 1):
            self._sleep(t / n)
            self._check()
            f = f0 + (f1 - f0) * k / n
            self._motion(lambda f=f: api.magnet.set_force(f))
        return {"increments": n, "increment_s": t / n}

    def _do_move(self, st):
        self._motion(lambda: api.magnet.move_to(self._a(st, "mm")))
        self._sleep(self._a(st, "t", 0.0))

    def _do_rotate(self, st):
        f0, f1, t = self._a(st, "from"), self._a(st, "to"), self._a(st, "t")
        speed = abs(f1 - f0) / t
        self._motion(lambda: api.magnet.set_force(self._a(st, "f")))
        origin = api.devices.info("rotor")["origin"]
        rel = api.rotor.position() - origin
        self._check()          # an emergency stop during the pre-read; the run scope also voids the move itself
        if abs(f0 - rel) > 1e-9:
            self._motion(lambda: api.rotor.rotate(f0 - rel, speed_turns_s=speed))
        self._check()
        self._motion(lambda: api.rotor.rotate(f1 - f0, speed_turns_s=speed))
        return {"speed_turns_s": speed}

    def _do_focus(self, st):
        self._motion(lambda: api.focus.move_to(self.focus_z0 + self._a(st, "um")))

    def _do_record(self, st):
        if st.form in ("on", "timed"):
            api.acq.set_recording(True, name=self.script.name)
        if st.form == "timed":
            self._sleep(self._a(st, "t"))
        if st.form in ("off", "timed"):
            api.acq.set_recording(False)

    def _do_mark(self, st):
        text = st.pos[0].value
        if api.acq.running():
            api.acq.mark(text)
        else:
            api.events.log("mark", text=text)

    def _do_wait(self, st):
        if st.form != "time":
            raise _End("failed", f"line {st.line}: 'wait until' cannot run yet (no api.events.rule)")
        self._sleep(self._a(st, "t"))

    def _do_end_protocol(self, st):
        """`end protocol` (decision 0016 item 3): switch recording off through the API (acquisition and the live
        display keep running) and end the run. Without it, recording simply continues after the protocol."""
        was = bool(api.acq.running() and api.acq.status().get("recording"))
        # logged BEFORE the switch, so while recording it reaches the run file ahead of the recording-off event
        api.events.log("protocol", action="end_statement", line=st.line, name=self.script.name,
                       recording_switched_off=was, note=None if was else "recording was not on; nothing switched off")
        if was:
            api.acq.set_recording(False)
        raise _End("completed", f"'end protocol' at line {st.line}"
                                + ("; recording switched off" if was else "; recording was not on"))

    def _do_stop(self, st):
        raise _End("completed", f"'stop' at line {st.line}")

    def _not_runnable(self, st):                 # light / if / on: refused by the checker, so never reached
        raise _End("failed", f"line {st.line}: '{st.kind}' cannot run in this version")
