"""The real Autonics PMC-2HS rotor (X axis, COM5 9600 8N1) as a `Device`; the rotor part of the motion gate
(docs/design/motion-gate.md; V6 docs/rotor-protocol.md). Same interface as `sim.motors.SimRotor` (turns).

Protocol: ASCII, CR-terminated; writes have NO reply; `POS` -> 'POS hhhhhhhh,hhhhhhhh' (8 hex digits per axis, two's
complement), 500 pulses per turn. The envelope is RELATIVE and enforced here, not by the controller (its soft limit
is EEPROM-only and its addresses unconfirmed): the window is the position read at open +- the profile's turns.
Nothing is ever written to the controller except 'SPD <n>' (<= MAX_SPD), 'PAB <pulses>' (X only) and 'STO X'.
"""
import time

from mtpy.api import safety

from . import gate
from .base import IMMEDIATE, Device
from .gate import Line

PORT, BAUD = "COM5", 9600
PULSES_PER_TURN = 500
MAX_SPD = 100                        # the main VI's 'Rot Speed' default; pps = SPD x the controller's multiplier


def _pos(reply):
    """'POS FFFFFFF6,00000000' -> -10 (pulses of the X axis), None when unreadable."""
    parts = reply.split()
    if len(parts) != 2 or parts[0] != "POS":
        return None
    h = parts[1].split(",")[0]
    if len(h) != 8:
        return None
    try:
        v = int(h, 16)
    except ValueError:
        return None
    return v - (1 << 32) if v >= (1 << 31) else v


class AutonicsRotor(Device):
    name, model, unit, relative = "rotor", "Autonics PMC-2HS (rotor)", "turns", True
    hint = "check the rotor driver power and the FTDI cable (serial AI03Q9JZA)"
    quantities = ("rotor_turns", "rotor_speed_turns_s")
    settings_kinds = {"position": (IMMEDIATE, False), "speed": (IMMEDIATE, False)}   # noqa: RUF012
    tol = 0.6 / PULSES_PER_TURN

    def __init__(self, port=None, line=None):
        self.line, self.port_name = line, port or PORT
        self.window = None                   # (lo, hi) pulses

    def _io(self):
        if self.line is None:
            raise ConnectionError("rotor port not open")
        return self.line

    def _read(self, L):
        p = _pos(L.ask("POS"))
        if p is None:
            raise ConnectionError("rotor POS gave no readable reply")
        return p

    def open(self):
        gate.permitted("the rotor")
        e = safety.profile()["limits"]["rotor_turns"]
        if e["relative_to"] != "session_start" or e["min"] is None or e["max"] is None:
            raise PermissionError("the profile's rotor_turns is not a session-relative window: no rotor session")
        L = self.line or Line.open(self.port_name, BAUD, b"\r", b"\r", 1.5)
        L.ask("POS")                                     # the first read after opening times out (V6 note)
        time.sleep(0.2)
        p = self._read(L)
        self.line = L
        self.window = (p + round(float(e["min"]) * PULSES_PER_TURN),
                       p + round(float(e["max"]) * PULSES_PER_TURN))

    def close(self):
        if self.line is not None:
            self.line.close()
        self.line, self.window = None, None

    def identity(self):
        L = self._io()
        return {"model": self.model, "serial": "", "firmware": L.ask("VER"), "port": self.port_name,
                "driver": "mtpy.devices.autonics (PMC-2HS ASCII, pyserial)"}

    def settings(self):
        return {"position": self.position(), "speed": self.speed(), "unit": self.unit}

    def limits(self):
        return {"window_pulses": self.window, "pulses_per_turn": PULSES_PER_TURN, "unit": self.unit}

    def probe(self):
        return {"position": self.position()}

    def session_origin(self):
        return self.position()

    def move_to(self, turns, speed=None):
        L = self._io()
        gate.permitted("a rotor move")
        spd = MAX_SPD if speed is None else round(float(speed) * PULSES_PER_TURN / 10.0)   # shortcut: multiplier assumed 10, upgrade when read
        if not 1 <= spd <= MAX_SPD:
            raise ValueError(f"rotor SPD {spd} outside 1..{MAX_SPD}")
        p1 = self._read(L)
        time.sleep(0.15)
        p2 = self._read(L)
        if p1 != p2:
            raise ValueError(f"rotor is moving ({p1} -> {p2}); no new move")
        target = round(float(turns) * PULSES_PER_TURN)
        lo, hi = self.window
        if not lo <= target <= hi:
            raise ValueError(f"rotor target {target} pulses outside the session window {lo}..{hi}")
        L.say(f"SPD {spd}")
        time.sleep(0.1)
        L.say(f"PAB {target}")

    def moving(self):
        L = self._io()
        p1 = self._read(L)
        lo, hi = self.window
        if p1 < lo - 25 or p1 > hi + 25:
            L.say("STO X")
            raise ValueError(f"rotor POS {p1} outside the window; STO sent")
        time.sleep(0.15)
        return self._read(L) != p1

    def speed(self):
        r = self._io().ask("SPD")
        try:
            return int(r.split()[1].split(",")[0]) * 10.0 / PULSES_PER_TURN
        except (IndexError, ValueError):
            return float("nan")

    def position(self):
        return self._read(self._io()) / PULSES_PER_TURN

    def stop(self):
        if self.line is not None:
            self.line.say("STO X")
