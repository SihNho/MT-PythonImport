"""The real JAI SP-5000M-USB through JAI's eBUS SDK (.NET API `PvDotNet.dll` via pythonnet) - decision 0028 (owner
2026-11-01 "eBUS로 간다"), replacing the IMAQdx path of `jai.py` (kept, selectable with the preset key
`"camera_sdk": "imaqdx"`).

Same interface and validation as the simulator twin `sim/camera.py` and `jai.JaiCamera`. What differs from IMAQdx:
- the camera must be bound to Pleora's USB3 Vision driver (the eBUS SDK installer did that on 2026-10-31; IMAQdx and
  LabVIEW then no longer see it - manuals/camera-jai-imaqdx.md "Driver / SDK");
- `Frame.t_camera_s` is the camera's own timestamp (`PvBuffer.Timestamp`, 1 GHz ticks = ns on this camera), taken
  relative to the first frame of the acquisition; `buffer_number` = the U3V `BlockID` (0-based per acquisition);
- pythonnet cannot read a `Byte*`, so a 10-line C# helper (`ebus_helper/MtpyEbus.cs`, built on first use with the
  .NET Framework's own `csc.exe`) returns the buffer address; the frame is copied once with `ctypes.string_at`
  (0.33 ms for 1280 x 1024 on the rig).
- gain: the camera's `Gain` is 1..16 in its own unit (GainRaw 100..1600), the same number IMAQdx reported as
  `gain_dB`; kept read-only, as before (shortcut: upgrade when the owner decides on gain).
"""
import collections
import ctypes
import os
import subprocess
import threading

import numpy as np

from .base import NEEDS_PAUSE, Device
from .jai import _permitted
from .sim.camera import Frame, SimCamera

PVDOTNET = r"C:\Program Files\Common Files\Pleora\eBUS SDK\PvDotNet.dll"
HELPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ebus_helper")
HELPER_SRC, HELPER_DLL = os.path.join(HELPER_DIR, "MtpyEbus.cs"), os.path.join(HELPER_DIR, "MtpyEbus.dll")
CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
RING_DEPTH = 100
TICK_S = 1e-9                                  # PvBuffer.Timestamp of the SP-5000M: 1 GHz (rig 2026-11-01)
_sdk = None


