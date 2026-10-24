"""The public function layer (docs/design/api.md): the GUI, scripts, plug-ins and the AI gateway call only this.

Usage: `from mtpy import api`. WP1 provides the skeleton: errors, the event log with the caller context, the
emergency-stop flag and the rig safety profile. Device groups follow in later work packages.
"""
from . import errors, estop, events, safety
from .errors import DeviceError, MtpyError, NotReady, SafetyRefused, Timeout

VERSION = "0.1.0"

__all__ = ["VERSION", "DeviceError", "MtpyError", "NotReady", "SafetyRefused", "Timeout",
           "errors", "estop", "events", "safety"]
