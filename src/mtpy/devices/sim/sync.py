"""Simulated Arduino frame divider (docs/manuals/arduino-sync.md, decision 0005) and lasers (manual on / off, U24).

The divider counts JAI exposure pulses itself (`on_jai_frame`, wired to the camera's exposure line by `make_rig`);
it never uses the camera's buffer number to decide anything. Every N of ITS OWN pulses it triggers one EMCCD frame m
and records which lights its gating outputs had on for that frame.

Count reset rule (the one rule of this simulator, review l2s-wp2-r1): the pulse count p starts at 0 on `open()`
(opening the port auto-resets the board) and on every `set_ratio(n)` (configuring N starts a new count). Nothing else
resets it - in particular NOT a camera acquisition stop / start, whose buffer numbers restart at 0 while the board
keeps counting. Pulse p (0-based since the last reset) triggers EMCCD frame m = p // N when p % N == 0, so frame m
covers the divider's pulses [mN, (m+1)N). Each record is (m, JAI buffer number seen with the triggering pulse,
lights on); the buffer number is only recorded, for matching frames afterwards.
Nothing is timed by the PC. Not imitated yet: the k-wide pulse, the count reset when JAI pulses stop (timeout), the
32-bit count and the watchdog (firmware not designed yet).
"""
import collections
import threading
from typing import ClassVar

from ..base import IMMEDIATE, Device


class SimLight(Device):
    """Lasers 532 and 637 nm, manual on / off; all off after open (U24: lights closed outside recording)."""
    name, model = "light", "lasers 532 / 637 nm"
    hint = "check the laser power supply, its interlock key and the cable"
    quantities = ("laser_power_mW.532", "laser_power_mW.637")
    settings_kinds: ClassVar[dict] = {"532": (IMMEDIATE, False), "637": (IMMEDIATE, False)}
    LASERS = ("532", "637")

    def __init__(self):
        self._on = dict.fromkeys(self.LASERS, False)
        self._lock, self.is_open, self.fault = threading.Lock(), False, None

    def _io(self):
        if self.fault == "no_reply":
            raise TimeoutError("no reply")
        if not self.is_open:
            raise ConnectionError("port not open")

    def open(self):
        self._on = dict.fromkeys(self.LASERS, False)
        self.is_open = True

    def close(self):
        self.is_open = False

    def identity(self):
        self._io()
        return {"model": f"simulator of {self.model}", "serial": "SIM", "firmware": "sim", "port": "sim",
                "driver": "mtpy.devices.sim"}

    def settings(self):
        self._io()
        return self.outputs_dict()

    def outputs_dict(self):
        with self._lock:
            return dict(self._on)

    def set(self, laser, on):
        self._io()
        with self._lock:
            self._on[laser] = bool(on)

    def get(self, laser):
        self._io()
        with self._lock:
            return self._on[laser]


class SimArduino(Device):
    """Frame divider: ratio N JAI frames per EMCCD frame; `pulses` counts its own JAI pulses since the last reset
    (open or set_ratio); `frames` records (m, JAI buffer at the triggering pulse, lights on)."""
    name, model = "arduino", "Arduino UNO frame divider"
    hint = "check the Arduino USB cable (CH340); never reopen its port during a run (it resets the count)"
    settings_kinds: ClassVar[dict] = {"ratio": (IMMEDIATE, True)}
    RATIO_MAX = 65536                      # Timer1 TOP is 16 bits (ICR1 = N - 1)

    def __init__(self, light=None):
        self.light, self.ratio, self.pulses = light, 1, 0
        self.frames = collections.deque(maxlen=1_000_000)
        self._lock, self.is_open, self.fault = threading.Lock(), False, None

    def _io(self):
        if self.fault == "no_reply":
            raise TimeoutError("no reply")
        if not self.is_open:
            raise ConnectionError("port not open")

    def open(self):
        with self._lock:                   # opening the port auto-resets the board: count and ratio start over
            self.ratio, self.pulses = 1, 0
            self.frames.clear()
        self.is_open = True

    def close(self):
        self.is_open = False

    def identity(self):
        self._io()
        return {"model": f"simulator of {self.model}", "serial": "none (CH340; asked from the firmware)",
                "firmware": "sim", "port": "sim", "driver": "mtpy.devices.sim"}

    def settings(self):
        self._io()
        return {"ratio": self.ratio}

    def limits(self):
        return {"ratio": (1, self.RATIO_MAX)}

    def set_ratio(self, n):
        self._io()
        with self._lock:                   # configuring N starts a new count (the reset rule above)
            self.ratio, self.pulses = int(n), 0

    def get_ratio(self):
        self._io()
        return self.ratio

    def on_jai_frame(self, buffer_number):
        """One JAI exposure pulse (hardware input D5); counted by the board itself, buffer_number only recorded."""
        with self._lock:
            n, p = self.ratio, self.pulses
            self.pulses = p + 1
            if p % n == 0:
                on = self.light.outputs_dict() if self.light else {}
                self.frames.append((p // n, buffer_number, tuple(k for k, v in on.items() if v)))
