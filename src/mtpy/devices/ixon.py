"""The Andor iXon Ultra EMCCD as a `Device` ("emccd"), on Andor SDK2 `atmcd64d.dll` through ctypes
(docs/manuals/andor-ixon.md; the parameter set follows smCamera, docs/manuals/smcamera-emccd-parameters.md).

Owner 2026-10-30: the core parameters must be adjustable - exposure time, frame rate, EM gain mode, EM gain and the
sensor temperature; every other parameter later. So `settings()` / `set()` cover exactly those five:
- `exposure_ms`: `SetExposureTime` (seconds on the SDK); read back from `GetAcquisitionTimings`.
- `rate_Hz`: `SetKineticCycleTime(1 / rate)` in run-till-abort mode with frame transfer OFF (so the exposure and the
  cycle stay independent: cycle >= exposure + readout); read back as 1 / kinetic cycle. A rate the camera cannot
  reach reads back lower and the API reports the mismatch (U15), it is not silently clamped.
- `em_gain_mode`: `SetEMGainMode` 0 = 8 bit DAC, 1 = 12 bit, 2 = linear, 3 = real EM gain; the SDK has no getter, so
  the read-back is the value kept here; the gain range (`GetEMGainRange`) is re-read after every mode change.
- `em_gain`: `SetEMCCDGain` / `GetEMCCDGain`, within `GetEMGainRange`; gain above the normal range stays locked
  (`SetEMAdvanced` never called: high EM gain with bright light damages the EM register).
- `temperature_C`: `SetTemperature` + `CoolerON`, within `GetTemperatureRange`; the SDK has no set-point getter, so
  the read-back is the value kept here; `sensor_temperature_C` and `cooler` (the GetTemperature status) are read.
A set while acquiring aborts the acquisition, applies, and starts again (the SDK refuses writes while acquiring).
Close = abort, cooler off, wait until the sensor is warmer than -20 C (Andor's guidance; `close_timeout_s`), ShutDown.
Opens only under the rig lock, like the JAI (`jai._permitted`). The simulator `SimEmccd` is this class on `FakeAndor`.
"""
import ctypes
import threading
import time
from typing import ClassVar

import numpy as np

from mtpy.api.errors import SafetyRefused

from .base import IMMEDIATE, Device

DLL = r"C:\Program Files\Andor Driver Pack 2\atmcd64d.dll"
DRV_SUCCESS, DRV_ACQUIRING, DRV_IDLE = 20002, 20072, 20073
TEMP_STATUS = {20034: "off", 20035: "not stabilized", 20036: "stabilized", 20037: "not reached", 20040: "drift",
               20002: "ok"}
WARM_C = -20                                  # ShutDown only above this (manual "Safety envelope")
GAIN_MODES = ("8 bit DAC", "12 bit DAC", "linear", "real EM gain")
c_int, c_float = ctypes.c_int, ctypes.c_float
P = ctypes.POINTER


class AndorError(RuntimeError):
    pass


