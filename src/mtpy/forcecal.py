"""Magnet force calibrations: magnet position (raw, decision 0010) -> force, and the inverse (decisions 0017, 0018).

Two kinds behind one interface (0010: swappable):

- `EquationCalibration` (the default, decision 0018 item 1): the force computed live from the calibration equation of
  the LabVIEW program. `M270_V3` is `Magnet2Force v3_for M270.vi`, selected case "1, Default" (read from the VI copy
  and checked by running it: 16 points, worst relative deviation 2.2e-16; V6 card m2feq2,
  tools/bench/m2feq2_report.md):

      F_pN = 48.8162 * exp(-d / 1.13483) + 22.8394 * exp(-d / 3.68428) - 0.45845,   d = touch_mm - pos_mm

  touch_mm is 'Mag pos when touched to glass' (a rig / session parameter); pos_mm the magnet position (`Max Trans
  Pos.vi` is an identity). F rises monotonically with pos. The VI's unused case "0" is kept as `M270_CASE0`, a named
  alternative, never the default.
- `TableCalibration`: a recorded position-to-force table (the pre-0018 default), interpolated linearly.

Every calibration offers `force(pos_mm, touch_mm)`, `position(force_pN, lo, hi, touch_mm)` (the inverse on [lo, hi],
which must lie inside `domain()`), `domain()` and `describe(touch_mm)` (what the run file records). Pure maths: no
device, no event, no lock; cheap enough for a poller or display to call per reading (two exponentials or one
interpolation). The safety logic (position limit, coercion, events) lives in `mtpy.api.magnet`.
"""
import math

import numpy as np

POSITION_TOL_MM = 1e-9          # the inverse's bracket width (bisection)


class EquationCalibration:
    """F(d) = a1 * exp(-d / t1) + a2 * exp(-d / t2) + c, d = touch_mm - pos_mm (a1, a2, t1, t2 > 0: F rises with pos).
    Needs touch_mm for every value."""

    kind = "equation"
    needs_touch = True

    def __init__(self, name, a1, t1, a2, t2, c, source):
        if not all(math.isfinite(x) for x in (a1, t1, a2, t2, c)) or min(a1, a2, t1, t2) <= 0:
            raise ValueError("a1, a2, t1, t2 must be finite and > 0 (F must rise strictly with the position)")
        self.name, self.source = name, source
        self.a1, self.t1, self.a2, self.t2, self.c = float(a1), float(t1), float(a2), float(t2), float(c)

    @property
    def equation(self):
        return (f"F_pN = {self.a1:g}*exp(-d/{self.t1:g}) + {self.a2:g}*exp(-d/{self.t2:g}) "
                f"{'-' if self.c < 0 else '+'} {abs(self.c):g}, d = touch_mm - pos_mm")

    def domain(self):
        return (-math.inf, math.inf)

    def force(self, pos_mm, touch_mm):
        """Force in pN at the magnet position pos_mm (a number or an array) for the touch position touch_mm."""
        d = touch_mm - np.asarray(pos_mm, dtype=float)
        f = self.a1 * np.exp(-d / self.t1) + self.a2 * np.exp(-d / self.t2) + self.c
        return float(f) if f.ndim == 0 else f

    def position(self, force_pN, lo, hi, touch_mm):
        """The position in [lo, hi] whose force is force_pN (bisection to POSITION_TOL_MM); the nearer end when the
        force is outside [force(lo), force(hi)]."""
        return _bisect(lambda p: self.force(p, touch_mm), force_pN, lo, hi)

    def describe(self, touch_mm=None):
        return {"name": self.name, "kind": self.kind, "equation": self.equation,
                "constants": {"a1_pN": self.a1, "t1_mm": self.t1, "a2_pN": self.a2, "t2_mm": self.t2,
                              "c_pN": self.c},
                "touch_mm": None if touch_mm is None else float(touch_mm), "source": self.source}


class TableCalibration:
    """A recorded table {"name", "version", "position_mm": [...], "force_pN": [...]}: force strictly increasing,
    position strictly monotonic (decision 0017 item 3), interpolated linearly; defined only between its ends."""

    kind = "table"
    needs_touch = False

    def __init__(self, table):
        try:
            pos = np.asarray(table["position_mm"], dtype=float)
            f = np.asarray(table["force_pN"], dtype=float)
            ok = (isinstance(table["name"], str) and table["name"] and "version" in table and pos.ndim == 1
                  and pos.shape == f.shape and pos.size >= 2 and np.all(np.isfinite(pos)) and np.all(np.isfinite(f))
                  and np.all(np.diff(f) > 0) and (np.all(np.diff(pos) > 0) or np.all(np.diff(pos) < 0)))
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            raise ValueError("a force table needs name, version, position_mm and force_pN (same length >= 2, finite, "
                             "force strictly increasing, position strictly monotonic)")
        self.name, self.version, self.table = table["name"], table["version"], table
        self.f_pos = (pos, f)                                   # force increasing (for the inverse)
        self.p_pos = (pos, f) if pos[0] < pos[-1] else (pos[::-1], f[::-1])   # position increasing (for force)

    def domain(self):
        p = self.p_pos[0]
        return (float(p[0]), float(p[-1]))

    def force(self, pos_mm, touch_mm=None):
        f = np.interp(np.asarray(pos_mm, dtype=float), *self.p_pos)
        return float(f) if np.ndim(f) == 0 else f

    def position(self, force_pN, lo, hi, touch_mm=None):
        pos, f = self.f_pos
        p = float(np.interp(force_pN, f, pos))
        return min(max(p, lo), hi)

    def describe(self, touch_mm=None):
        return {"name": self.name, "kind": self.kind, "version": self.version,
                "position_mm": [float(x) for x in self.table["position_mm"]],
                "force_pN": [float(x) for x in self.table["force_pN"]]}


def _bisect(fn, target, lo, hi):
    """Monotonic fn on [lo, hi] (rising or falling): the x with fn(x) == target, or the nearer end."""
    f_lo, f_hi = fn(lo), fn(hi)
    rising = f_hi >= f_lo
    if (target <= f_lo) if rising else (target >= f_lo):
        return float(lo)
    if (target >= f_hi) if rising else (target <= f_hi):
        return float(hi)
    a, b = float(lo), float(hi)
    while b - a > POSITION_TOL_MM:
        m = 0.5 * (a + b)
        if m in (a, b):
            break
        if (fn(m) < target) == rising:
            a = m
        else:
            b = m
    return 0.5 * (a + b)


M270_V3 = EquationCalibration(
    "M270 v3 (LabVIEW Magnet2Force v3, case 1)", 48.8162, 1.13483, 22.8394, 3.68428, -0.45845,
    "LabVIEW 'Magnet2Force v3_for M270.vi', case \"1, Default\" (V6 card m2feq2: 16 points, worst relative "
    "deviation 2.2e-16)")
M270_CASE0 = EquationCalibration(
    "M270 v3 case 0 (LabVIEW Magnet2Force v3, unused case 0)", 40.38409, 2.85023, 37.73288, 0.89767, 0.0,
    "LabVIEW 'Magnet2Force v3_for M270.vi', case \"0\" (not selected in the LabVIEW program; alternative only)")
DEFAULT = M270_V3
EQUATIONS = {c.name: c for c in (M270_V3, M270_CASE0)}