def _load():
    """(PvDotNet namespace, helper class), loaded once; builds the helper DLL when it is missing or older than its
    source. ConnectionError with the reason when the SDK is not installed."""
    global _sdk
    if _sdk is not None:
        return _sdk
    if not os.path.exists(PVDOTNET):
        raise ConnectionError(f"eBUS SDK not found ({PVDOTNET}): install JAI's eBUS SDK 64-bit")
    if not os.path.exists(HELPER_DLL) or os.path.getmtime(HELPER_DLL) < os.path.getmtime(HELPER_SRC):
        r = subprocess.run([CSC, "-nologo", "-target:library", "-unsafe", "-optimize", f"-out:{HELPER_DLL}",
                            f"-reference:{PVDOTNET}", HELPER_SRC], check=False, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise ConnectionError(f"building the eBUS pointer helper failed: {r.stdout} {r.stderr}")
    import clr
    clr.AddReference(PVDOTNET)
    clr.AddReference(HELPER_DLL)
    import PvDotNet as Pv

    from Mtpy import MtpyEbus as H
    _sdk = (Pv, H)
    return _sdk


class EbusCamera(Device):
    name, model, hint = SimCamera.name, SimCamera.model, SimCamera.hint
    timestamp_source = "camera timestamp (U3V device clock, ns ticks; s since the first frame of the acquisition)"
    settings_kinds = SimCamera.settings_kinds
    open_timeout_s = 30.0
    check_setting, tol, limits = SimCamera.check_setting, SimCamera.tol, SimCamera.limits

    def __init__(self, ring_size=64, serial=None):
        self.dev, self.info, self.serial = None, None, serial
        self._cond = threading.Condition()
        self._ring = collections.deque(maxlen=ring_size)
        self._thread, self._run = None, threading.Event()
        self._stream = None
        self.error = None                       # why the frame thread ended on its own, if it did

    def _io(self):
        if self.dev is None:
            raise ConnectionError("camera session not open")
        return self.dev

    # --- session -------------------------------------------------------------------------------------------------
    def open(self):
        _permitted()
        Pv, _ = _load()
        system = Pv.PvSystem()
        system.Find()
        found = [system.GetInterface(i).GetDeviceInfo(j) for i in range(system.InterfaceCount)
                 for j in range(system.GetInterface(i).DeviceCount)]
        if self.serial is not None:
            found = [d for d in found if str(getattr(d, "U3VSerialNumber", d.SerialNumber)) == str(self.serial)]
        if not found:
            raise ConnectionError("eBUS enumerates no camera - connected on USB 3, bound to the Pleora USB3 Vision "
                                  "driver, and not held by another program (eBUS Player)?")
        self.info = found[0]
        self.dev = Pv.PvDevice.CreateAndConnect(self.info)
        self._system = system                   # keeps the device info alive while the session lasts

    def close(self):
        self.stop_acquisition()
        if self.dev is not None:
            self.dev.Disconnect()
            self.dev = None

    def identity(self):
        P = self._io().Parameters
        return {"model": str(self.info.ModelName), "serial": str(getattr(self.info, "U3VSerialNumber", self.info.SerialNumber)),
                "firmware": str(P.GetStringValue("DeviceFirmwareVersion")), "port": str(self.info.DisplayID),
                "driver": "JAI eBUS SDK PvDotNet.dll via pythonnet (mtpy.devices.ebus)"}

    def settings(self):
        P = self._io().Parameters
        return {"exposure_ms": float(P.GetFloatValue("ExposureTime")) / 1000.0, "gain_dB": float(P.GetFloatValue("Gain")),
                "rate_Hz": float(P.GetFloatValue("AcquisitionFrameRate")),
                "roi": tuple(int(P.GetIntegerValue(k)) for k in ("OffsetX", "OffsetY", "Width", "Height")),
                "exposure_auto": str(P.GetEnumValueAsString("ExposureAuto")), "acquiring": self.acquiring(),
                "frame_thread_error": self.error}

    def set(self, name, value):
        P = self._io().Parameters
        if self.settings_kinds[name][0] == NEEDS_PAUSE and self.acquiring():
            raise RuntimeError(f"{name} cannot be written while acquiring (stop acquisition first)")
        if name == "exposure_ms":
            P.SetEnumValue("ExposureAuto", "Off")
            P.SetFloatValue("ExposureTime", float(value) * 1000.0)
        elif name == "rate_Hz":
            P.SetFloatValue("AcquisitionFrameRate", float(value))
        elif name == "roi":                     # offsets to 0 first, so a smaller window never overflows the sensor
            x, y, w, h = (int(v) for v in value)
            for k, v in (("OffsetX", 0), ("OffsetY", 0), ("Width", w), ("Height", h), ("OffsetX", x), ("OffsetY", y)):
                P.SetIntegerValue(k, v)
        else:
            raise RuntimeError(f"{name} is read-only on the real camera (the JAI gain unit is not verified)")

    def get(self, name):
        return self.settings()[name]

    # --- acquisition (the frame path) ---------------------------------------------------------------------------
    def acquiring(self):
        return self._thread is not None and self._thread.is_alive()

    def start_acquisition(self):
        d = self._io()
        if self.acquiring():
            return
        Pv, _ = _load()
        self._ring.clear()
        self.error = None
        stream = Pv.PvStream.CreateAndOpen(self.info)
        pipe = Pv.PvPipeline(stream)
        pipe.BufferSize = d.PayloadSize
        pipe.BufferCount = RING_DEPTH
        pipe.Start()
        d.StreamEnable()
        d.Parameters.ExecuteCommand("AcquisitionStart")
        self._stream = (stream, pipe)
        self._run.set()
        self._thread = threading.Thread(target=self._produce, args=(pipe,), name="ebus-frames", daemon=True)
        self._thread.start()

    def _produce(self, pipe):
        Pv, H = _load()
        t_first = None
        try:
            while self._run.is_set():
                res, buf = pipe.RetrieveNextBuffer(Pv.PvBuffer(), 1000)   # ref arg: an instance in, the real one back
                if not res.IsOK:
                    continue                    # timeout (no frame within 1 s): keep waiting while running
                try:
                    if not buf.OperationResult.IsOK:
                        continue
                    im = buf.Image
                    w, h = int(im.Width), int(im.Height)
                    img = np.frombuffer(ctypes.string_at(H.ImageAddress(im), w * h), dtype=np.uint8).reshape(h, w)
                    ts = int(buf.Timestamp)
                    if t_first is None:
                        t_first = ts
                    frame = Frame(int(buf.BlockID), (ts - t_first) * TICK_S, img)
                finally:
                    pipe.ReleaseBuffer(buf)
                with self._cond:
                    self._ring.append(frame)
                    self._cond.notify_all()
        except Exception as e:  # noqa: BLE001 - a stop tears the pipeline down under the thread; anything else is kept
            if self._run.is_set():
                self.error = f"{type(e).__name__}: {e}"

    def stop_acquisition(self):
        self._run.clear()
        if self._thread is not None:
            self._thread.join(timeout=6.0)
            self._thread = None
        if self._stream is not None:
            stream, pipe = self._stream
            self._stream = None
            d = self.dev
            if d is not None:
                d.Parameters.ExecuteCommand("AcquisitionStop")
                d.StreamDisable()
            pipe.Stop()
            stream.Close()

    def next_frame(self, timeout_s=1.0):
        """The oldest frame not yet taken, or None after timeout_s."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._ring, timeout_s):
                return None
            return self._ring.popleft()

    def stop(self):
        """Emergency stop: a camera has no motion; nothing to halt."""
