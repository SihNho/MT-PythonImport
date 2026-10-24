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
from typing import ClassVar

from mtpy.api import estop, events
from mtpy.api.errors import DeviceError, NotReady, Timeout

# U17: how a setting may change while the program runs. A device lists its settings in `settings_kinds` as
# {name: (kind, guarded_while_recording)}.
IMMEDIATE = "immediate"          # applied at once (exposure, gain, motion)
NEEDS_PAUSE = "needs_pause"      # stop acquisition, apply, read back, restart (ROI, frame rate)


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
            ctx, fn, args, fut, guard = item
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(ctx.run(fn, *args) if guard is None else self._send(ctx, fn, args, guard))
                except BaseException as e:  # noqa: BLE001 - handed to the waiting caller
                    fut.set_exception(e)

    def _send(self, ctx, fn, args, guard):
        """A device send of an acting call (review l2s-wp2-r1): checked against the e-stop generation and the cancel
        flag right before (void -> nothing sent) and right after (void -> this thread stops the device again)."""
        why = estop.invalid(guard)
        if why:
            raise NotReady(f"{self.name}: {why}; not sent")
        result = ctx.run(fn, *args)
        why = estop.invalid(guard)
        if why:
            try:
                self.device.stop()
            except Exception as e:  # noqa: BLE001 - recorded; the NotReady below still ends the call
                ctx.run(events.log, "estop_error", stopper=f"{self.name}.stop (after send)",
                        error=f"{type(e).__name__}: {e}")
            raise NotReady(f"{self.name}: {why} during the send; device stopped again")
        return result

    def call(self, fn, *args, what=None, timeout_s=None):
        """Run fn(*args) on the service thread in a copy of the caller's context and return its result.

        A failure or no reply within timeout_s becomes DeviceError(device, what, hint) with a `device_fault` event
        and is shown in status(). Never call this from the service thread itself (it would wait for itself).
        Inside an acting call's send (`estop.guarded_send`) the request is a guarded send (see `_send`); a void
        send raises NotReady, passed through unchanged (not a device fault).
        """
        what = what or getattr(fn, "__name__", repr(fn))
        fut, t0 = Future(), time.monotonic()
        self._q.put((contextvars.copy_context(), fn, args, fut, estop.send_guard()))
        wait = self.reply_timeout_s if timeout_s is None else timeout_s
        try:
            result = fut.result(wait)
        except FutureTimeout:
            fut.cancel()
            self._fail(what, f"no reply for {wait:g} s - {self.device.hint}")
        except NotReady:
            raise
        except Exception as e:  # noqa: BLE001 - any device failure becomes a DeviceError with a hint
            self._fail(what, f"{type(e).__name__}: {e} - {self.device.hint}", e)
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
        self.call(self.device.open, what="open")
        self.connected, self.connected_since = True, time.time()
        if self.origin is None:
            self.origin = self.call(self.device.session_origin, what="read session-start position")
        events.log("device", device=self.name, action="open", origin=self.origin)

    def close(self):
        if self.connected:
            self.connected = False
            self.call(self.device.close, what="close")
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

    def wait_arrival(self, moving):
        """Poll moving() through the service until the move ends; NotReady if cancelled or e-stopped."""
        t_end = time.monotonic() + self._svc.device.move_timeout_s
        while True:
            still = self._svc.call(moving, what="moving?")
            # checked AFTER the poll: the stop flags are set before the stop is sent, so a halt caused by them is
            # never mistaken for an arrival
            if estop.active():
                raise NotReady(f"{self.what} stopped by the emergency stop")
            if self._cancel.is_set():
                raise NotReady(f"{self.what} cancelled")
            if not still:
                return
            if time.monotonic() > t_end:
                raise TimeoutError(f"did not arrive within {self._svc.device.move_timeout_s:g} s")
            time.sleep(0.01)
