"""Simulated motion controllers: PI C-863 magnet (mm), Autonics PMC-2HS rotor (turns), ASI Tiger stage x/y (mm) and
focus z (um). Behaviour copied from docs/manuals/ where it matters for the program:
- moves take time (a speed limit) and end at the controller's limit switches;
- PI: a target outside the soft limits TMN / TMX is rejected (ERR 7) and nothing moves; position survives a reopen;
- ASI: at a firmware limit (SL / SU) the motor just stops, the command is NOT rejected (asi-tiger.md pitfall 4), so
  only the read-back shows it; positions in 0.1 um units;
- rotor: 500 pulses per turn, no limit switch, only the 24-bit counter range.
Fault injection for tests: `fault = "no_reply"` (every command raises TimeoutError) or `"nan"` (positions read NaN).
"""
import math
import random
import threading
import time
from typing import ClassVar

from ..base import IMMEDIATE, Device


class Axis:
    """One axis that moves toward its target at `speed` (units/s) and stops at its limit switches `travel`."""

    def __init__(self, pos, speed, travel, resolution, noise=0.0):
        self._lock = threading.Lock()
        self._p0 = self._target = float(pos)
        self._t0 = time.monotonic()
        self.speed, self.travel, self.resolution, self.noise = speed, travel, resolution, noise

    def _now(self):
        d = self._target - self._p0
        return self._p0 + math.copysign(min(abs(d), self.speed * (time.monotonic() - self._t0)), d)

    def move_to(self, target, speed=None):
        with self._lock:
            self._p0, self._t0 = self._now(), time.monotonic()
            if speed is not None:
                self.speed = speed
            self._target = min(max(target, self.travel[0]), self.travel[1])   # a limit switch stops it there

    def stop(self):
        with self._lock:
            self._p0 = self._target = self._now()
            self._t0 = time.monotonic()

    def moving(self):
        with self._lock:
            return self._now() != self._target

    def position(self):
        with self._lock:
            p = self._now()
        if self.noise:
            p += random.gauss(0.0, self.noise)
        return round(p / self.resolution) * self.resolution


class SimMotor(Device):
    """A one-axis controller. Subclasses set the model, units and limits."""
    model, unit, relative = "motor", "", False
    settings_kinds: ClassVar[dict] = {"position": (IMMEDIATE, False), "speed": (IMMEDIATE, False)}

    def __init__(self, axis, tol):
        self.axis, self.tol, self.fault, self.is_open = axis, tol, None, False

    def _io(self):
        if self.fault == "no_reply":
            raise TimeoutError("no reply")
        if not self.is_open:
            raise ConnectionError("port not open")

    def open(self):
        if self.fault == "no_reply":
            raise TimeoutError("no reply")
        self.is_open = True

    def close(self):
        self.is_open = False

    def identity(self):
        self._io()
        return {"model": f"simulator of {self.model}", "serial": "SIM", "firmware": "sim", "port": "sim",
                "driver": "mtpy.devices.sim"}

    def settings(self):
        return {"position": self.position(), "speed": self.axis.speed, "unit": self.unit}

    def limits(self):
        return {"limit_switches": self.axis.travel, "unit": self.unit}

    def probe(self):
        return {"position": self.position()}

    def session_origin(self):
        return self.position() if self.relative else None

    def move_to(self, target, speed=None):
        self._io()
        self.axis.move_to(target, speed)

    def moving(self):
        self._io()
        return self.axis.moving()

    def speed(self):
        """The speed the controller applies to the next move when none is given (PI `VEL?`), units/s."""
        self._io()
        return self.axis.speed

    def position(self):
        self._io()
        return float("nan") if self.fault == "nan" else self.axis.position()

    def stop(self):
        self.axis.stop()


