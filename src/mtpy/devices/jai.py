"""The real JAI SP-5000M-USB as a `Device` (phase 6), on the IMAQdx ctypes layer (`imaqdx.py`; decision 0021).

Same interface and validation as its simulator twin `sim/camera.py` (the `check_setting` / `tol` / `limits` contract
is shared, so the API above cannot tell them apart). Differences of the real camera:
- opens only under the shared rig lock: `RIGLOCK_TOKEN` in the environment and `riglock.permitted` (RULES.md 2), as
  V6 `tools/rig_session.py --no-motor-session` provides; the wrapper polls `permitted` every 30 s and kills this
  process on refusal, so nothing here polls (no device call is on the frame path, rule 6).
- `Frame.t_camera_s` = PC receive time (perf_counter since acquisition start): the JAI has no hardware timestamp
  (decision 0005); buffer numbers are the camera's own count, gaps = frames the PC missed.
- frames are fetched by buffer number (`LastBufferNumber + 1`, as `get buff image-lost frames.vi` does, F4.03) on a
  producer thread into a deque, like the simulator; the driver ring holds 100 buffers (131 MB) to absorb jitter.
- gain is read back (`AnalogControl::Gain`, auto gain on by default) but not written: its unit is not verified
  (shortcut: gain_dB read-only on the real camera, upgrade when the owner decides on gain).
"""
import collections
import contextlib
import os
import sys
import threading
import time

from ..api.errors import SafetyRefused
from .base import NEEDS_PAUSE, Device
from .imaqdx import ACQ, BOOL, CMD, ENUM, F64, I64, IMG, STR, U32, VIS_INTERMEDIATE, VIS_SIMPLE, A, ImaqdxCamera
from .sim.camera import Frame, SimCamera

RIG_DIR = r"G:\Codes\rig"
DEV, GAIN = A + "DeviceControl::", A + "AnalogControl::Gain"
RING_DEPTH = 100
# attribute catalogue (owner 2026-11-04): what a generic write may never touch - these change the camera's stored
# defaults, reset it, or break the 8-bit frame path the program's ring buffer assumes
ATTR_REFUSED = {"DeviceReset", "FactoryStoreAll", "UserSetSave", "FactoryBootAreaSet"}
ATTR_REFUSED_CATEGORIES = {"JAICustomFactorySetting"}
ATTR_PIXEL_FORMATS = {"Mono8"}
# writes in these categories change how frames are produced: refused while acquiring (the API pauses for them)
ATTR_NEEDS_PAUSE = {"ImageFormatControl", "AcquisitionControl", "TransportLayerControl", "UserSetControl", "DeviceControl"}
_TYPES = {U32: "int", I64: "int", F64: "float", STR: "string", ENUM: "enum", BOOL: "bool", CMD: "command"}


def _permitted():
    """PermissionError unless this process runs under the rig lock in a state that allows the camera."""
    token = os.environ.get("RIGLOCK_TOKEN")
    if not token:
        raise PermissionError("no RIGLOCK_TOKEN: the real camera opens only under the rig lock "
                              "(api.devices.connect takes it, decision 0026)")
    if RIG_DIR not in sys.path:
        sys.path.insert(0, RIG_DIR)
    import riglock
    if not riglock.permitted(token, ("assembled", "disassembled")):
        raise PermissionError("rig lock refuses the camera: experiment declared, lock lost, or not the holder")


