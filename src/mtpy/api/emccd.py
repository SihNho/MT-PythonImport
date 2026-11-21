"""EMCCD (Andor iXon Ultra) settings: the five core parameters the owner asked for on 2026-10-30 - exposure, frame
rate, EM gain mode, EM gain, sensor temperature - each sent, read back and verified like a camera setting
(`mtpy.devices.ixon`). `snap()` grabs one frame.

Recording beside the JAI (plan 10a, owner 2026-11-21 "JAI + iXon measured together"): while `api.acq` runs, a
recorder thread reads every new EMCCD frame; while recording is on they go into the run file's `/fluorescence`
(raw images, the SDK frame number, an estimated host time, the newest JAI frame at the read). The EMCCD runs on its
internal trigger: the two cameras are aligned by host time only, until the Arduino frame divider exists (0005).

    api.emccd.apply_preset({"name": "tirf", "exposure_ms": 30.0, "rate_Hz": 20.0, "em_gain": 100, "temperature_C": -70})
    api.emccd.set_exposure(50.0)        # -> 50.0 read back (ms)
"""
import contextvars
import threading
import time

from . import events
from ._act import acting
from .devices import _services, service
from .errors import MtpyError, SafetyRefused

FIELDS = ("frame_transfer", "shutter", "em_gain_mode", "em_gain", "exposure_ms", "rate_Hz", "temperature_C")   # applied in this order


def _set(name, value, rate_Hz=None, exposure_ms=None):
    svc = service("emccd")
    dev = svc.require()
    s = svc.call(dev.settings, what="read settings")
    rate = s["rate_requested_Hz"] if rate_Hz is None else rate_Hz      # None: no rate requested yet
    exp = s["exposure_ms"] if exposure_ms is None else exposure_ms

    def check(v):
        dev.check_setting(name, v, rate, exp)
        return True
    return acting(f"emccd_{name}", value, lambda v: svc.call(dev.set, name, v, what=f"set {name} {v!r}"),
                  lambda: svc.call(dev.get, name, what=f"read {name}"), dev.tol(name, value), device="emccd",
                  check=check)


def set_frame_transfer(on):
    """0: period = exposure + readout (exposure and rate independent). 1: the exposure overlaps the readout, so the
    exposure equals the frame period and only the rate is set (up to 1 / readout)."""
    return _set("frame_transfer", on)


def set_shutter(mode):
    """Internal shutter 0 auto (the SDK adds both 50 ms transfer times to every frame), 1 open, 2 closed. start()
    opens it and stop() / disconnect close it, as the LabVIEW program did (owner 2026-10-30)."""
    return _set("shutter", mode)


def set_exposure(exposure_ms):
    """Exposure in ms; must not exceed the frame period. Returns the read-back (the SDK's real exposure)."""
    return _set("exposure_ms", exposure_ms)


def set_rate(rate_Hz):
    """Frame rate in Hz (kinetic cycle 1 / rate). A rate the camera cannot reach reads back lower -> DeviceError."""
    return _set("rate_Hz", rate_Hz)


def set_gain_mode(mode):
    """EM gain mode 0 = 8 bit DAC, 1 = 12 bit DAC, 2 = linear, 3 = real EM gain; the gain range follows the mode."""
    return _set("em_gain_mode", mode)


def set_gain(em_gain):
    """EM gain within the camera's range for the mode in force (gain above the range stays locked)."""
    return _set("em_gain", em_gain)


def set_temperature(temperature_C):
    """Cooling set point in deg C (integer) and cooler on. The sensor temperature is in settings()."""
    return _set("temperature_C", temperature_C)


def settings():
    """Read back: the five settings plus sensor_temperature_C, cooler status and acquiring."""
    svc = service("emccd")
    return svc.call(svc.require().settings, what="read settings")


def apply_preset(preset):
    """Apply {"name": str, and any of FIELDS} in the order gain mode, gain, exposure, rate, temperature; each is read
    back and verified (U15). Remembered and re-applied after a reconnect. Returns the read-back values."""
    extra = set(preset) - set(FIELDS) - {"name"}
    if extra or not isinstance(preset.get("name"), str):
        raise ValueError(f"emccd preset needs a 'name' and only the fields {FIELDS}; got {sorted(preset)}")
    svc = service("emccd")
    got = {k: _set(k, preset[k], preset.get("rate_Hz"), preset.get("exposure_ms")) for k in FIELDS if k in preset}
    svc.reapply = lambda: apply_preset(preset)
    svc.preset = dict(preset)
    events.log("preset", device="emccd", name=preset["name"], readback=got)
    return got


