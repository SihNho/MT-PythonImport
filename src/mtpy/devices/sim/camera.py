"""Simulated JAI SP-5000M-USB through IMAQdx (docs/manuals/camera-jai-imaqdx.md).

- Replays the recorded fixture frames (img00004.tif .. img11825.tif, 1280 x 1024, 8 bit) at the set rate, or, when
  no fixture folder is given or found, a synthetic ring pattern - tests never need the G: data.
- Frames carry the absolute buffer number (counts every frame the camera produced since acquisition start, also the
  ones the PC dropped; IMAQdx restarts it at 0 on every start) and `t_camera_s`, the sim camera's own clock since
  acquisition start (a stall shows as a jump).
  The real JAI has NO hardware timestamp (decision 0005); the real driver will carry the PC receive time instead.
- Like the JAI, every open resets ROI, exposure and frame rate to the camera-file defaults (so presets must be
  re-applied, U15); frame rate and ROI cannot be written while acquiring (the "needs a short pause" kind, U17).
- Frame period is quantised to 1 us (AcquisitionFrameRateRaw), exposure to 1 us, as on the camera.
- Fault injection: `drop_every = k` drops every k-th buffer on the PC side (a gap in buffer numbers); `stall(s)`
  stops frame production for s seconds; `fault = "no_reply"` makes every control call raise TimeoutError.
- `exposure_listeners`: called with each buffer number as the frame is exposed (the "Exposure Active" TTL line that
  drives the Arduino divider, decision 0005); hardware wiring, not a PC call.
"""
import collections
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np

from mtpy.api.errors import SafetyRefused

from ..base import IMMEDIATE, NEEDS_PAUSE, Device

SENSOR_W, SENSOR_H = 1280, 1024          # binned 2 x 2
DEFAULTS = {"exposure_ms": 1.909, "gain_dB": 0.0, "rate_Hz": 1e6 / 11111, "roi": (0, 0, SENSOR_W, SENSOR_H)}
RATE_MAX_HZ = 247.9544                   # at 1280 x 1024; shortcut: the same cap for every ROI, refine with the driver
GAIN_DB = (0.0, 24.0)                    # sim range only: the JAI gain range is not in docs/manuals yet


@dataclass(frozen=True)
class Frame:
    buffer_number: int
    t_camera_s: float
    image: np.ndarray


def _rings(h=SENSOR_H, w=SENSOR_W):
    """A synthetic field of diffraction-ring beads (uint8)."""
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.full((h, w), 90.0)
    for cx, cy in ((320, 256), (640, 512), (960, 300), (400, 800), (1000, 820)):
        r = np.hypot(xx - cx, yy - cy)
        img += 70.0 * np.cos(2 * np.pi * r / 14.0) * np.exp(-r / 45.0)
    return np.clip(img, 0, 255).astype(np.uint8)


