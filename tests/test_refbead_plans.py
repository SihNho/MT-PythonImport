"""The reference-bead plans return every axis to where it started and stay inside the V6 gate envelopes."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("refbead_record", Path(__file__).parents[1] / "tools" / "refbead_record.py")
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)


def moves(steps, device):
    return [s["command"] for s in steps if s["do"] == "gate" and s["device"] == device]


def test_plans_return_and_stay_inside():
    for name in ("static", "field", "magnet", "rotation", "exposure", "drift", "zscan", "zscan_field", "zfine50", "zfine20", "exposure2", "search", "zfine_at"):
        steps = rr.plan(name, 3000.0)
        pos, peak = {"X": 0, "Y": 0, "Z": 0}, {"X": 0, "Y": 0, "Z": 0}
        for c in moves(steps, "asi"):
            axis, v = c[2], float(c.split("=")[1])
            pos[axis] += v
            peak[axis] = max(peak[axis], abs(pos[axis]))
        assert all(abs(v) < 1e-6 for v in pos.values()), name
        assert max(peak["X"], peak["Y"]) <= 20000, name               # ASI window: start +- 2 mm (0.1 um units)
        assert peak["Z"] <= 50, name                                 # focus: +-5 um around the start
        rot, rpeak = 0, 0
        for c in moves(steps, "rotor"):
            if c.startswith("SPD"):
                assert int(c.split()[1]) <= 100, name                # V6 gate SPD cap
            else:
                rot += int(c.split()[1])
                rpeak = max(rpeak, abs(rot))
        assert rot == 0 and rpeak <= 2500, name                      # rotor window: start +- 2500 pulses
        mags = [float(c.split()[2]) for c in moves(steps, "pi")]
        assert all(0 <= m <= 39 for m in mags), name                 # PI TMN 0 / TMX 39
        assert not mags or mags[-1] == 0, name                       # magnet left at 0 mm (safe)
