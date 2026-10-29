"""The real ASI Tiger (COM4) as two `Device`s on one port: `AsiStage` (X/Y, mm) and `AsiFocus` (Z, um); the ASI
part of the motion gate (docs/design/motion-gate.md). Same interfaces as `sim.motors.SimStage` / `SimFocus`.

Units: motion commands and `W` replies are in 0.1 um (1 mm = 10 000 units); SL / SU are absolute mm and persist in
the controller. Session: the stage's open() writes SL/SU X Y = position +- the profile's window and reads them back;
close() writes the release values +-500 mm. Z: SL/SU Z are READ at open and never written (decision 0021); a Z move
must lie inside them. Every move re-reads SL/SU in this port session first and sends exactly one single-axis 'M'.
"""
from mtpy.api import safety

from . import gate
from .base import IMMEDIATE, Device
from .gate import Line

PORT, BAUD = "COM4", 115200
UNIT_MM = 1e-4                       # one controller unit = 0.1 um
RELEASE = 500.0                      # mm, V6 motor_limits.json asi.release
TOL = 0.001                          # SL/SU readback tolerance, mm
_shared = {}                         # port name -> Line: the stage and the focus share COM4


def _line(name):
    if name not in _shared:
        _shared[name] = Line.open(name, BAUD, b"\r", b"\r\n", 0.8)
    return _shared[name]


def _num(reply, key):
    """':A X=-18475 Y=-27744' / ':A -18475' -> float for `key` ('X', 'Y', 'Z' or '' for the bare :A form)."""
    if key:
        head = reply.split(key + "=", 1)
        if len(head) < 2:
            return None
        s = head[1].split()[0] if head[1].split() else ""
    else:
        parts = reply.split()
        s = parts[1] if len(parts) > 1 and parts[0] == ":A" else ""
    try:
        return float(s)
    except ValueError:
        return None


class AsiStage(Device):
    name, model = "stage", "ASI Tiger X/Y (stage)"
    hint = "check the ASI Tiger controller power and its serial cable"
    quantities = ("stage_x_mm", "stage_y_mm")
    settings_kinds = {"position": (IMMEDIATE, False)}      # noqa: RUF012 - class contract
    tol = 0.0005

    def __init__(self, port=None, line=None):
        self.line, self.port_name = line, port or PORT
        self.sl = self.su = None             # session SL/SU {X, Y} in mm

    def _io(self):
        if self.line is None:
            raise ConnectionError("ASI port not open")
        return self.line

    def _where(self, L, axis):
        v = _num(L.ask(f"W {axis}"), "")
        if v is None:
            raise ConnectionError(f"ASI W {axis} gave no number")
        return v

    def _read_limits(self, L):
        sl, su = L.ask("SL X? Y?"), L.ask("SU X? Y?")
        out = {k: (_num(sl, k), _num(su, k)) for k in ("X", "Y")}
        if any(v is None for pair in out.values() for v in pair):
            raise ConnectionError(f"ASI SL/SU readback unreadable: {sl!r} / {su!r}")
        return out

    def _write_limits(self, L, sl, su):
        L.ask(f"SL X={sl['X']:.4f} Y={sl['Y']:.4f}")
        L.ask(f"SU X={su['X']:.4f} Y={su['Y']:.4f}")
        rb = self._read_limits(L)
        for k in ("X", "Y"):
            if abs(rb[k][0] - sl[k]) > TOL or abs(rb[k][1] - su[k]) > TOL:
                raise ConnectionError(f"ASI limits read back {rb}, wanted SL {sl} SU {su}")

    def open(self):
        gate.permitted("the ASI stage")
        lims = safety.profile()["limits"]
        half = {}
        for k, q in (("X", "stage_x_mm"), ("Y", "stage_y_mm")):
            e = lims[q]
            if not e["verified"] or e["relative_to"] != "session_start" or e["min"] is None or e["max"] is None:
                raise PermissionError(f"the profile's {q} is not a verified session-relative window: no ASI session")
            half[k] = (float(e["min"]), float(e["max"]))
        L = self.line or _line(self.port_name)
        pos = {k: self._where(L, k) * UNIT_MM for k in ("X", "Y")}
        sl = {k: pos[k] + half[k][0] for k in half}
        su = {k: pos[k] + half[k][1] for k in half}
        self._write_limits(L, sl, su)
        self.line, self.sl, self.su = L, sl, su

    def close(self):
        L = self.line
        if L is None:
            return
        try:
            rel = {"X": RELEASE, "Y": RELEASE}
            self._write_limits(L, {"X": -RELEASE, "Y": -RELEASE}, rel)
        finally:
            self.line, self.sl, self.su = None, None, None

    def _checked_move(self, L, axis, target_units):
        gate.permitted("an ASI move")
        rb = self._read_limits(L)
        for k in ("X", "Y"):
            if abs(rb[k][0] - self.sl[k]) > TOL or abs(rb[k][1] - self.su[k]) > TOL:
                raise ValueError(f"ASI SL/SU {rb} are not the session's SL {self.sl} SU {self.su}")
        lo, hi = self.sl[axis] / UNIT_MM, self.su[axis] / UNIT_MM
        if not lo <= target_units <= hi:
            raise ValueError(f"ASI target {axis}={target_units:.0f} outside the controller window {lo:.0f}..{hi:.0f}")
        reply = L.ask(f"M {axis}={target_units:.0f}")
        if not reply.startswith(":A"):
            raise ValueError(f"ASI M {axis}: reply {reply!r}")

    def identity(self):
        L = self._io()
        return {"model": self.model, "serial": "", "firmware": L.ask("V").replace(":A", "").strip(),
                "port": self.port_name, "driver": "mtpy.devices.asi (Tiger ASCII, pyserial)"}

    def settings(self):
        return {"position": self.position(), "unit": "mm"}

    def limits(self):
        rb = self._read_limits(self._io())
        return {"SL": (rb["X"][0], rb["Y"][0]), "SU": (rb["X"][1], rb["Y"][1]), "unit": "mm"}

    def probe(self):
        return {"position": self.position()}

    def session_origin(self):
        return self.position()

    def move_to(self, xy, speed=None):
        L = self._io()
        for axis, v in zip("XY", xy):
            self._checked_move(L, axis, round(float(v) / UNIT_MM))

    def moving(self):
        L = self._io()
        x, y = self._where(L, "X"), self._where(L, "Y")
        for axis, v in (("X", x), ("Y", y)):
            if v * UNIT_MM < self.sl[axis] - 0.05 or v * UNIT_MM > self.su[axis] + 0.05:
                L.say("\\")                          # watchdog halt
                raise ValueError(f"ASI {axis}={v} outside SL/SU; halt sent")
        return "B" in L.ask("/")

    def position(self):
        L = self._io()
        return (self._where(L, "X") * UNIT_MM, self._where(L, "Y") * UNIT_MM)

    def stop(self):
        if self.line is not None:
            self.line.say("\\")


