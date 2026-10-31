"""The real PI C-863.11 magnet axis (GCS over COM3) as a `Device`; the PI part of the motion gate
(docs/design/motion-gate.md). Same interface as `sim.motors.SimMagnet`, so the API cannot tell them apart.

Session (RULES.md 3, after V6 motor_send_pi.ps1): open() = soft limits TMN / TMX written (RAM, never WPA), read
back; servo on, referencing on, a real FNL reference move to the negative limit switch, POS 0, a 2 mm commanded-vs-
readback verify; close() = MOV 1 0 verified while the limits are still set, then the release limits 0..52 written
and read back. Every move re-reads the limits in this port session first and sends exactly one 'MOV 1 <mm>'.
"""
import time

from mtpy.api import safety

from . import gate
from .base import IMMEDIATE, Device
from .gate import Line

PORT, BAUD = "COM3", 115200
RELEASE_LO, RELEASE_HI = 0.0, 52.0         # controller geometry (TMX 52 = full travel), V6 motor_limits.json
TOL = 0.001                                # limit readback tolerance, mm
VERIFY_TOL = 0.05                          # commanded vs readback after referencing, mm
HOME_TOL = 0.01                            # magnet at 0 mm before the release
REF_ATTEMPTS = 3


def _num(reply):
    """'1=39.00000' / '1 0X15=39.00000' / '7' -> float, None when there is no number."""
    s = reply.rsplit("=", 1)[-1].strip() if reply else ""
    try:
        return float(s)
    except ValueError:
        return None