class JaiCamera(Device):
    name, model, hint = SimCamera.name, SimCamera.model, SimCamera.hint
    timestamp_source = "PC receive time (s since acquisition start; the JAI has no hardware timestamp, 0005)"
    settings_kinds = SimCamera.settings_kinds
    open_timeout_s = 30.0                   # IMAQdxOpenCamera reloads the .icd and took > 5 s on the rig (2026-10-29)
    tol = SimCamera.tol
    _rate_max = None                        # the driver's frame-rate cap at the ROI in force, read by settings()

    def limits(self):
        lim = dict(SimCamera.limits(self))
        if self._rate_max:
            lim["rate_Hz"] = (1.0, self._rate_max)
        return lim

    def check_setting(self, name, value, rate_Hz, exposure_ms):
        """As the simulator, except the rate cap: the camera's own maximum at the ROI in force (owner 2026-11-01:
        the maximum rate of a half-size ROI; the simulator keeps one cap for every ROI)."""
        if name == "rate_Hz" and self._rate_max:
            if not (isinstance(value, (int, float)) and not isinstance(value, bool) and 1.0 <= value <= self._rate_max):
                raise SafetyRefused(f"camera rate {value!r} Hz is outside [1, {self._rate_max:.4f}] Hz at this ROI")
            if 1000.0 / value < exposure_ms:
                raise SafetyRefused(f"camera rate {value:g} Hz: frame period {1000.0 / value:.4f} ms is shorter than "
                                    f"the exposure {exposure_ms:g} ms; shorten the exposure first")
            return
        SimCamera.check_setting(self, name, value, rate_Hz, exposure_ms)

    def __init__(self, ring_size=64):
        self.cam = None
        self._cond = threading.Condition()
        self._ring = collections.deque(maxlen=ring_size)
        self._thread, self._run = None, threading.Event()
        self.error = None                       # why the frame thread ended on its own, if it did
        self._cat = None

    def _io(self):
        if self.cam is None:
            raise ConnectionError("camera session not open")
        return self.cam

    def open(self):
        self._cat = None
        _permitted()
        cam = ImaqdxCamera()
        cam.open()                              # every open reloads the .icd: presets are re-applied by the API (U15)
        self.cam = cam

    def close(self):
        self.stop_acquisition()
        if self.cam is not None:
            self.cam.close()
            self.cam = None

    def identity(self):
        c = self._io()
        return {"model": c.model, "serial": c.serial, "firmware": c.get(DEV + "DeviceFirmwareVersion", STR),
                "port": c.name, "driver": "NI-IMAQdx niimaqdx.dll (mtpy.devices.imaqdx)"}

    _cat = None

    def catalogue(self):
        """Every camera attribute the driver lists (NI MAX's tree), read once per session: name = the short GenICam
        name, category = the tree node it sits in. Attributes of IMAQdx itself (AcquisitionAttributes::) are left out."""
        if self._cat is None:
            c = self._io()
            simple = {n for n, *_ in c.attributes("CameraAttributes", VIS_SIMPLE)}
            inter = {n for n, *_ in c.attributes("CameraAttributes", VIS_INTERMEDIATE)}
            rows = []
            for full, t, readable, writable in c.attributes("CameraAttributes"):
                parts = full.split("::")
                if len(parts) < 3 or t not in _TYPES:
                    continue
                e = {"name": parts[-1], "full": full, "category": parts[1], "type": _TYPES[t], "access":
                     "rw" if readable and writable else ("ro" if readable else "wo"),
                     "visibility": "beginner" if full in simple else ("expert" if full in inter else "guru"),
                     "description": ""}
                with contextlib.suppress(Exception):                 # a tooltip is a nicety
                    e["description"] = c.text("IMAQdxGetAttributeTooltip", full)
                if t in (U32, I64, F64):
                    with contextlib.suppress(Exception):             # some read-only numbers have no range
                        e["min"], e["max"] = c.limit("IMAQdxGetAttributeMinimum", full, t), c.limit("IMAQdxGetAttributeMaximum", full, t)
                        e["step"] = c.limit("IMAQdxGetAttributeIncrement", full, t)
                if t == ENUM:
                    try:
                        e["values"] = c.enum_values(full)
                    except Exception:  # noqa: BLE001
                        e["values"] = []
                rows.append(e)
            self._cat = rows
        return self._cat

    def _entry(self, name):
        for e in self.catalogue():
            if e["name"] == name or e["full"] == name:
                return e
        raise ValueError(f"camera has no attribute {name!r}")

    def get_attribute(self, name):
        e = self._entry(name)
        t = {v: k for k, v in _TYPES.items()}[e["type"]]
        if e["type"] == "enum":
            return self._io().get(e["full"], STR)
        if e["type"] == "command":
            return None
        return self._io().get(e["full"], t)

    def set_attribute(self, name, value):
        """A generic write with the refusals above; needs-a-pause categories while acquiring are refused here (the
        API pauses the acquisition around them)."""
        e = self._entry(name)
        if e["name"] in ATTR_REFUSED or e["category"] in ATTR_REFUSED_CATEGORIES:
            raise ValueError(f"camera attribute {e['name']} is never written by the program (stored defaults, reset, factory)")
        if e["access"] == "ro":
            raise ValueError(f"camera attribute {e['name']} is read-only")
        if e["name"] == "PixelFormat" and value not in ATTR_PIXEL_FORMATS:
            raise ValueError(f"PixelFormat {value!r}: the frame path takes {sorted(ATTR_PIXEL_FORMATS)} only")
        if e["category"] in ATTR_NEEDS_PAUSE and self.acquiring():
            raise RuntimeError(f"{e['name']} cannot be written while acquiring (stop acquisition first)")
        t = {v: k for k, v in _TYPES.items()}[e["type"]]
        self._io().set(e["full"], t, value)
        return self.get_attribute(name)

    def settings(self):
        c = self._io()
        self._rate_max = c.get_max(ACQ + "AcquisitionFrameRate", F64)
        return {"exposure_ms": c.get(ACQ + "ExposureTime", F64) / 1000.0, "gain_dB": c.get(GAIN, F64),
                "rate_Hz": c.get(ACQ + "AcquisitionFrameRate", F64),
                "roi": tuple(int(c.get(IMG + k, I64)) for k in ("OffsetX", "OffsetY", "Width", "Height")),
                "exposure_auto": c.get(ACQ + "ExposureAuto", STR), "acquiring": self.acquiring(),
                "frame_thread_error": self.error}

    def set(self, name, value):
        c = self._io()
        if self.settings_kinds[name][0] == NEEDS_PAUSE and self.acquiring():
            raise RuntimeError(f"{name} cannot be written while acquiring (stop acquisition first)")
        if name == "exposure_ms":
            c.set(ACQ + "ExposureAuto", STR, "Off")
            c.set(ACQ + "ExposureTime", F64, float(value) * 1000.0)
        elif name == "rate_Hz":
            c.set(ACQ + "AcquisitionFrameRate", F64, float(value))
        elif name == "roi":                     # offsets to 0 first, so a smaller window never overflows the sensor
            x, y, w, h = (int(v) for v in value)
            for k, v in (("OffsetX", 0), ("OffsetY", 0), ("Width", w), ("Height", h), ("OffsetX", x), ("OffsetY", y)):
                c.set(IMG + k, I64, v)
        else:
            raise RuntimeError(f"{name} is read-only on the real camera (the JAI gain unit is not verified)")

    def get(self, name):
        return self.settings()[name]

    # --- acquisition (the frame path) ---------------------------------------------------------------------------
    def acquiring(self):
        return self._thread is not None and self._thread.is_alive()

    def start_acquisition(self):
        c = self._io()
        if self.acquiring():
            return
        self._ring.clear()
        self.error = None
        c.start(n_buffers=RING_DEPTH)
        self._run.set()
        self._thread = threading.Thread(target=self._produce, args=(c,), name="jai-frames", daemon=True)
        self._thread.start()

    def _produce(self, c):
        b, t0 = 0, time.perf_counter()
        try:
            while self._run.is_set():
                act, _, img = c.frame(b)        # waits for that buffer; `act` is the one delivered (pitfall 6)
                t = time.perf_counter() - t0
                b = act + 1
                with self._cond:
                    self._ring.append(Frame(act, t, img.copy()))
                    self._cond.notify_all()
        except Exception as e:  # noqa: BLE001 - a stop unblocks GetImageData with an error; anything else is kept
            if self._run.is_set():
                self.error = f"{type(e).__name__}: {e}"

    def stop_acquisition(self):
        self._run.clear()
        if self._thread is not None:
            if self.cam is not None:
                self.cam.stop_streaming()       # unblocks the waiting GetImageData
            self._thread.join(timeout=6.0)
            self._thread = None
        if self.cam is not None:
            self.cam.stop()

    def next_frame(self, timeout_s=1.0):
        """The oldest frame not yet taken, or None after timeout_s."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._ring, timeout_s):
                return None
            return self._ring.popleft()
