"""Real JAI SP-5000M-USB through the NI-IMAQdx C API (decision 0021; docs/manuals/camera-jai-imaqdx.md).

Minimal raw-frame access for rig recordings: open, write + read back exposure / rate, ring acquisition by buffer
number, close. The phase-6 `Device` wrapper (`devices/sim/camera.py` is its simulator twin) builds on this; nothing
above it may depend on IMAQdx, so the SDK can be swapped (eBUS, GenTL) later.
- Buffer numbers count every frame the camera produced since start; a gap = frames the PC missed (manual "Units").
- Every open reloads the `.icd` file, so settings written here vanish at close; never edit or save the `.icd`.
- The camera has no hardware timestamp; frames carry the PC receive time (decision 0005).
"""
import ctypes as C
import time

import numpy as np

MAXSTR = 512
U32, I64, F64, STR, ENUM, BOOL = range(6)
NEXT, LAST, BUFNUM = 0, 1, 2
A = "CameraAttributes::"
IMG, ACQ, TL = A + "ImageFormatControl::", A + "AcquisitionControl::", A + "TransportLayerControl::"


class CameraInformation(C.Structure):
    _fields_ = [("Type", C.c_uint32), ("Version", C.c_uint32), ("Flags", C.c_uint32),
                ("SerialNumberHi", C.c_uint32), ("SerialNumberLo", C.c_uint32), ("BusType", C.c_uint32),
                ("InterfaceName", C.c_char * MAXSTR), ("VendorName", C.c_char * MAXSTR),
                ("ModelName", C.c_char * MAXSTR), ("CameraFileName", C.c_char * MAXSTR),
                ("CameraAttributeURL", C.c_char * MAXSTR)]


class ImaqdxError(RuntimeError):
    pass


class ImaqdxCamera:
    def __init__(self):
        self.dx = C.windll.LoadLibrary("niimaqdx.dll")
        self.sess = None
        self.acquiring = False

    def _ok(self, rc, what):
        if rc:
            buf = C.create_string_buffer(MAXSTR)
            self.dx.IMAQdxGetErrorString(C.c_int32(rc), buf, C.c_uint32(MAXSTR))
            raise ImaqdxError(f"{what}: error {rc} (0x{rc & 0xFFFFFFFF:08X}) {buf.value.decode('latin-1')}")

    def open(self):
        n = C.c_uint32(0)
        self.dx.IMAQdxEnumerateCameras(None, C.byref(n), C.c_uint32(1))
        if not n.value:
            raise ImaqdxError("no camera enumerated - connected, and not held by LabVIEW / NI MAX?")
        arr = (CameraInformation * n.value)()
        self._ok(self.dx.IMAQdxEnumerateCameras(arr, C.byref(n), C.c_uint32(1)), "EnumerateCameras")
        self.name = arr[0].InterfaceName.decode()          # 'cam1' on this rig; enumerate, never guess
        self.model = arr[0].ModelName.decode()
        self.serial = f"{arr[0].SerialNumberHi:08X}{arr[0].SerialNumberLo:08X}"
        s = C.c_uint32(0)
        self._ok(self.dx.IMAQdxOpenCamera(self.name.encode(), C.c_uint32(0), C.byref(s)), f"OpenCamera({self.name})")
        self.sess = s

    def get(self, name, t):
        if t == STR:
            b = C.create_string_buffer(MAXSTR)
            self._ok(self.dx.IMAQdxGetAttribute(self.sess, name.encode(), C.c_uint32(STR), b), f"get {name}")
            return b.value.decode("latin-1")
        v = C.c_double() if t == F64 else C.c_int64()
        self._ok(self.dx.IMAQdxGetAttribute(self.sess, name.encode(), C.c_uint32(t), C.byref(v)), f"get {name}")
        return v.value

    def set(self, name, t, value):
        arg = {STR: lambda v: v.encode(), F64: C.c_double, I64: C.c_int64}[t](value)
        self._ok(self.dx.IMAQdxSetAttribute(self.sess, name.encode(), C.c_uint32(t), arg), f"set {name}")

    def configure(self, rate_hz=None, exposure_us=None):
        """Write the condition (None = leave the .icd value, e.g. auto exposure) and return the read-back. A write is
        accepted with rc 0 even when clamped, so the caller records the read-back, not the request (pitfalls 7, 8)."""
        if exposure_us is not None:
            self.set(ACQ + "ExposureAuto", STR, "Off")
            self.set(ACQ + "ExposureTime", F64, float(exposure_us))
        if rate_hz is not None:
            self.set(ACQ + "AcquisitionFrameRate", F64, float(rate_hz))
        return self.readback()

    def readback(self):
        return {"camera": self.name, "model": self.model, "serial": self.serial,
                "width": self.get(IMG + "Width", I64), "height": self.get(IMG + "Height", I64),
                "binning_h": self.get(IMG + "BinningHorizontal", I64),
                "rate_hz": self.get(ACQ + "AcquisitionFrameRate", F64),
                "exposure_auto": self.get(ACQ + "ExposureAuto", STR),
                "exposure_us": self.get(ACQ + "ExposureTime", F64),
                "payload": self.get(TL + "PayloadSize", I64)}

    def start(self, n_buffers=50):
        rb = self.readback()
        self.shape, self.size = (rb["height"], rb["width"]), rb["payload"]
        if self.size != self.shape[0] * self.shape[1]:
            raise ImaqdxError(f"payload {self.size} B is not {self.shape} x 8 bit")
        self._buf = C.create_string_buffer(self.size)
        self._ok(self.dx.IMAQdxConfigureAcquisition(self.sess, C.c_uint32(1), C.c_uint32(n_buffers)), "Configure")
        self._ok(self.dx.IMAQdxStartAcquisition(self.sess), "StartAcquisition")
        self.acquiring = True

    def frame(self, buffer_number):
        """Wait for that buffer (driver timeout 5 s) -> (actual buffer number, PC receive time s, image copy). The
        driver may return a different buffer without an error (pitfall 6), so `actual` is the truth."""
        act = C.c_uint32(0)
        self._ok(self.dx.IMAQdxGetImageData(self.sess, self._buf, C.c_uint32(self.size), C.c_uint32(BUFNUM),
                                            C.c_uint32(buffer_number), C.byref(act)), "GetImageData")
        t = time.time()
        return act.value, t, np.frombuffer(self._buf.raw, np.uint8).reshape(self.shape)

    def stop_streaming(self):
        """StopAcquisition only: a GetImageData waiting on another thread returns (with an error); stop() then frees
        the ring. Safe to call twice."""
        if self.acquiring:
            self.dx.IMAQdxStopAcquisition(self.sess)

    def stop(self):
        if self.acquiring:
            self.acquiring = False
            self.dx.IMAQdxStopAcquisition(self.sess)
            self.dx.IMAQdxUnconfigureAcquisition(self.sess)

    def close(self):
        """Always safe to call; the camera returns to its .icd state by itself."""
        if self.sess is not None:
            self.stop()
            self.dx.IMAQdxCloseCamera(self.sess)
            self.sess = None