class PiMagnet(Device):
    name, model, unit = "magnet", "PI C-863.11 (magnet)", "mm"
    hint = "check the PI controller power, servo (SVO) and the USB cable"
    quantities = ("magnet_position_mm", "magnet_force_pN", "magnet_speed_mm_s")
    settings_kinds = {"position": (IMMEDIATE, False), "speed": (IMMEDIATE, False)}   # noqa: RUF012 - class contract
    tol = 0.01
    open_timeout_s = 420.0                   # 3 reference attempts of up to 120 s each
    STALL_ERROR = -1024
    position_valid_after_stall = True        # open rig item: not confirmed on this C-863 (api.md)

    def __init__(self, port=None, line=None):
        self.line = line                     # tests inject a Line over a fake controller
        self.port_name = port or PORT
        self.lo, self.hi = None, None        # the session limits once set

    def _io(self):
        if self.line is None:
            raise ConnectionError("PI port not open")
        return self.line

    def _limits(self, L):
        tmn, tmx = _num(L.ask("TMN?")), _num(L.ask("TMX?"))
        if tmn is None or tmx is None:
            raise ConnectionError("PI TMN?/TMX? gave no number")
        return tmn, tmx

    def _write_limits(self, L, lo, hi):
        L.say(f"SPA 1 0x15 {hi:g}")
        time.sleep(0.25)
        L.say(f"SPA 1 0x30 {lo:g}")
        time.sleep(0.25)
        L.ask("ERR?")
        tmn, tmx = self._limits(L)
        if abs(tmn - lo) > TOL or abs(tmx - hi) > TOL:
            raise ConnectionError(f"PI limits read back TMN {tmn} / TMX {tmx}, wanted {lo:g} / {hi:g}")
        return tmn, tmx

    def _wait(self, L, cond, timeout_s, every_s=0.3):
        t_end = time.monotonic() + timeout_s
        while time.monotonic() < t_end:
            time.sleep(every_s)
            if cond():
                return True
        return False

    def _reference(self, L):
        """SVO 1 1, RON 1 1, FNL 1 -> FRF? 1 and ONT? 1 and POS 0; then MOV 2 / MOV 0 each within VERIFY_TOL."""
        L.say("SVO 1 1")
        time.sleep(0.3)
        L.say("RON 1 1")
        time.sleep(0.3)
        L.say("FNL 1")
        if not self._wait(L, lambda: _num(L.ask("FRF?")) == 1 and _num(L.ask("ONT?")) == 1, 120, 0.5):
            raise ConnectionError("PI reference move (FNL 1) did not complete in 120 s")
        p = _num(L.ask("POS?"))
        if p is None or abs(p) > TOL:
            raise ConnectionError(f"PI after FNL the counter reads {p}, not 0")
        for tgt in (2.0, 0.0):
            L.say(f"MOV 1 {tgt:g}")
            self._wait(L, lambda: _num(L.ask("ONT?")) == 1, 20)
            pv, err = _num(L.ask("POS?")), L.ask("ERR?")
            if pv is None or abs(pv - tgt) > VERIFY_TOL or _num(err) != 0:
                raise ConnectionError(f"PI verify: commanded {tgt:g} read back {pv} ERR {err}")

    def open(self):
        gate.permitted("the PI magnet")
        lim = safety.profile()["limits"]["magnet_position_mm"]
        if not lim["verified"] or lim["min"] is None or lim["max"] is None:
            raise PermissionError("the profile's magnet_position_mm limit is unset or unverified: no PI session")
        lo, hi = float(lim["min"]), float(lim["max"])
        L = self.line or Line.open(self.port_name, BAUD, b"\n", b"\n", 0.6)
        try:
            last = None
            for _ in range(REF_ATTEMPTS):
                try:
                    self._write_limits(L, lo, hi)
                    self._reference(L)
                    tmn, tmx = self._limits(L)               # read only: an SPA write un-references the axis (FRF 0)
                    if abs(tmn - lo) > TOL or abs(tmx - hi) > TOL:
                        raise ConnectionError(f"PI limits {tmn} / {tmx} did not survive the reference move")
                    break
                except ConnectionError as e:
                    last = e
                    time.sleep(2)
            else:
                raise ConnectionError(f"PI session start failed {REF_ATTEMPTS} times: {last}")
        except BaseException:
            if self.line is None:
                L.close()
            raise
        self.line, self.lo, self.hi = L, lo, hi

    def close(self):
        """Magnet home at 0 mm verified while the limits are still set, then the release limits. A failed home
        releases nothing and raises (the lock holder keeps the lock); the port and the session limits are KEPT, so
        the retry (fault list D1, owner 2026-10-31) repeats the home on the same session instead of re-opening
        (a re-open would write the limits again and run the FNL reference move)."""
        L = self.line
        if L is None:
            return
        self._checked_move(L, 0.0)
        self._wait(L, lambda: _num(L.ask("ONT?")) == 1, 60)
        p = _num(L.ask("POS?"))
        if p is None or abs(p) > HOME_TOL:
            raise ConnectionError(f"PI magnet return: POS {p}, not within {HOME_TOL} of 0 mm; limits NOT released")
        self._write_limits(L, RELEASE_LO, RELEASE_HI)
        self.line, self.lo = None, None
        L.close()

    # --- the gate: one checked move ----------------------------------------------------------------------------
    def _checked_move(self, L, target):
        """Inside this port session: limits still the session's, referenced, servo on, target inside; then ONE MOV."""
        gate.permitted("a PI move")
        tmn, tmx = self._limits(L)
        if abs(tmn - self.lo) > TOL or abs(tmx - self.hi) > TOL:
            raise ValueError(f"PI controller limits TMN {tmn} / TMX {tmx} are not the session's {self.lo:g}..{self.hi:g}")
        if not self.lo <= target <= self.hi:
            raise ValueError(f"PI ERR 7: target {target:g} mm outside the soft limits TMN/TMX ({self.lo:g}, {self.hi:g}) mm")
        if _num(L.ask("FRF?")) != 1:
            raise ValueError("PI axis not referenced (FRF? 0): reconnect for a reference move")
        if _num(L.ask("SVO?")) != 1:
            L.say("SVO 1 1")
            time.sleep(0.3)
            if _num(L.ask("SVO?")) != 1:
                raise ValueError("PI ERR 5: the servo could not be enabled")
        L.ask("ERR?")        # drains a stale code (ERR 10 after HLT) so only this move is judged (rig 2026-10-30)
        L.say(f"MOV 1 {target:.5f}")
        err = _num(L.ask("ERR?"))
        if err:
            raise ValueError(f"PI ERR {err:g} right after MOV 1 {target:g}")

    # --- Device interface (service thread) ---------------------------------------------------------------------
    def identity(self):
        idn = self._io().ask("*IDN?")
        return {"model": idn or self.model, "serial": "", "firmware": idn.rsplit(",", 1)[-1] if idn else "",
                "port": self.port_name, "driver": "mtpy.devices.pi (GCS ASCII, pyserial)"}

    def settings(self):
        return {"position": self.position(), "speed": self.speed(), "unit": self.unit}

    def limits(self):
        tmn, tmx = self._limits(self._io())
        return {"soft_limits_TMN_TMX": (tmn, tmx), "unit": self.unit}

    def probe(self):
        return {"position": self.position()}

    def session_origin(self):
        return None

    def move_to(self, target, speed=None):
        L = self._io()
        if speed is not None:
            vmax = safety.profile()["limits"]["magnet_speed_mm_s"]["max"]      # audit item 7: the driver's own cap
            if vmax is None or not 0 < speed <= vmax:
                raise ValueError(f"PI VEL {speed!r} outside the profile's 0..{vmax} mm/s")
            L.say(f"VEL 1 {speed:g}")
            v, err = _num(L.ask("VEL?")), _num(L.ask("ERR?"))
            if err or v is None or abs(v - speed) > 1e-3:
                raise ValueError(f"PI VEL {speed:g}: read back {v}, ERR {err}")
        self._checked_move(L, float(target))

    def moving(self):
        L = self._io()
        p = _num(L.ask("POS?"))
        if p is not None and (p > self.hi + 0.5 or p < self.lo - 0.5):
            L.say("HLT 1")                   # watchdog: outside the limits by more than 0.5 mm
            raise ValueError(f"PI position {p} outside the limits; HLT sent")
        ont = _num(L.ask("ONT?"))
        if ont is None:                      # fault list D7 (2026-10-31): a dead port must not read as "still moving"
            raise ConnectionError("PI ONT?: no reply")
        return ont != 1

    def speed(self):
        v = _num(self._io().ask("VEL?"))
        if v is None:
            raise ConnectionError("PI VEL? gave no number")
        return v

    def position(self):
        p = _num(self._io().ask("POS?"))
        if p is None:
            raise ConnectionError("PI POS? gave no number")
        return p

    def error(self):
        e = _num(self._io().ask("ERR?"))
        return int(e) if e is not None else 0

    def set_servo(self, on):
        self._io().say(f"SVO 1 {1 if on else 0}")

    def servo_on(self):
        return _num(self._io().ask("SVO?")) == 1

    def stop(self):
        if self.line is not None:
            self.line.say("HLT 1")