class AsiFocus(Device):
    name, model, unit = "focus", "ASI Tiger Z (focus)", "um"
    hint = AsiStage.hint
    quantities = ("focus_z_um",)
    settings_kinds = {"position": (IMMEDIATE, False), "speed": (IMMEDIATE, False)}   # noqa: RUF012
    tol = 0.15

    def __init__(self, port=None, line=None):
        self.line, self.port_name = line, port or PORT
        self.window = None                   # (lo, hi) in controller units, read at open

    def _io(self):
        if self.line is None:
            raise ConnectionError("ASI port not open")
        return self.line

    def _zlimits(self, L):
        sl, su = _num(L.ask("SL Z?"), "Z"), _num(L.ask("SU Z?"), "Z")
        if sl is None or su is None or not sl < su or abs(sl) > 0.1 or abs(su) > 0.1:
            raise ConnectionError(f"ASI SL/SU Z implausible: {sl} / {su} mm (decision 0021 window)")
        return sl, su

    def open(self):
        gate.permitted("the ASI focus")
        L = self.line or _line(self.port_name)
        sl, su = self._zlimits(L)
        self.line, self.window = L, (sl / UNIT_MM, su / UNIT_MM)

    def close(self):
        L = self.line
        if L is None:
            return
        try:
            sl, su = self._zlimits(L)
            if abs(sl / UNIT_MM - self.window[0]) > 5 or abs(su / UNIT_MM - self.window[1]) > 5:
                raise ConnectionError(f"ASI SL/SU Z changed during the session: {sl} / {su} mm")
        finally:
            self.line, self.window = None, None

    def _z_units(self, L):
        v = _num(L.ask("W Z"), "")
        if v is None:
            raise ConnectionError("ASI W Z gave no number")
        return v

    def identity(self):
        return {**AsiStage.identity(self), "model": self.model}

    def settings(self):
        return {"position": self.position(), "speed": self.speed(), "unit": self.unit}

    def limits(self):
        sl, su = self._zlimits(self._io())
        return {"SL_SU_Z_mm": (sl, su), "unit": "mm"}

    def probe(self):
        return {"position": self.position()}

    def session_origin(self):
        return self.position()

    def move_to(self, z_um, speed=None):
        L = self._io()
        gate.permitted("an ASI Z move")
        sl, su = self._zlimits(L)
        lo, hi = sl / UNIT_MM, su / UNIT_MM
        if abs(lo - self.window[0]) > 5 or abs(hi - self.window[1]) > 5:
            raise ValueError(f"ASI SL/SU Z {sl}/{su} differ from the window read at open; reconnect")
        target = round(float(z_um) * 10.0, 3)                       # um -> 0.1 um units, 3 decimals (owner 2026-10-27)
        if not lo <= target <= hi:
            raise ValueError(f"ASI Z target {target} outside the controller window {lo:.0f}..{hi:.0f}")
        reply = L.ask(f"M Z={target:.3f}".rstrip("0").rstrip("."))
        if not reply.startswith(":A"):
            raise ValueError(f"ASI M Z: reply {reply!r}")

    def moving(self):
        L = self._io()
        z = self._z_units(L)
        if z < self.window[0] - 5 or z > self.window[1] + 5:
            L.say("\\")
            raise ValueError(f"ASI Z={z} outside SL/SU Z; halt sent")
        return "B" in L.ask("/")

    def speed(self):
        return float("nan")                  # not read: the API never checks a focus speed

    def position(self):
        return self._z_units(self._io()) / 10.0

    def stop(self):
        if self.line is not None:
            self.line.say("\\")
