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


class NotReady(MtpyError):
    """The call cannot run now (emergency stop active, no valid calibration, ...)."""


class Timeout(MtpyError):
    """A wait ran past its timeout_s."""
