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
import os
import sys
import threading
import time

from .base import NEEDS_PAUSE, Device
from .imaqdx import ACQ, F64, I64, IMG, STR, A, ImaqdxCamera
from .sim.camera import Frame, SimCamera

RIG_DIR = r"G:\Codes\rig"
DEV, GAIN = A + "DeviceControl::", A + "AnalogControl::Gain"
RING_DEPTH = 100


def _permitted():
    """PermissionError unless this process runs under the rig lock in a state that allows the camera."""
    token = os.environ.get("RIGLOCK_TOKEN")
    if not token:
        raise PermissionError("no RIGLOCK_TOKEN: the real camera opens only under the rig lock "
                              "(V6 tools/rig_session.py --no-motor-session -- <this program>)")
    if RIG_DIR not in sys.path:
        sys.path.insert(0, RIG_DIR)
    import riglock
    if not riglock.permitted(token, ("assembled", "disassembled")):
        raise PermissionError("rig lock refuses the camera: experiment declared, lock lost, or not the holder")


class JaiCamera(Device):
    name, model, hint = SimCamera.name, SimCamera.model, SimCamera.hint
    timestamp_source = "PC receive time (s since acquisition start; the JAI has no hardware timestamp, 0005)"
    settings_kinds = SimCamera.settings_kinds
    check_setting, tol, limits = SimCamera.check_setting, SimCamera.tol, SimCamera.limits

    def __init__(self, ring_size=64):
        self.cam = None
        self._cond = threading.Condition()
        self._ring = collections.deque(maxlen=ring_size)
        self._thread, self._run = None, threading.Event()
        self.error = None                       # why the frame thread ended on its own, if it did

    def _io(self):
        if self.cam is None:
            raise ConnectionError("camera session not open")
        return self.cam

    def open(self):
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

    def settings(self):
        c = self._io()
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
