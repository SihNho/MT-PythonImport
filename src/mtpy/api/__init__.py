"""The public function layer (docs/design/api.md): the GUI, scripts, plug-ins and the AI gateway call only this.

Usage: `from mtpy import api`. WP1: errors, the event log with the caller context, the emergency-stop flag and the
rig safety profile. WP2: device connection and status, camera settings, magnet, rotor, stage, focus, lasers and the
sync divider, each against the simulators selected by the rig preset `{"backend": "sim"}`. WP3: acquisition and
recording (`acq`), bead selection (`beads`) and the latest tracking result (`tracking`). WP4: the HDF5 v1 run file
(`acq.start(folder=...)`), opening it and exporting it to `.tra` / `.cal` (`data`). WP5: protocol scripts - load,
check, run, pause, resume, stop, mid-run edits (`protocol`). 0.6.0 (decision 0016): `end protocol` statement,
`.tra` frame column from the first recorded frame; shipped rig safety profile v3 (magnet speed max 15 mm/s,
verified:false until the rig check, so magnet moves are refused; review l2s-wp5-r4). 0.7.0 (WP6, walking skeleton):
magnet / rotor poller during acquisition (`motor_reading` events, per-frame motor columns), storage errors stored in
the run file, the camera stop checked separately, the ROI origin kept at bead selection and checked at start, a
camera reconnect as a segment end, the e-stop generation through wait_arrival and protocol run(), late sends stopped
again. 0.8.0 (decision 0017): no separate maximum force - a force is converted to a magnet position through the
force table in use and checked against the magnet position limit (`magnet.force_range()`, `magnet.force_position()`);
shipped rig safety profile v5 without `magnet_force_pN`.
"""
from . import errors, estop, events, safety  # noqa: I001 - must load before the device groups (they import them)
from . import camera, devices, focus, light, magnet, rotor, stage, sync
from . import acq, beads, data, tracking
from . import protocol
from .errors import DeviceError, MtpyError, NotReady, SafetyRefused, ScriptError, Timeout

VERSION = "0.8.0"

__all__ = ["VERSION", "DeviceError", "MtpyError", "NotReady", "SafetyRefused", "ScriptError", "Timeout",
           "acq", "beads", "camera", "data", "devices", "errors", "estop", "events", "focus", "light", "magnet",
           "protocol", "rotor", "safety", "stage", "sync", "tracking"]
