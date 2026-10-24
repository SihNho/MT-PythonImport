"""The public function layer (docs/design/api.md): the GUI, scripts, plug-ins and the AI gateway call only this.

Usage: `from mtpy import api`. WP1: errors, the event log with the caller context, the emergency-stop flag and the
rig safety profile. WP2: device connection and status, camera settings, magnet, rotor, stage, focus, lasers and the
sync divider, each against the simulators selected by the rig preset `{"backend": "sim"}`. WP3: acquisition and
recording (`acq`), bead selection (`beads`) and the latest tracking result (`tracking`). WP4: the HDF5 v1 run file
(`acq.start(folder=...)`), opening it and exporting it to `.tra` / `.cal` (`data`).
"""
from . import errors, estop, events, safety  # noqa: I001 - must load before the device groups (they import them)
from . import camera, devices, focus, light, magnet, rotor, stage, sync
from . import acq, beads, data, tracking
from .errors import DeviceError, MtpyError, NotReady, SafetyRefused, Timeout

VERSION = "0.4.0"

__all__ = ["VERSION", "DeviceError", "MtpyError", "NotReady", "SafetyRefused", "Timeout",
           "acq", "beads", "camera", "data", "devices", "errors", "estop", "events", "focus", "light", "magnet",
           "rotor", "safety", "stage", "sync", "tracking"]