def exercise_shutter(cycles=100, pause_s=0.1):
    """Cycle the internal shutter open / closed `cycles` times, `pause_s` after each call (owner 2026-10-30: the
    blade was stiff after long disuse and freed up under cycling); stops at the first SDK error; the shutter is
    left closed. Returns {"calls_ok", "cycles", "stopped_at"}."""
    svc = service("emccd")
    r = svc.call(svc.require().cycle_shutter, cycles, pause_s, what=f"exercise shutter {cycles} x {pause_s} s",
                 timeout_s=2.0 * cycles * pause_s + 30.0)
    events.log("emccd_shutter_exercise", device="emccd", **r)
    return r


def start():
    """Shutter open, then the run-till-abort acquisition into the SDK's circular buffer (read it with read_new())."""
    svc = service("emccd")
    svc.call(svc.require().start_acquisition, what="start acquisition")


def stop():
    svc = service("emccd")
    svc.call(svc.require().stop_acquisition, what="stop acquisition")


def read_new():
    """(first, last, frames n x h x w uint16) not yet read, or None; a jump in first over the last read = loss.
    While api.acq runs the recorder reads the camera: this returns its newest frame once (for a display)."""
    rec = _rec
    if rec is not None:
        latest, rec.latest = rec.latest, None
        return latest
    svc = service("emccd")
    return svc.call(svc.require().read_new, what="read new frames")


_storage = {"mode": "full"}


def set_storage(mode="full", jai_map=None, size=15, first_full=20, every_full=100):
    """How the EMCCD frames go into the run files created from now on (owner 2026-11-21: "first frames whole, then
    the chosen pixels"). "full": every frame whole (decision 0006 item 6; the default). "boxes": per tracked bead a
    size x size box (odd, px) around its start position mapped to the EMCCD with `jai_map` (a mapping.load() map
    with a jai -> emccd transform), plus the first `first_full` frames and every `every_full`-th frame whole (0 =
    none) for the map check, drift and choosing spots later. The box is wide because which spot under a bead is its
    molecule is decided after the run (U25). Returns storage()."""
    global _storage
    if mode == "full":
        _storage = {"mode": "full"}
    elif mode == "boxes":
        from mtpy import mapping
        if not isinstance(jai_map, dict):
            raise SafetyRefused("emccd bead boxes need a JAI -> EMCCD map (mapping.load); none given")
        try:
            mapping.transform(jai_map, "jai", jai_map.get("reference", "emccd"))
        except (KeyError, TypeError) as e:
            raise SafetyRefused(f"emccd bead boxes: {e}") from None
        nums = (size, first_full, every_full)
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in nums) or size < 3 or size % 2 == 0 \
                or size > 255 or first_full < 0 or every_full < 0:
            raise SafetyRefused(f"emccd bead boxes: size {size!r} must be an odd integer 3..255, first_full "
                                f"{first_full!r} and every_full {every_full!r} integers >= 0")
        _storage = {"mode": "boxes", "size": size, "first_full": first_full, "every_full": every_full, "map": jai_map}
    else:
        raise SafetyRefused(f"emccd storage {mode!r} is not 'full' or 'boxes'")
    events.log("emccd_storage", device="emccd", **{k: v for k, v in _storage.items() if k != "map"},
               map_id=(jai_map or {}).get("id") if mode == "boxes" else None)
    return storage()


def storage():
    """The EMCCD storage for the next run file (set_storage); the map is included in full."""
    return dict(_storage)


class _Recorder:
    """Reads the EMCCD's new frames every `period_s` on its own thread while api.acq runs (never on the JAI frame
    path) and, while recording is on, hands them to the pipeline's sink. A frame number that does not follow the
    last one read is a loss (`emccd_frames_lost` event); a failed read is one `emccd_read_error` event per text."""

    def __init__(self, pipe, svc, period_s=0.02):
        self.pipe, self.svc, self.period_s = pipe, svc, period_s
        self.latest = None                      # (first, last, the newest frame as 1 x h x w) for a display
        self.frames_read = self.frames_recorded = self.frames_lost = 0
        self.error = None
        self._next, self._timing = None, None   # the frame number expected next; (exposure_s, period_s)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=contextvars.copy_context().run, args=(self._loop,),
                                        name="acq-emccd", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(self.period_s):
            try:
                self.read_once()
                self.error = None
            except MtpyError as e:
                msg = f"{type(e).__name__}: {e}"
                if msg != self.error:
                    self.error = msg
                    events.log("emccd_read_error", device="emccd", error=msg, **self.pipe.last_record())

    def read_once(self):
        dev = self.svc.device
        r = self.svc.call(dev.read_new, what="read new frames")
        if r is None:
            return
        t_read, jai = time.time(), self.pipe.last_record()
        first, last, frames = r
        if self._next is None or first < self._next:          # a new EMCCD acquisition: its numbers restart at 1
            s = self.svc.call(dev.settings, what="read settings")
            self._timing = (s["exposure_ms"] / 1000.0, 1.0 / s["rate_Hz"] if s.get("rate_Hz") else 0.0)
            self._offset = float("inf")
        elif first > self._next:
            self.frames_lost += first - self._next
            events.log("emccd_frames_lost", device="emccd", first=self._next, last=first - 1, **jai)
        self._next = last + 1
        # the frame clock: frame n ends at offset + n * cycle; a frame is never read before it exists, so the
        # smallest (read time - n * cycle) seen is the offset (the poll's delay only ever adds to it)
        self._offset = min(self._offset, t_read - last * self._timing[1])
        self.frames_read += len(frames)
        self.latest = (last, last, frames[-1:])
        if self.pipe.recording:
            self.frames_recorded += len(frames)
            self.pipe.forward_emccd({"first": first, "frames": frames, "t_read": t_read, "exposure_s": self._timing[0],
                                     "t_last": self._offset + last * self._timing[1],
                                     "period_s": self._timing[1], "jai_segment": jai.get("segment"),
                                     "jai_buffer": jai.get("buffer_number")})

    def stop(self):
        self._stop.set()
        self._thread.join(2.0)                  # a read stuck in the device keeps only this daemon thread

    def status(self):
        return {"frames_read": self.frames_read, "frames_recorded": self.frames_recorded,
                "frames_lost": self.frames_lost, "error": self.error}


