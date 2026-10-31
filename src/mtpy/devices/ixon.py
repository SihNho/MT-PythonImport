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
Open reads the state a previous owner left (LabVIEW, a crash): a sensor below -20 C is adopted as the set point so
the read-back is true and close() warms it up (owner 2026-10-31: check the state at start, reset, then connect).
Close = abort, warm-up by the camera's own regulation (set point = top of the range + CoolerON, judged by the
temperature only), CoolerOFF above -20 C, ShutDown. On this iXon CoolerOFF alone does not stop the cooler (rig
2026-10-30: -80 C for 30 min after CoolerOFF; IsCoolerOn and the GetTemperature status were wrong both ways).
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
        "GetTotalNumberImagesAcquired": (P(c_int),), "GetNumberNewImages": (P(c_int), P(c_int)),
        "GetImages16": (c_int, c_int, P(ctypes.c_uint16), ctypes.c_ulong, P(c_int), P(c_int)),
        "GetNumberHSSpeeds": (c_int, c_int, P(c_int)), "GetHSSpeed": (c_int, c_int, c_int, P(c_float)),
        "GetNumberVSSpeeds": (P(c_int),), "GetVSSpeed": (c_int, P(c_float)),
        "IsInternalMechanicalShutter": (P(c_int),), "GetCapabilities": (P(ctypes.c_ulong * 13),),
        "SetShutterEx": (c_int,) * 5}

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

    READOUT_FT_S = 0.015                      # frame transfer on: the shortest period
    RING = 50                                 # frames the SDK ring holds before it wraps

    def __init__(self):
        self.exposure_s, self.cycle_s, self.gain, self.gain_mode, self.ft = 0.1, 0.0, 0, 0, 0
        self.set_c, self.cooler, self.acquiring, self.initialized, self.shut = 20, False, False, False, False
        self.t_start, self.read_to, self.shutter = 0.0, 0, 2
        self.stuck_c = None                   # when set: the sensor reads this whatever the cooler is told
        self.calls = []

    def _period(self):
        p = max(self.cycle_s, self.exposure_s, self.READOUT_FT_S) if self.ft else \
            max(self.cycle_s, self.exposure_s + self.READOUT_S)
        return p + (0.1 if self.shutter == 0 else 0.0)        # auto shutter: both 50 ms transfer times per frame

    def _total(self):
        return int((time.perf_counter() - self.t_start) / self._period()) if self.acquiring else 0

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
            if self.stuck_c is not None:
                args[0]._obj.value = self.stuck_c
                return 20037
            args[0]._obj.value = self.set_c if self.cooler else 20
            return 20036 if self.cooler else 20034
        elif name == "GetEMCCDGain":
            args[0]._obj.value = self.gain
        elif name == "GetAcquisitionTimings":
            args[2]._obj.value = self._period()
            args[0]._obj.value = self._period() if self.ft else self.exposure_s
        elif name == "GetNumberNewImages":
            total = self._total()
            first = max(self.read_to + 1, total - self.RING + 1)
            if total < first:
                return 20024
            args[0]._obj.value, args[1]._obj.value = first, total
        elif name == "GetImages16":
            first, last, n = args[0], args[1], args[3]
            np.ctypeslib.as_array(args[2], shape=(n,))[:] = 100 + (first % 7)
            args[4]._obj.value, args[5]._obj.value = first, last
            self.read_to = last
        elif name == "SetFrameTransferMode":
            self.ft = args[0]
        elif name == "IsInternalMechanicalShutter":
            args[0]._obj.value = 0
        elif name == "GetCapabilities":
            args[0]._obj[8] = 0
        elif name in ("SetShutter", "SetShutterEx"):
            if args[2] < 50:
                raise AndorError(f"{name} returned 20068")
            self.shutter = args[1]
        elif name in ("GetNumberHSSpeeds", "GetNumberVSSpeeds"):
            args[-1]._obj.value = 3
        elif name == "GetHSSpeed":
            args[3]._obj.value = (17.0, 10.0, 5.0)[args[2]]
        elif name == "GetVSSpeed":
            args[1]._obj.value = (0.3, 0.5, 0.9)[args[0]]
        elif name == "GetStatus":
            args[0]._obj.value = DRV_ACQUIRING if self.acquiring else DRV_IDLE
        elif name == "GetMostRecentImage16":
            n = args[1]
            buf = np.ctypeslib.as_array(args[0], shape=(n,))
            buf[:] = (np.random.default_rng(0).integers(90, 110, n) * (1 + self.gain) * self.exposure_s * 10).astype(np.uint16)
        elif name == "GetTotalNumberImagesAcquired":
            args[0]._obj.value = self._total()
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
                self.acquiring, self.t_start, self.read_to = True, time.perf_counter(), 0
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
                                      ("frame_transfer", "shutter", "exposure_ms", "rate_Hz", "em_gain_mode",
                                       "em_gain", "temperature_C")}
    open_timeout_s = 60.0                   # Initialize loads the firmware (seconds)
    close_timeout_s = 900.0                 # the warm-up wait before ShutDown
    stall_s = 60.0                          # a warm-up that moves less than 2 C in this time has failed
    needs_lock = True

    def __init__(self, sdk=None):
        self.sdk_factory = sdk or AndorSdk
        self.sdk = None
        self._lock = threading.Lock()         # settings are read on the service thread and by the GUI snap
        self.detector = (0, 0)
        self.gain_range, self.temp_range = (0, 0), (0, 0)
        self._gain_mode, self._set_c, self.cooler_on = 0, None, False
        self._ft, self._exp_s, self._cycle_s = 0, None, 0.0     # frame transfer, last exposure / cycle requested
        self._shutter, self.has_shutter = 2, False              # 0 auto, 1 open, 2 closed (SetShutter mode)
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
            rc, t = self._get("GetTemperature", c_int)
            self.identity_d["found_at_open"] = {"sensor_temperature_C": t, "cooler": TEMP_STATUS[rc]}
            if t < WARM_C:
                # left cooling by a previous owner (rig 2026-10-30: -80 C, status "off"): make it our set point
                sdk("SetTemperature", max(t, self.temp_range[0]))
                sdk("CoolerON")
                self._set_c, self.cooler_on = max(t, self.temp_range[0]), True
            w, h_ = self.detector
            # smCamera's fixed set-up (manual section 3); frame transfer OFF by default (exposure and rate independent)
            for call in (("SetReadMode", 4), ("SetAcquisitionMode", 5), ("SetFrameTransferMode", self._ft),
                         ("SetTriggerMode", 0), ("SetImage", 1, 1, 1, w, 1, h_), ("SetOutputAmplifier", 0),
                         ("SetHSSpeed", 0, 0)):
                sdk(*call)
            self._shutter_facts(sdk)
            vs, f = c_int(), c_float()
            sdk("GetFastestRecommendedVSSpeed", ctypes.byref(vs), ctypes.byref(f))
            sdk("SetVSSpeed", vs.value)
            # the readout speeds the camera offers (EM amplifier), for the owner's choice of frame rate vs noise
            n_hs = c_int()
            sdk("GetNumberHSSpeeds", 0, 0, ctypes.byref(n_hs))
            hs = []
            for i in range(n_hs.value):
                sdk("GetHSSpeed", 0, 0, i, ctypes.byref(f))
                hs.append(round(f.value, 3))
            n_vs = c_int()
            sdk("GetNumberVSSpeeds", ctypes.byref(n_vs))
            vss = []
            for i in range(n_vs.value):
                sdk("GetVSSpeed", i, ctypes.byref(f))
                vss.append(round(f.value, 3))
            self.identity_d.update(hs_speeds_MHz=hs, hs_speed_index=0, vs_speeds_us=vss, vs_speed_index=vs.value)
            sdk("SetEMGainMode", self._gain_mode)
            self.gain_range = self._get("GetEMGainRange", c_int, c_int)
            self._measure_readout()
        except Exception:
            sdk("ShutDown")
            self.sdk = None
            raise

    def _shutter_facts(self, sdk):
        """Owner 2026-10-30: does this iXon have an internal shutter? Recorded in the identity: the SDK's
        IsInternalMechanicalShutter answer, the capability bits AC_FEATURES_SHUTTER (8) / SHUTTEREX (16), and what
        SetShutter / SetShutterEx answered (the 897 refused SetShutter with 20068 on the rig)."""
        d = self.identity_d
        self.has_shutter = False
        try:
            d["internal_shutter"] = bool(self._get("IsInternalMechanicalShutter", c_int))
        except AndorError as e:
            d["internal_shutter"] = f"not answered: {e}"
        caps = (ctypes.c_ulong * 13)()
        caps[0] = ctypes.sizeof(caps)
        try:
            sdk("GetCapabilities", ctypes.byref(caps))
            d["features_shutter"], d["features_shutterex"] = bool(caps[8] & 8), bool(caps[8] & 16)
        except AndorError as e:
            d["features_shutter"] = f"not answered: {e}"
        # closed until an acquisition starts (the LabVIEW program opened it first, then acquired: owner 2026-10-30);
        # 50 ms transfer times (Andor's example; 0 and 10 ms answered 20068 P3 invalid). Never auto (mode 0): the
        # SDK then adds both transfer times to every frame (readout read 124.59 ms instead of 24.59 on the rig).
        for call in (("SetShutter", 1, 2, 50, 50), ("SetShutterEx", 1, 2, 50, 50, 0)):
            try:
                sdk(*call)
                d[call[0]] = "ok (closed)"
                self.has_shutter = True
            except AndorError as e:
                d[call[0]] = f"refused: {e}"
        self._shutter = 2

    def _set_shutter(self, mode):
        if self.has_shutter:
            self._io()("SetShutter", 1, int(mode), 50, 50)
        self._shutter = int(mode)

    def _measure_readout(self):
        """readout_ms = the shortest frame period minus the exposure (frame transfer off: 24.59 ms on the 897 at
        512 x 512, rig 2026-10-30) or the shortest period itself (frame transfer on: the exposure overlaps the
        readout and equals the period). Measured with a 0 exposure and the fastest cycle, then the requested
        exposure and cycle are put back."""
        sdk = self.sdk
        exp0 = self._exp_s if self._exp_s is not None else self._get("GetAcquisitionTimings", c_float, c_float, c_float)[0]
        sdk("SetExposureTime", 0.0)
        sdk("SetKineticCycleTime", 0.0)
        exp, _acc, kin = self._get("GetAcquisitionTimings", c_float, c_float, c_float)
        self.readout_ms = (kin if self._ft else kin - exp) * 1000.0
        sdk("SetExposureTime", exp0)
        sdk("SetKineticCycleTime", self._cycle_s)

    def close(self):
        sdk = self.sdk
        if sdk is None:
            return
        self.stop_acquisition()             # abort and shutter closed
        self._warm_up()                     # a failure here keeps the handle: the retry warms up again (fault list D1 / D11)
        sdk("CoolerOFF")
        self.cooler_on = False
        sdk("ShutDown")
        self.sdk = None

    def _warm_up(self):
        """Bring the sensor above WARM_C through the camera's own regulation: set point = top of the range + CoolerON
        (rig 2026-10-30: -80 -> +17 C in 4 min; CoolerOFF and SetCoolerMode(0) had changed nothing in 30 min).
        Judged by the temperature trajectory alone; fails fast when it does not move."""
        t = self._get("GetTemperature", c_int)[1]
        if t >= WARM_C:
            return
        hi = self.temp_range[1]
        self.sdk("SetTemperature", hi)
        self.sdk("CoolerON")
        t0, now = t, time.monotonic()
        t_stall, t_end = now + self.stall_s, now + self.close_timeout_s - 5.0
        while t < WARM_C:
            now = time.monotonic()
            if now > t_stall and t - t0 < 2.0:
                raise TimeoutError(f"sensor {t} C did not warm up within {self.stall_s:.0f} s of SetTemperature({hi}) + "
                                   f"CoolerON (was {t0} C); ShutDown not called")
            if now > t_end:
                raise TimeoutError(f"sensor still below {WARM_C} C ({t} C) after the warm-up wait; ShutDown not called")
            time.sleep(2.0)
            t = self._get("GetTemperature", c_int)[1]

    def identity(self):
        self._io()
        return dict(self.identity_d, detector=self.detector)

    def settings(self):
        self._io()
        with self._lock:
            exp, _acc, kin = self._get("GetAcquisitionTimings", c_float, c_float, c_float)
            rc, t = self._get("GetTemperature", c_int)
            return {"frame_transfer": self._ft, "shutter": self._shutter, "exposure_ms": exp * 1000.0, "rate_Hz": 1.0 / kin if kin > 0 else 0.0,
                    "rate_requested_Hz": 1.0 / self._cycle_s if self._cycle_s else None,   # None: fastest cycle, no constraint
                    "em_gain_mode": self._gain_mode, "em_gain": self._get("GetEMCCDGain", c_int),
                    "temperature_C": self._set_c, "sensor_temperature_C": t, "cooler": TEMP_STATUS[rc],
                    "acquiring": self.acquiring()}

    def limits(self):
        ft = self._ft
        return {"frame_transfer": "0 off (period = exposure + readout), 1 on (exposure = period >= readout)",
                "shutter": "0 auto (adds 100 ms per frame), 1 open, 2 closed; opened at start, closed at stop",
                "exposure_ms": (f"= frame period, >= {self.readout_ms:.2f} ms readout" if ft else
                                f"0.001 .. frame period - {self.readout_ms:.2f} ms readout"),
                "rate_Hz": (f"0.01 .. {1000.0 / self.readout_ms:.3f} (1 / {self.readout_ms:.2f} ms readout)" if ft else
                            f"0.01 .. 1000 / (exposure_ms + {self.readout_ms:.2f} ms readout)"),
                "em_gain_mode": f"0..3 ({', '.join(GAIN_MODES)})", "em_gain": self.gain_range,
                "temperature_C": self.temp_range}

    def check_setting(self, name, value, rate_Hz, exposure_ms):
        """SafetyRefused unless `value` is valid for `name` given the rate and exposure in force (rate_Hz None: no
        rate was requested, the cycle is the fastest for the exposure, so the exposure is unconstrained). No I/O."""
        def num(v):
            return isinstance(v, (int, float, np.number)) and not isinstance(v, bool) and np.isfinite(v)
        def integer(v):
            return isinstance(v, (int, np.integer)) and not isinstance(v, bool)
        # the camera would lengthen the period silently otherwise. Frame transfer off: period = exposure + readout.
        # Frame transfer on: the exposure overlaps the readout, so exposure = period >= readout (the SDK reads the
        # exposure back as the cycle), and the rate is set alone: 1 / period <= 1 / readout.
        period = 1000.0 / rate_Hz if rate_Hz else float("inf")
        if name == "frame_transfer":
            if value not in (0, 1) or isinstance(value, bool):
                raise SafetyRefused(f"emccd frame_transfer {value!r} is not 0 or 1")
        elif name == "shutter":
            if value not in (0, 1, 2) or isinstance(value, bool):
                raise SafetyRefused(f"emccd shutter {value!r} is not 0 (auto), 1 (open) or 2 (closed)")
        elif name == "exposure_ms" and self._ft:
            if rate_Hz is None or not (num(value) and abs(value - period) <= max(0.02, 0.01 * period)):
                raise SafetyRefused(f"emccd exposure {value!r} ms: in frame-transfer mode the exposure equals the "
                                    f"frame period ({period:.3f} ms at {rate_Hz or 0:g} Hz); set the rate instead")
        elif name == "exposure_ms":
            hi = period - self.readout_ms
            if not (num(value) and 0.001 <= value <= hi * 1.01):
                raise SafetyRefused(f"emccd exposure {value!r} ms is outside [0.001, {hi:.3f}] ms (frame period at "
                                    f"{rate_Hz:g} Hz minus the {self.readout_ms:.2f} ms readout); lower the rate first")
        elif name == "rate_Hz":
            hi = 1000.0 / (self.readout_ms if self._ft else exposure_ms + self.readout_ms)
            if not (num(value) and 0.01 <= value <= hi * 1.01):
                raise SafetyRefused(f"emccd rate {value!r} Hz is outside [0.01, {hi:.3f}] Hz (1 / "
                                    + (f"readout {self.readout_ms:.2f} ms, frame transfer on)" if self._ft else
                                       f"(exposure {exposure_ms:g} ms + readout {self.readout_ms:.2f} ms)); "
                                       "shorten the exposure first"))
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
            if name == "frame_transfer":
                sdk("SetFrameTransferMode", int(value))
                self._ft = int(value)
                self._measure_readout()
            elif name == "shutter":
                self._set_shutter(value)
                self._measure_readout()          # auto mode adds the transfer times to the period
            elif name == "exposure_ms":
                self._exp_s = float(value) / 1000.0
                sdk("SetExposureTime", self._exp_s)
            elif name == "rate_Hz":
                self._cycle_s = 1.0 / float(value)
                if self._ft:                     # frame transfer: the exposure is the period
                    self._exp_s = self._cycle_s
                    sdk("SetExposureTime", self._exp_s)
                sdk("SetKineticCycleTime", self._cycle_s)
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
        """Shutter open first (as the LabVIEW program did), then StartAcquisition."""
        if not self.acquiring():
            if self._shutter == 2:
                self._set_shutter(1)
            self._io()("StartAcquisition")

    def stop_acquisition(self):
        """AbortAcquisition, then the shutter closed."""
        if self.acquiring():
            self._io()("AbortAcquisition")
        if self.sdk is not None and self._shutter != 2:
            self._set_shutter(2)

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

    def cycle_shutter(self, cycles, pause_s):
        """Owner 2026-10-30: exercise a stiff shutter blade. SetShutter open / closed `cycles` times, `pause_s`
        after each call, stopping at the first return code other than DRV_SUCCESS; the shutter is left closed.
        Returns {"calls_ok", "cycles", "stopped_at": None | (cycle, "open" | "closed", error)}."""
        sdk = self._io()
        r = {"calls_ok": 0, "cycles": int(cycles), "stopped_at": None}
        try:
            for i in range(int(cycles)):
                for mode, name in ((1, "open"), (2, "closed")):
                    try:
                        sdk("SetShutter", 1, mode, 50, 50)
                    except AndorError as e:
                        r["stopped_at"] = (i + 1, name, str(e))
                        return r
                    r["calls_ok"] += 1
                    time.sleep(pause_s)
        finally:
            self._set_shutter(2)
        return r

    def read_new(self):
        """Every frame not yet read, from the SDK's circular buffer: (first, last, uint16 array n x h x w), or
        None when there is none. first / last are the SDK's own frame numbers (1-based, counting since the
        acquisition start): a jump over the last frame read is a loss (the buffer wrapped)."""
        sdk = self._io()
        first, last = c_int(), c_int()
        if sdk("GetNumberNewImages", ctypes.byref(first), ctypes.byref(last), ok=(DRV_SUCCESS, 20024)) == 20024:
            return None
        w, h = self.detector
        n = last.value - first.value + 1
        buf = np.empty(n * h * w, dtype=np.uint16)
        vf, vl = c_int(), c_int()
        sdk("GetImages16", first.value, last.value, buf.ctypes.data_as(P(ctypes.c_uint16)), buf.size,
            ctypes.byref(vf), ctypes.byref(vl))
        return vf.value, vl.value, buf.reshape(n, h, w)[: vl.value - vf.value + 1]

    def total_acquired(self):
        """Frames the camera has produced since the acquisition start (SDK counter)."""
        return self._get("GetTotalNumberImagesAcquired", c_int)


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