class SimCamera(Device):
    name, model = "camera", "JAI SP-5000M-USB (IMAQdx cam1)"
    hint = "check the USB 3 cable and that no other program (LabVIEW, NI MAX) holds the camera"
    settings_kinds: ClassVar[dict] = {"exposure_ms": (IMMEDIATE, False), "gain_dB": (IMMEDIATE, False),
                      "rate_Hz": (NEEDS_PAUSE, True), "roi": (NEEDS_PAUSE, True)}

    def __init__(self, fixture=None, ring_size=50):
        files = sorted(Path(fixture).glob("img*.tif")) if fixture and Path(fixture).is_dir() else []
        self.files = files
        self.source = str(fixture) if files else "synthetic rings"
        self._synthetic = None if files else _rings()
        self._lock, self._cond = threading.Lock(), threading.Condition()
        self._ring = collections.deque(maxlen=ring_size)
        self._s = dict(DEFAULTS)
        self._thread, self._run = None, threading.Event()
        self.is_open, self.fault, self.drop_every, self._stall_s = False, None, 0, 0.0
        self.exposure_listeners = []
        self.last_buffer = -1

    # --- control (called on the service thread) ---------------------------------------------------------------------
    def _io(self):
        if self.fault == "no_reply":
            raise TimeoutError("no reply")
        if not self.is_open:
            raise ConnectionError("camera session not open")

    def open(self):
        if self.fault == "no_reply":
            raise TimeoutError("no reply")
        with self._lock:
            self._s = dict(DEFAULTS)                    # the JAI reloads its camera file on every open
        self.is_open = True

    def close(self):
        self.stop_acquisition()
        self.is_open = False

    def identity(self):
        self._io()
        return {"model": f"simulator of {self.model}", "serial": "SIM", "firmware": "sim", "port": "sim",
                "driver": "mtpy.devices.sim", "frames": self.source}

    def settings(self):
        self._io()
        with self._lock:
            return {**self._s, "acquiring": self.acquiring()}

    def limits(self):
        return {"exposure_ms": (0.001, "frame period"), "gain_dB": GAIN_DB, "rate_Hz": (1.0, RATE_MAX_HZ),
                "roi": "x, y >= 0; w 8..1280 step 8; h 8..1024 step 2; inside 1280 x 1024"}

    def check_setting(self, name, value, rate_Hz, exposure_ms):
        """Raise SafetyRefused (with the allowed range) unless `value` is valid for `name` given the rate and
        exposure that will be in force. Pure validation, no I/O."""
        def num(v):
            return isinstance(v, (int, float, np.number)) and not isinstance(v, bool) and np.isfinite(v)
        if name == "exposure_ms":
            if not (num(value) and 0.001 <= value <= 1000.0 / rate_Hz):
                raise SafetyRefused(f"camera exposure {value!r} ms is outside [0.001, {1000.0 / rate_Hz:.4f}] ms "
                                    f"(must not exceed the frame period at {rate_Hz:g} Hz)")
        elif name == "gain_dB":
            if not (num(value) and GAIN_DB[0] <= value <= GAIN_DB[1]):
                raise SafetyRefused(f"camera gain {value!r} dB is outside [{GAIN_DB[0]:g}, {GAIN_DB[1]:g}] dB")
        elif name == "rate_Hz":
            if not (num(value) and 1.0 <= value <= RATE_MAX_HZ):
                raise SafetyRefused(f"camera rate {value!r} Hz is outside [1, {RATE_MAX_HZ}] Hz")
            if 1000.0 / value < exposure_ms:
                raise SafetyRefused(f"camera rate {value:g} Hz: frame period {1000.0 / value:.4f} ms is shorter than "
                                    f"the exposure {exposure_ms:g} ms; shorten the exposure first")
        elif name == "roi":
            ok = (isinstance(value, (tuple, list)) and len(value) == 4
                  and all(isinstance(v, (int, np.integer)) and not isinstance(v, bool) for v in value))
            x, y, w, h = value if ok else (0, 0, 0, 0)
            if not (ok and x >= 0 and y >= 0 and 8 <= w <= SENSOR_W and w % 8 == 0 and 8 <= h <= SENSOR_H
                    and h % 2 == 0 and x + w <= SENSOR_W and y + h <= SENSOR_H):
                raise SafetyRefused(f"camera ROI {value!r} is not allowed: integers x, y >= 0; w 8..1280 step 8; "
                                    "h 8..1024 step 2; x + w <= 1280, y + h <= 1024")
        else:
            raise SafetyRefused(f"camera has no setting {name!r}; settings: {sorted(self.settings_kinds)}")

    def tol(self, name, value):
        """Read-back tolerance of each setting (1 us steps of exposure and frame period)."""
        if name == "rate_Hz":
            return value * value * 0.6e-6 if isinstance(value, (int, float)) and value < 1e6 else 0.0
        return {"exposure_ms": 0.0006, "gain_dB": 0.01}.get(name, 0.0)

    def set(self, name, value):
        self._io()
        if self.settings_kinds[name][0] == NEEDS_PAUSE and self.acquiring():
            raise RuntimeError(f"{name} cannot be written while acquiring (stop acquisition first)")
        if name == "rate_Hz":
            value = 1e6 / round(1e6 / value)
        elif name == "exposure_ms":
            value = round(value * 1000.0) / 1000.0
        elif name == "roi":
            value = tuple(int(v) for v in value)
        with self._lock:
            self._s[name] = value

    def get(self, name):
        self._io()
        with self._lock:
            return self._s[name]

    # --- acquisition (the frame path; frames never pass through the service queue) ------------------------------------
    def acquiring(self):
        return self._thread is not None and self._thread.is_alive()

    def start_acquisition(self):
        self._io()
        if self.acquiring():
            return
        self._ring.clear()
        self._run.set()
        self._thread = threading.Thread(target=self._produce, name="sim-camera-frames", daemon=True)
        self._thread.start()

    def stop_acquisition(self):
        self._run.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def stall(self, seconds):
        self._stall_s = seconds

    def _image(self, b):
        with self._lock:
            x, y, w, h = self._s["roi"]
        if self._synthetic is not None:
            img = self._synthetic
        else:
            from PIL import Image
            img = np.asarray(Image.open(self.files[b % len(self.files)]))
        return img[y:y + h, x:x + w].copy()

    def _produce(self):
        with self._lock:
            period = 1.0 / self._s["rate_Hz"]
        b, t_next = 0, time.monotonic()
        t_start = t_next
        while self._run.is_set():
            if self._stall_s:
                time.sleep(self._stall_s)
                self._stall_s, t_next = 0.0, time.monotonic()
            delay = t_next - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            for fn in list(self.exposure_listeners):
                fn(b)
            self.last_buffer = b
            if not (self.drop_every and b % self.drop_every == self.drop_every - 1):
                frame = Frame(b, t_next - t_start, self._image(b))
                with self._cond:
                    self._ring.append(frame)
                    self._cond.notify_all()
            b, t_next = b + 1, t_next + period

    def next_frame(self, timeout_s=1.0):
        """The oldest frame not yet taken (IMAQdx 'Next'), or None after timeout_s."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._ring, timeout_s):
                return None
            return self._ring.popleft()
