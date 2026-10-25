"""Typed errors of the public API (docs/design/api.md section 1). Every API failure is one of these."""


class MtpyError(Exception):
    """Base class of every error the public API raises."""


class SafetyRefused(MtpyError):
    """The request is outside the active rig safety profile, or the caller may not do this. Never a silent clamp: the
    message names the allowed range."""


class DeviceError(MtpyError):
    """A device did not reply, replied badly, or read back something other than what was asked."""

    def __init__(self, device, command, hint):
        self.device, self.command, self.hint = device, command, hint
        super().__init__(f"{device}: {command} - {hint}")


class MagnetStall(DeviceError):
    """Decision 0019: the PI controller detected a magnet stall (error -1024: position error too large, servo
    switched off). `record` is the `magnet_stall` event's content (time, position at the stall, controller error,
    whether the return to 0 mm was verified, whether the magnet is now locked). A DeviceError, so code that handles
    device failures still stops; the GUI (phase 8) shows it as a modal error window."""

    def __init__(self, record, hint=None):
        self.record = dict(record)
        if hint is None:
            hint = (f"stall at {record.get('position_mm')!r} mm (controller error {record.get('controller_error')}, "
                    "servo switched off); "
                    + ("returned to 0 mm, verified" if record.get("return_verified") else
                       "the return to 0 mm was NOT verified: the magnet is locked until api.magnet.clear_stall()"))
        super().__init__("magnet", "stall detected", hint)


class NotReady(MtpyError):
    """The call cannot run now (emergency stop active, no valid calibration, ...)."""


class Timeout(MtpyError):
    """A wait ran past its timeout_s."""


class ScriptError(MtpyError):
    """A protocol, illumination sequence or analysis recipe has errors (WP5): it cannot run. `diagnostics` lists
    each error as `<file>:<line>:<column>: <message>` (docs/format/grammar.md section 8); `warnings` the warnings."""

    def __init__(self, diagnostics, warnings=()):
        self.diagnostics, self.warnings = list(diagnostics), list(warnings)
        n = len(self.diagnostics)
        super().__init__(f"{n} error{'s' if n != 1 else ''}:\n" + "\n".join(str(d) for d in self.diagnostics))