class AndorSdk:
    """The SDK2 calls this device uses, each raising AndorError unless the return code is DRV_SUCCESS (or, for
    GetTemperature, one of its status codes)."""
    SIGS: ClassVar[dict] = {
        "GetAvailableCameras": (P(c_int),), "GetCameraHandle": (c_int, P(c_int)), "SetCurrentCamera": (c_int,),
        "Initialize": (ctypes.c_char_p,), "ShutDown": (), "GetHeadModel": (ctypes.c_char_p,),
        "GetCameraSerialNumber": (P(c_int),), "GetDetector": (P(c_int), P(c_int)),
        "GetTemperatureRange": (P(c_int), P(c_int)), "SetTemperature": (c_int,), "CoolerON": (), "CoolerOFF": (),
        "GetTemperature": (P(c_int),), "GetEMGainRange": (P(c_int), P(c_int)), "SetEMGainMode": (c_int,),
        "SetEMCCDGain": (c_int,), "GetEMCCDGain": (P(c_int),), "SetReadMode": (c_int,),
        "SetAcquisitionMode": (c_int,), "SetFrameTransferMode": (c_int,), "SetTriggerMode": (c_int,),
        "SetImage": (c_int,) * 6, "SetExposureTime": (c_float,), "SetKineticCycleTime": (c_float,),
        "GetAcquisitionTimings": (P(c_float),) * 3, "SetShutter": (c_int,) * 4, "SetOutputAmplifier": (c_int,),
        "SetHSSpeed": (c_int, c_int), "GetFastestRecommendedVSSpeed": (P(c_int), P(c_float)), "SetVSSpeed": (c_int,),
        "StartAcquisition": (), "AbortAcquisition": (), "GetStatus": (P(c_int),),
        "GetMostRecentImage16": (P(ctypes.c_uint16), ctypes.c_ulong),
        "GetTotalNumberImagesAcquired": (P(c_int),)}

    def __init__(self, path=DLL):
        self.dll = ctypes.WinDLL(path)
        for name, args in self.SIGS.items():
            fn = getattr(self.dll, name)
            fn.argtypes, fn.restype = list(args), ctypes.c_uint

    def __call__(self, name, *args, ok=(DRV_SUCCESS,)):
        rc = getattr(self.dll, name)(*args)
        if rc not in ok:
            raise AndorError(f"{name} returned {rc}")
        return rc


class FakeAndor:
    """SDK2 as an iXon Ultra 897 answers it, for the simulator and the tests: 512 x 512, -120..20 C, EM gain
    1..300 (mode 0: 0..255), readout 17.9 ms per frame (cycle = max(requested, exposure + readout))."""
    READOUT_S = 0.0179
    cameras = 1

    def __init__(self):
        self.exposure_s, self.cycle_s, self.gain, self.gain_mode = 0.1, 0.0, 0, 0
        self.set_c, self.cooler, self.acquiring, self.initialized, self.shut = 20, False, False, False, False
        self.calls = []

    def __call__(self, name, *args, ok=(DRV_SUCCESS,)):
        self.calls.append(name)
        if name == "Initialize" and self.cameras:
            self.initialized = True
        elif name == "GetAvailableCameras":
            args[0]._obj.value = self.cameras
        elif name == "GetHeadModel":
            args[0].value = b"DU897_BV"
        elif name == "GetCameraSerialNumber":
            args[0]._obj.value = 12345
        elif name == "GetDetector":
            args[0]._obj.value, args[1]._obj.value = 512, 512
        elif name == "GetTemperatureRange":
            args[0]._obj.value, args[1]._obj.value = -120, 20
        elif name == "GetEMGainRange":
            args[0]._obj.value, args[1]._obj.value = (0, 255) if self.gain_mode == 0 else (1, 300)
        elif name == "GetTemperature":
            args[0]._obj.value = self.set_c if self.cooler else 20
            return 20036 if self.cooler else 20034
        elif name == "GetEMCCDGain":
            args[0]._obj.value = self.gain
        elif name == "GetAcquisitionTimings":
            args[0]._obj.value = self.exposure_s
            args[2]._obj.value = max(self.cycle_s, self.exposure_s + self.READOUT_S)
        elif name == "GetStatus":
            args[0]._obj.value = DRV_ACQUIRING if self.acquiring else DRV_IDLE
        elif name == "GetMostRecentImage16":
            n = args[1]
            buf = np.ctypeslib.as_array(args[0], shape=(n,))
            buf[:] = (np.random.default_rng(0).integers(90, 110, n) * (1 + self.gain) * self.exposure_s * 10).astype(np.uint16)
        elif name == "GetTotalNumberImagesAcquired":
            args[0]._obj.value = 1
        elif name in ("SetTemperature", "SetEMCCDGain", "SetEMGainMode", "SetExposureTime", "SetKineticCycleTime",
                      "StartAcquisition", "AbortAcquisition", "CoolerON", "CoolerOFF", "ShutDown"):
            if self.acquiring and name.startswith("Set"):
                raise AndorError(f"{name} returned {DRV_ACQUIRING}")
            v = args[0] if args else None
            if name == "SetTemperature":
                self.set_c = v
            elif name == "SetEMCCDGain":
                self.gain = v
            elif name == "SetEMGainMode":
                self.gain_mode = v
            elif name == "SetExposureTime":
                self.exposure_s = round(v, 6)
            elif name == "SetKineticCycleTime":
                self.cycle_s = v
            elif name == "StartAcquisition":
                self.acquiring = True
            elif name == "AbortAcquisition":
                self.acquiring = False
            elif name in ("CoolerON", "CoolerOFF"):
                self.cooler = name == "CoolerON"
            elif name == "ShutDown":
                self.initialized, self.shut = False, True
        return DRV_SUCCESS


