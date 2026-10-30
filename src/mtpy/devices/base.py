"""Device layer base: the `Device` interface, the `DeviceService` that owns one device in its own thread, and the
`Motion` handle (decision 0015 item 1; docs/design/api.md sections 1 and 3; ui-requirements U8, U17).

- Every call to a device runs on its service thread, in a copy of the CALLER's context (contextvars), so an event
  logged there names the real caller. Nothing here runs on the frame acquisition path; frames come from the camera's
  own producer, never through a service queue.
- The only call that bypasses the queue is `Device.stop()`: the emergency stop calls it directly from the engaging
  thread (decision 0007: "never queued behind busy loops") and `Motion.cancel()` from the cancelling thread, so
  every `stop()` must be thread-safe.
- A device send of an acting call is checked against the emergency-stop generation and the Motion's cancel flag
  right before and right after it (`DeviceService._send`, review l2s-wp2-r1).
  Real-device seam: a real driver's stop() needs its own way onto the port (a second handle or a port lock that the
  service thread releases between commands); the simulators only set a flag.
- The service keeps the session-start origin for relative windows (ASI x/y, rotor, focus), read once at the first
  open of the session and kept across reconnects; device functions pass it to `safety.check`, callers never do.
"""
import contextvars
import queue
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from typing import ClassVar

from mtpy.api import estop, events
from mtpy.api.errors import DeviceError, NotReady, Timeout

# U17: how a setting may change while the program runs. A device lists its settings in `settings_kinds` as
# {name: (kind, guarded_while_recording)}.
IMMEDIATE = "immediate"          # applied at once (exposure, gain, motion)
NEEDS_PAUSE = "needs_pause"      # stop acquisition, apply, read back, restart (ROI, frame rate)

_passive = contextvars.ContextVar("mtpy_passive_reads", default=False)


@contextmanager
def passive_reads():
    """Calls made inside this block (the acquisition's motor poller, review l2s-wp6-r1) do not CLEAR the U8 state
    when they succeed: a device marked error (e.g. after a failed move) or slow stays so until a real command
    succeeds. A failing passive call still marks the error, as any other call."""
    token = _passive.set(True)
    try:
        yield
    finally:
        _passive.reset(token)


class Device:
    """What every device provides, simulator or real driver. The service calls these on its own thread, except
    stop() (any thread, must be thread-safe). Failures are ordinary exceptions; the service turns them into
    DeviceError with the device's plain-language hint."""
    name = "device"
    hint = "check the device's power and cable"
    quantities = ()              # rig-safety-profile quantities this device acts on (shown in info())
    settings_kinds: ClassVar[dict] = {}
    tol = 0.0                    # read-back tolerance, decided by the device (api.md "Requirements for WP2")
    move_timeout_s = 60.0        # longest wait for a move to arrive before it is a DeviceError

    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def identity(self):
        """model, serial, firmware, port, driver - as read from the device."""
        raise NotImplementedError

    def settings(self):
        """Current settings read back from the device."""
        return {}

    def limits(self):
        """The controller's own limits (limit switches, soft limits, attribute ranges)."""
        return {}

    def calibration(self):
        return None

    def probe(self):
        """One read that proves the device replies (position or a setting); used by self_check (U8)."""
        return self.settings()

    def session_origin(self):
        """The position kept as the session-start origin for a relative window, or None."""

    def stop(self):
        """Halt any motion in place. Called directly by the emergency stop from any thread."""