_rec = None


def _acq_started(pipe):
    """api.acq: acquisition started - record the EMCCD beside it when one is connected."""
    global _rec
    svc = _services.get("emccd")
    if svc is not None and svc.connected:
        _rec = _Recorder(pipe, svc)


def _acq_stopping():
    """api.acq: before the pipeline stops - a last read, so the frames up to the stop reach the sink."""
    global _rec
    rec, _rec = _rec, None
    if rec is not None:
        rec.stop()
        try:
            rec.read_once()
        except MtpyError:
            pass
    return rec


def total_acquired():
    svc = service("emccd")
    return svc.call(svc.require().total_acquired, what="frames acquired")


def snap():
    """One frame (uint16 array h x w) from the EMCCD: the acquisition is started if it is not running."""
    svc = service("emccd")
    return svc.call(svc.require().snap, what="snap", timeout_s=15.0)


def catalogue():
    """The EMCCD's settings as a catalogue like api.camera.catalogue() (owner 2026-11-04: the same panel for both
    cameras): frame transfer, shutter, exposure, rate, EM gain mode and gain, temperature, with the ranges the device
    reports. The SDK is not attribute-based, so this is the program's table; a setting outside it is set by code."""
    svc = service("emccd")
    dev = svc.require()
    lim = svc.call(dev.limits, what="limits")
    gain = lim.get("em_gain") if isinstance(lim.get("em_gain"), (tuple, list)) else (0, 1000)
    temp = lim.get("temperature_C") if isinstance(lim.get("temperature_C"), (tuple, list)) else (-120, 20)
    rows = [
        {"name": "frame_transfer", "category": "Readout", "type": "enum", "values": [0, 1], "description": str(lim.get("frame_transfer", ""))},
        {"name": "shutter", "category": "Readout", "type": "enum", "values": [0, 1, 2], "description": str(lim.get("shutter", ""))},
        {"name": "exposure_ms", "category": "Acquisition", "type": "float", "min": 0.001, "max": 100000.0, "step": 1.0, "description": str(lim.get("exposure_ms", ""))},
        {"name": "rate_Hz", "category": "Acquisition", "type": "float", "min": 0.01, "max": 1000.0, "step": 1.0, "description": str(lim.get("rate_Hz", ""))},
        {"name": "em_gain_mode", "category": "Gain", "type": "enum", "values": [0, 1, 2, 3], "description": str(lim.get("em_gain_mode", ""))},
        {"name": "em_gain", "category": "Gain", "type": "int", "min": int(gain[0]), "max": int(gain[1]), "step": 1, "description": "EM gain in the mode's unit"},
        {"name": "temperature_C", "category": "Cooling", "type": "int", "min": int(temp[0]), "max": int(temp[1]), "step": 1, "description": "set-point; the cooler runs towards it"},
    ]
    for r in rows:
        r.update(access="rw", visibility="beginner")
    return rows


def get_attribute(name):
    return settings()[name]


_SETTERS = {"frame_transfer": lambda v: set_frame_transfer(int(v)), "shutter": lambda v: set_shutter(int(v)),
            "exposure_ms": set_exposure, "rate_Hz": set_rate, "em_gain_mode": lambda v: set_gain_mode(int(v)),
            "em_gain": lambda v: set_gain(int(v)), "temperature_C": lambda v: set_temperature(int(v))}


def set_attribute(name, value, confirm=False):
    """Write one catalogue entry through its setter (each reads back); confirm is accepted for the panel's sake."""
    if name not in _SETTERS:
        raise ValueError(f"emccd has no attribute {name!r}; the catalogue has {sorted(_SETTERS)}")
    return _SETTERS[name](value)