class IxonCamera(Device):
    name, model = "emccd", "Andor iXon Ultra 897 (SDK2 atmcd64d.dll)"
    hint = "check the iXon's USB cable and power, and that Solis or a LabVIEW VI does not hold the camera"
    settings_kinds: ClassVar[dict] = {k: (IMMEDIATE, False) for k in
                                      ("exposure_ms", "rate_Hz", "em_gain_mode", "em_gain", "temperature_C")}
    open_timeout_s = 60.0                   # Initialize loads the firmware (seconds)
    close_timeout_s = 900.0                 # the warm-up wait before ShutDown
    needs_lock = True

    def __init__(self, sdk=None):
        self.sdk_factory = sdk or AndorSdk
        self.sdk = None
        self._lock = threading.Lock()         # settings are read on the service thread and by the GUI snap
        self.detector = (0, 0)
        self.gain_range, self.temp_range = (0, 0), (0, 0)
        self._gain_mode, self._set_c, self.cooler_on = 0, None, False
        self.readout_ms = 0.0
        self.identity_d = {}

    def _io(self):
        if self.sdk is None:
            raise ConnectionError("camera session not open")
        return self.sdk

    def _get(self, name, *types):
        """Call `name` with one ctypes out-argument per type and return their values."""
        outs = [t() for t in types]
        rc = self._io()(name, *(ctypes.byref(o) for o in outs), ok=(DRV_SUCCESS,) if name != "GetTemperature" else tuple(TEMP_STATUS))
        vals = [o.value for o in outs]
        return (rc, *vals) if name == "GetTemperature" else vals[0] if len(vals) == 1 else tuple(vals)

    def open(self):
        if self.needs_lock:
            from .jai import _permitted  # here, not at module level: jai -> sim -> ixon would be a cycle
            _permitted()
        sdk = self.sdk_factory()
        n = c_int()
        sdk("GetAvailableCameras", ctypes.byref(n))
        if n.value < 1:
            raise ConnectionError("no Andor camera found (GetAvailableCameras = 0)")
        h = c_int()
        sdk("GetCameraHandle", 0, ctypes.byref(h))
        sdk("SetCurrentCamera", h.value)
        sdk("Initialize", b"")
        self.sdk = sdk
        try:
            buf = ctypes.create_string_buffer(256)
            sdk("GetHeadModel", buf)
            self.identity_d = {"model": buf.value.decode(errors="replace"),
                               "serial": str(self._get("GetCameraSerialNumber", c_int)),
                               "port": "USB", "driver": f"Andor SDK2 {DLL} (mtpy.devices.ixon)"}
            self.detector = self._get("GetDetector", c_int, c_int)
            self.temp_range = self._get("GetTemperatureRange", c_int, c_int)
            w, h_ = self.detector
            # smCamera's fixed set-up (manual section 3), frame transfer OFF so exposure and rate stay independent
            for call in (("SetReadMode", 4), ("SetAcquisitionMode", 5), ("SetFrameTransferMode", 0),
                         ("SetTriggerMode", 0), ("SetImage", 1, 1, 1, w, 1, h_), ("SetOutputAmplifier", 0),
                         ("SetHSSpeed", 0, 0)):
                sdk(*call)
            try:
                sdk("SetShutter", 1, 0, 0, 0)   # auto; the 897 answered 20068 (P3 invalid) on the rig 2026-10-30
            except AndorError as e:
                self.identity_d["shutter"] = f"not set: {e}"
            vs = c_int()
            sdk("GetFastestRecommendedVSSpeed", ctypes.byref(vs), ctypes.byref(c_float()))
            sdk("SetVSSpeed", vs.value)
            sdk("SetEMGainMode", self._gain_mode)
            self.gain_range = self._get("GetEMGainRange", c_int, c_int)
            sdk("SetKineticCycleTime", 0.0)   # fastest cycle for the exposure in force
            exp, _acc, kin = self._get("GetAcquisitionTimings", c_float, c_float, c_float)
            self.readout_ms = (kin - exp) * 1000.0     # 24.6 ms on the 897 at 512 x 512 (rig 2026-10-30)
        except Exception:
            sdk("ShutDown")
            self.sdk = None
            raise

    def close(self):
        sdk = self.sdk
        if sdk is None:
            return
        try:
            if self.acquiring():
                sdk("AbortAcquisition")
            sdk("CoolerOFF")
            self.cooler_on = False
            t_end = time.monotonic() + self.close_timeout_s - 5.0
            while self._get("GetTemperature", c_int)[1] < WARM_C:
                if time.monotonic() > t_end:
                    raise TimeoutError(f"sensor still below {WARM_C} C after the warm-up wait; ShutDown not called "
                                       "(the cooler is off: wait, then disconnect again)")
                time.sleep(2.0)
            sdk("ShutDown")
        finally:
            self.sdk = None

    def identity(self):
        self._io()
        return dict(self.identity_d, detector=self.detector)

    def settings(self):
        self._io()
        with self._lock:
            exp, _acc, kin = self._get("GetAcquisitionTimings", c_float, c_float, c_float)
            rc, t = self._get("GetTemperature", c_int)
            return {"exposure_ms": exp * 1000.0, "rate_Hz": 1.0 / kin if kin > 0 else 0.0,
                    "em_gain_mode": self._gain_mode, "em_gain": self._get("GetEMCCDGain", c_int),
                    "temperature_C": self._set_c, "sensor_temperature_C": t, "cooler": TEMP_STATUS[rc],
                    "acquiring": self.acquiring()}

    def limits(self):
        return {"exposure_ms": f"0.001 .. frame period - {self.readout_ms:.2f} ms readout",
                "rate_Hz": f"0.01 .. 1000 / (exposure_ms + {self.readout_ms:.2f} ms readout)",
                "em_gain_mode": f"0..3 ({', '.join(GAIN_MODES)})", "em_gain": self.gain_range,
                "temperature_C": self.temp_range}

    def check_setting(self, name, value, rate_Hz, exposure_ms):
        """SafetyRefused unless `value` is valid for `name` given the rate and exposure in force. No I/O."""
        def num(v):
            return isinstance(v, (int, float, np.number)) and not isinstance(v, bool) and np.isfinite(v)
        def integer(v):
            return isinstance(v, (int, np.integer)) and not isinstance(v, bool)
        # frame transfer off: period = exposure + readout; the camera would lengthen the period silently otherwise
        if name == "exposure_ms":
            hi = 1000.0 / rate_Hz - self.readout_ms
            if not (num(value) and 0.001 <= value <= hi * 1.01):
                raise SafetyRefused(f"emccd exposure {value!r} ms is outside [0.001, {hi:.3f}] ms (frame period at "
                                    f"{rate_Hz:g} Hz minus the {self.readout_ms:.2f} ms readout); lower the rate first")
        elif name == "rate_Hz":
            hi = 1000.0 / (exposure_ms + self.readout_ms)
            if not (num(value) and 0.01 <= value <= hi * 1.01):
                raise SafetyRefused(f"emccd rate {value!r} Hz is outside [0.01, {hi:.3f}] Hz (1 / (exposure "
                                    f"{exposure_ms:g} ms + readout {self.readout_ms:.2f} ms)); shorten the exposure first")
        elif name == "em_gain_mode":
            if not (integer(value) and 0 <= value <= 3):
                raise SafetyRefused(f"emccd EM gain mode {value!r} is not 0..3 ({', '.join(GAIN_MODES)})")
        elif name == "em_gain":
            lo, hi = self.gain_range
            if not (integer(value) and (value == 0 or lo <= value <= hi)):   # 0 = EM gain off (the 897 reads 0 at open)
                raise SafetyRefused(f"emccd EM gain {value!r} is outside the camera's range [{lo}, {hi}] for gain "
                                    f"mode {self._gain_mode} (gain above the range stays locked)")
        elif name == "temperature_C":
            lo, hi = self.temp_range
            if not (integer(value) and lo <= value <= hi):
                raise SafetyRefused(f"emccd temperature {value!r} C is outside the camera's range [{lo}, {hi}] C")
        else:
            raise SafetyRefused(f"emccd has no setting {name!r}; settings: {sorted(self.settings_kinds)}")

    def tol(self, name, value):
        """Read-back tolerance: the SDK rounds timings to its clock; integers are exact."""
        if name in ("exposure_ms", "rate_Hz") and isinstance(value, (int, float)):
            return max(0.02, 0.01 * abs(value)) if name == "exposure_ms" else 0.01 * abs(value)
        return 0.0

    def set(self, name, value):
        sdk = self._io()
        was = self.acquiring()
        with self._lock:
            if was:
                sdk("AbortAcquisition")          # the SDK refuses every Set while acquiring
            if name == "exposure_ms":
                sdk("SetExposureTime", float(value) / 1000.0)
            elif name == "rate_Hz":
                sdk("SetKineticCycleTime", 1.0 / float(value))
            elif name == "em_gain_mode":
                sdk("SetEMGainMode", int(value))
                self._gain_mode = int(value)
                self.gain_range = self._get("GetEMGainRange", c_int, c_int)
            elif name == "em_gain":
                sdk("SetEMCCDGain", int(value))
            elif name == "temperature_C":
                sdk("SetTemperature", int(value))
                sdk("CoolerON")
                self._set_c, self.cooler_on = int(value), True
            else:
                raise RuntimeError(f"emccd has no setting {name!r}")
            if was:
                sdk("StartAcquisition")

    def get(self, name):
        return self.settings()[name]

    # --- acquisition ----------------------------------------------------------------------------------------------
    def acquiring(self):
        return self.sdk is not None and self._get("GetStatus", c_int) == DRV_ACQUIRING

    def start_acquisition(self):
        if not self.acquiring():
            self._io()("StartAcquisition")

    def stop_acquisition(self):
        if self.acquiring():
            self._io()("AbortAcquisition")

    def snap(self):
        """The most recent frame as uint16 (h, w): starts the acquisition if needed and waits one cycle for it."""
        sdk = self._io()
        w, h = self.detector
        if not self.acquiring():
            sdk("StartAcquisition")
        with self._lock:
            _exp, _acc, kin = self._get("GetAcquisitionTimings", c_float, c_float, c_float)
        time.sleep(min(2.0 * kin + 0.05, 10.0))
        img = np.empty(h * w, dtype=np.uint16)
        sdk("GetMostRecentImage16", img.ctypes.data_as(P(ctypes.c_uint16)), img.size)
        return img.reshape(h, w)


class SimEmccd(IxonCamera):
    """The iXon simulator: the real driver on `FakeAndor` (no DLL, no lock, no warm-up wait)."""
    needs_lock = False

    def __init__(self):
        super().__init__(sdk=FakeAndor)
        self.fault = None

    def _io(self):
        if self.fault == "no_reply":
            raise TimeoutError("no reply")
        return super()._io()