class SimMagnet(SimMotor):
    """PI C-863.11 magnet: 0 mm = top (farthest from the sample), larger = more force; soft limits TMN/TMX from the
    profile's magnet_position_mm at open, as the real open writes them; hard travel 0 .. 40.94 mm (Max Trans Pos.vi)."""
    name, model, unit = "magnet", "PI C-863.11 (magnet)", "mm"
    hint = "check the PI controller power, servo (SVO) and the USB cable"
    quantities = ("magnet_position_mm", "magnet_force_pN", "magnet_speed_mm_s")

    STALL_ERROR = -1024             # PI: "position error too large, servo switched off" (decision 0019)
    # Device-layer flag (decision 0019 item 5): after a -1024 the position is still valid, so the return to 0 mm needs
    # no reference move first. NOT confirmed on the rig's C-863 yet (open rig item, docs/design/api.md); a real
    # backend sets it from that check. False -> the API does not attempt the return (no reference path exists).
    position_valid_after_stall = True

    def __init__(self, pos=0.0, speed=10.0, soft=(0.0, 39.0)):
        super().__init__(Axis(pos, speed, (0.0, 40.94), 1e-5, noise=2e-4), tol=0.01)
        self.soft = soft
        self.err, self.servo = 0, True
        self._stall_at = None          # armed stall position (inject_stall), or None
        self._stall_pending = False    # a move was cut at the stall position; the stall fires when it arrives
        self.fail_servo_on = False     # TEST ONLY: re-enabling the servo fails (it stays off)

    def open(self):
        super().open()
        # as the real PI open writes the profile's TMN/TMX (pi.open): the simulator followed a fixed 0..39 until
        # profile v9 (40.9 mm, 2026-10-31) showed it
        from mtpy.api import safety
        lim = safety.profile()["limits"]["magnet_position_mm"]
        if lim["min"] is not None and lim["max"] is not None:
            self.soft = (float(lim["min"]), float(lim["max"]))

    def limits(self):
        return {**super().limits(), "soft_limits_TMN_TMX": self.soft}

    # --- stall injection for tests (decision 0019) -----------------------------------------------------------------
    def inject_stall(self, at_mm=None):
        """TEST ONLY. at_mm None: stall now, where the magnet is. Else: the next move that passes at_mm stops there,
        and then the controller reports -1024 with the servo switched off."""
        if at_mm is None:
            self._stall_now()
        else:
            self._stall_at = float(at_mm)

    def _stall_now(self):
        self.axis.stop()
        self.servo, self.err, self._stall_at, self._stall_pending = False, self.STALL_ERROR, None, False

    def _update(self):
        if self._stall_pending and not self.axis.moving():
            self._stall_now()

    def move_to(self, target, speed=None):
        self._io()
        if not self.soft[0] <= target <= self.soft[1]:
            raise ValueError(f"PI ERR 7: target {target:g} mm outside the soft limits TMN/TMX {self.soft} mm")
        self._update()
        if not self.servo:
            raise ValueError("PI ERR 5: move attempted with the servo off")
        s, p = self._stall_at, self.axis.position()
        if s is not None and min(p, target) <= s <= max(p, target) and abs(s - p) > 1e-9:
            self.axis.move_to(s, speed)        # the motor is blocked at s
            self._stall_pending = True
        else:
            self.axis.move_to(target, speed)

    def moving(self):
        self._io()
        self._update()
        return self.axis.moving()

    def position(self):
        self._io()
        self._update()
        return super().position()

    def error(self):
        """PI `ERR?`: the last controller error code, cleared by the read (0 = none)."""
        self._io()
        self._update()
        e, self.err = self.err, 0
        return e

    def set_servo(self, on):
        """PI `SVO 1 <on>`."""
        self._io()
        if not (on and self.fail_servo_on):
            self.servo = bool(on)

    def servo_on(self):
        """PI `SVO? 1`."""
        self._io()
        return self.servo

    def stop(self):
        self._stall_pending = False
        super().stop()


class SimRotor(SimMotor):
    """Autonics PMC-2HS rotor: 500 pulses per turn, signed counter of 24 bits, no limit switch."""
    name, model, unit, relative = "rotor", "Autonics PMC-2HS (rotor)", "turns", True
    hint = "check the rotor driver power and the FTDI cable (serial AI03Q9JZA)"
    quantities = ("rotor_turns", "rotor_speed_turns_s")

    def __init__(self, turns=0.0, speed=5.0):
        super().__init__(Axis(turns, speed, (-8388608 / 500, 8388607 / 500), 1 / 500), tol=0.6 / 500)


class SimFocus(SimMotor):
    """ASI Tiger Z (focus) in um, 0.1 um units; no envelope declared on the rig, travel here is a sim value."""
    name, model, unit, relative = "focus", "ASI Tiger Z (focus)", "um", True
    hint = "check the ASI Tiger controller power and its serial cable"
    quantities = ("focus_z_um",)

    def __init__(self, z=2.9, speed=1000.0, travel=(-5000.0, 5000.0)):
        super().__init__(Axis(z, speed, travel, 0.1), tol=0.15)


class SimStage(Device):
    """ASI Tiger X/Y in mm (0.1 um units). SL/SU are firmware limits: the motor stops there, the move is not
    rejected. Defaults are the released SL/SU (-500 / +500 mm) and the 2026-09-18 position."""
    name, model, relative = "stage", "ASI Tiger X/Y (stage)", True
    hint = "check the ASI Tiger controller power and its serial cable"
    quantities = ("stage_x_mm", "stage_y_mm")
    settings_kinds: ClassVar[dict] = {"position": (IMMEDIATE, False)}
    tol = 0.0005

    def __init__(self, x=-1.8475, y=-2.7744, speed=5.0, sl=(-500.0, -500.0), su=(500.0, 500.0)):
        self.x = SimMotor(Axis(x, speed, (sl[0], su[0]), 1e-4), self.tol)
        self.y = SimMotor(Axis(y, speed, (sl[1], su[1]), 1e-4), self.tol)
        self.fault = None

    def _axes(self):
        for a in (self.x, self.y):
            a.fault = self.fault
        return self.x, self.y

    def open(self):
        for a in self._axes():
            a.open()

    def close(self):
        for a in self._axes():
            a.close()

    def identity(self):
        return {**self._axes()[0].identity(), "model": f"simulator of {self.model}"}

    def settings(self):
        return {"position": self.position(), "unit": "mm"}

    def limits(self):
        return {"SL": (self.x.axis.travel[0], self.y.axis.travel[0]),
                "SU": (self.x.axis.travel[1], self.y.axis.travel[1]), "unit": "mm"}

    def probe(self):
        return {"position": self.position()}

    def session_origin(self):
        return self.position()

    def move_to(self, xy, speed=None):
        x, y = self._axes()
        x.move_to(xy[0], speed)
        y.move_to(xy[1], speed)

    def moving(self):
        x, y = self._axes()
        return x.moving() or y.moving()

    def position(self):
        x, y = self._axes()
        return (x.position(), y.position())

    def stop(self):
        self.x.stop()
        self.y.stop()