class DeviceService:
    """Owns one device: a thread with a request queue, connection state, and the U8 status / info / self-check."""

    def __init__(self, device, reply_timeout_s=5.0, slow_s=0.5):
        self.device, self.name = device, device.name
        self.reply_timeout_s, self.slow_s = reply_timeout_s, slow_s
        self.connected, self.connected_since, self.origin = False, None, None
        self.last_reply_t = self.last_reply_ms = self.last_error = None
        self.errors = []                 # recent errors, newest last (U8 details)
        self._failed = self._slow = False
        self.recording = False           # set by acquisition (later WP); guards the 'guarded while recording' kinds
        self.reapply = None              # callable run after a reconnect (camera: the last preset, U15)
        self.calibration = None          # calibration in use set by the API (magnet: the force table, 0010)
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._run, name=f"device-{self.name}", daemon=True)
        self._thread.start()
        self._remove_stopper = estop.add_stopper(device.stop)

    def _run(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            ctx, fn, args, fut, guard, what, late = item
            if fut.set_running_or_notify_cancel():
                try:
                    result = ctx.run(fn, *args) if guard is None else self._send(ctx, fn, args, guard, what, late)
                except BaseException as e:  # noqa: BLE001 - handed to the waiting caller
                    fut.set_exception(e)
                    continue
                with late["lock"]:
                    if late["abandoned"] and guard is not None:
                        self._late_send(ctx, what or getattr(fn, "__name__", repr(fn)))
                        fut.set_exception(NotReady(f"{self.name}: applied after the reply timeout; stopped again"))
                    else:
                        fut.set_result(result)

    def _late_send(self, ctx, what):
        """WP6 carry: an acting send that completed AFTER its caller's reply timeout (the caller already got
        DeviceError and will not act on it). The device is stopped again on this thread and a `device_fault` event
        with `applied_after_timeout` records it, so a late move never runs on unnoticed."""
        self._stop_again(ctx)
        ctx.run(events.log, "device_fault", device=self.name, command=what, applied_after_timeout=True,
                hint=f"the command completed after the caller's reply timeout ({self.reply_timeout_s:g} s); "
                     f"{self.name}.stop() was called again - {self.device.hint}")

    def _send(self, ctx, fn, args, guard, what=None, late=None):
        """A device send of an acting call (review l2s-wp2-r1): checked against the e-stop generation and the cancel
        flag right before (void -> nothing sent) and right after (void -> this thread stops the device again).

        Re-review l2s-wp2-r2: the after-check runs whether the send returned or raised (a send may apply the move and
        then raise). A voided send always ends in NotReady (the caller logs `cancelled`, never `act`); when it had
        raised, that exception is kept as the NotReady's cause and recorded as a `device_fault` event (with `voided`;
        status() is not marked failed, the request was void anyway); `estop_error` only when the re-stop itself
        fails. A send that raised and is not void re-raises unchanged, so call() makes it the usual DeviceError."""
        why = estop.invalid(guard)
        if why:
            raise NotReady(f"{self.name}: {why}; not sent")
        if late is not None and late["abandoned"]:
            raise NotReady(f"{self.name}: the caller stopped waiting (reply timeout); not sent")
        try:
            result = ctx.run(fn, *args)
        except Exception as e:  # checked for voiding first, else re-raised unchanged
            why = estop.invalid(guard)
            if not why:
                raise
            self._stop_again(ctx)
            ctx.run(events.log, "device_fault", device=self.name, command=what or getattr(fn, "__name__", repr(fn)),
                    hint=f"{type(e).__name__}: {e} - {self.device.hint}", voided=why)
            raise NotReady(f"{self.name}: {why} during the send (the send also raised {type(e).__name__}: {e}); "
                           "device stopped again") from e
        why = estop.invalid(guard)
        if why:
            self._stop_again(ctx)
            raise NotReady(f"{self.name}: {why} during the send; device stopped again")
        return result

    def _stop_again(self, ctx):
        """Stop the device on this (service) thread after a voided send; a failure is an `estop_error` event."""
        try:
            self.device.stop()
        except Exception as e:  # noqa: BLE001 - recorded; the caller's NotReady still ends the call
            ctx.run(events.log, "estop_error", stopper=f"{self.name}.stop (after send)",
                    error=f"{type(e).__name__}: {e}")

    def call(self, fn, *args, what=None, timeout_s=None):
        """Run fn(*args) on the service thread in a copy of the caller's context and return its result.

        A failure or no reply within timeout_s becomes DeviceError(device, what, hint) with a `device_fault` event
        and is shown in status(). Never call this from the service thread itself (it would wait for itself).
        Inside an acting call's send (`estop.guarded_send`) the request is a guarded send (see `_send`); a void
        send raises NotReady, passed through unchanged (not a device fault).
        """
        what = what or getattr(fn, "__name__", repr(fn))
        fut, t0 = Future(), time.monotonic()
        late = {"lock": threading.Lock(), "abandoned": False}
        self._q.put((contextvars.copy_context(), fn, args, fut, estop.send_guard(), what, late))
        wait = self.reply_timeout_s if timeout_s is None else timeout_s
        try:
            fut.result(wait)
        except FutureTimeout:
            # WP6 carry: atomically either take a result that just arrived or mark the request abandoned, so a send
            # that completes later is stopped again by the service thread (`_late_send`), never left running
            with late["lock"]:
                if not fut.done():
                    late["abandoned"] = True
                    fut.cancel()
            if late["abandoned"]:
                self._fail(what, f"no reply for {wait:g} s - {self.device.hint}")
        except Exception:  # noqa: BLE001, S110 - read again just below, where it is handled
            pass
        try:
            result = fut.result(0)
        except NotReady:
            raise
        except Exception as e:  # noqa: BLE001 - any device failure becomes a DeviceError with a hint
            self._fail(what, f"{type(e).__name__}: {e} - {self.device.hint}", e)
        if not _passive.get():                # a poller read never clears an error / slow state (l2s-wp6-r1)
            dt = time.monotonic() - t0
            self.last_reply_t, self.last_reply_ms = time.time(), dt * 1000.0
            self._failed, self._slow = False, dt > self.slow_s
        return result

    def _fail(self, what, hint, cause=None):
        self._failed = True
        self.last_error = {"t": time.time(), "command": what, "hint": hint}
        self.errors = (self.errors + [self.last_error])[-20:]
        events.log("device_fault", device=self.name, command=what, hint=hint)
        raise DeviceError(self.name, what, hint) from cause

    def open(self):
        # a real driver may need longer than the reply timeout to open (IMAQdx reloads the camera file)
        self.call(self.device.open, what="open", timeout_s=getattr(self.device, "open_timeout_s", None))
        self.connected, self.connected_since = True, time.time()
        if self.origin is None:
            self.origin = self.call(self.device.session_origin, what="read session-start position")
        events.log("device", device=self.name, action="open", origin=self.origin)

    def close(self):
        if self.connected:
            self.connected = False
            # the iXon waits for its sensor to warm up before ShutDown (ixon.py close_timeout_s)
            self.call(self.device.close, what="close", timeout_s=getattr(self.device, "close_timeout_s", None))
            events.log("device", device=self.name, action="close")

    def reconnect(self):
        """Close (a failure here is recorded, not raised) and open again; the session-start origin is kept."""
        try:
            self.close()
        except DeviceError:
            pass
        self.open()

    def shutdown(self):
        """Close the device and end the service thread (end of session)."""
        try:
            self.close()
        finally:
            self._remove_stopper()
            self._q.put(None)
            self._thread.join(timeout=self.reply_timeout_s)

    def require(self):
        if not self.connected:
            raise NotReady(f"{self.name} is not connected; use api.devices.reconnect({self.name!r})")
        return self.device

    def status(self):
        """U8 row: state connected / disconnected / error / slow, last reply (time and ms), last error with hint."""
        state = ("disconnected" if not self.connected else "error" if self._failed
                 else "slow" if self._slow else "connected")
        return {"state": state, "last_reply_t": self.last_reply_t, "last_reply_ms": self.last_reply_ms,
                "last_error": self.last_error}

    def info(self):
        """U8 details (read-only): identity, settings read back, limits, calibration in use, origin, errors."""
        d = self.require()
        return {"identity": self.call(d.identity, what="identity"),
                "settings": self.call(d.settings, what="settings"),
                "limits": self.call(d.limits, what="limits"),
                "calibration": self.calibration or self.call(d.calibration, what="calibration"),
                "settings_kinds": dict(d.settings_kinds), "origin": self.origin,
                "connected_since": self.connected_since, "recent_errors": list(self.errors)}

    def self_check(self):
        """U8 start-up check: open, reply, read; stops at the first failed step with its reason."""
        report = []
        steps = [("open", lambda: None if self.connected else self.open()),
                 ("reply", lambda: self.call(self.device.identity, what="identity")),
                 ("read", lambda: self.call(self.device.probe, what="read"))]
        for step, fn in steps:
            try:
                report.append({"step": step, "ok": True, "detail": fn()})
            except DeviceError as e:
                report.append({"step": step, "ok": False, "detail": e.hint})
                break
        events.log("self_check", device=self.name, ok=all(r["ok"] for r in report), steps=len(report))
        return report


class Motion:
    """Handle of a running move (api.md section 1): `wait(timeout_s)`, `done`, `cancel()`.

    body(motion) runs on its own thread in a copy of the caller's context and returns the read-back position. A
    move stopped by cancel() or the emergency stop raises NotReady from wait().
    """

    def __init__(self, service, body, what):
        self._svc, self.what = service, what
        self._fut, self._cancel = Future(), threading.Event()
        ctx = contextvars.copy_context()
        threading.Thread(target=ctx.run, args=(self._main, body), name=f"motion-{service.name}", daemon=True).start()

    def _main(self, body):
        try:
            self._fut.set_result(body(self))
        except BaseException as e:  # noqa: BLE001 - handed to wait()
            self._fut.set_exception(e)

    @property
    def done(self):
        return self._fut.done()

    def wait(self, timeout_s):
        """Wait for the move and return the read-back position; Timeout if it has not finished within timeout_s."""
        try:
            return self._fut.result(timeout_s)
        except FutureTimeout:
            raise Timeout(f"{self.what} not finished within {timeout_s:g} s (still running; cancel() stops it)") \
                from None

    @property
    def cancel_flag(self):
        """The threading.Event set by cancel(); acting() checks it around the device send."""
        return self._cancel

    def cancel(self):
        """Stop the move in place; wait() then raises NotReady. Sets the cancel flag first, then calls the device's
        stop() directly on this thread, not through the service queue (which may be busy with a long command)."""
        self._cancel.set()
        self._svc.device.stop()

    def wait_arrival(self, moving, gen=None):
        """Poll moving() through the service until the move ends; NotReady if cancelled or e-stopped.

        gen (WP6 carry): the emergency-stop generation recorded when the move was requested. A stop engaged AND
        released while the move runs halts the axis but leaves the flag clear; without this check the halt would
        look like an arrival (and end in a read-back mismatch). Inside a protocol run the run's generation counts
        too (`estop.run_scope_void`)."""
        t_end = time.monotonic() + self._svc.device.move_timeout_s
        while True:
            still = self._svc.call(moving, what="moving?")
            # checked AFTER the poll: the stop flags are set before the stop is sent, so a halt caused by them is
            # never mistaken for an arrival
            if estop.active() or (gen is not None and estop.generation() != gen) or estop.run_scope_void():
                raise NotReady(f"{self.what} stopped by the emergency stop")
            if self._cancel.is_set():
                raise NotReady(f"{self.what} cancelled")
            if not still:
                return
            if time.monotonic() > t_end:
                raise TimeoutError(f"did not arrive within {self._svc.device.move_timeout_s:g} s")
            time.sleep(0.01)
