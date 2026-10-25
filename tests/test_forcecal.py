"""Decision 0018: the force calibrations of `mtpy.forcecal` (pure maths; no device, no G: data)."""
import math
import time

import numpy as np
import pytest

from mtpy import forcecal
from mtpy.forcecal import M270_CASE0, M270_V3, TableCalibration


def _formula(d):
    return 48.8162 * math.exp(-d / 1.13483) + 22.8394 * math.exp(-d / 3.68428) - 0.45845


def test_m270_v3_values_match_the_labview_equation():
    """`Magnet2Force v3_for M270.vi` case "1, Default" (V6 card m2feq2): d = touch - position."""
    assert M270_V3.force(20.0, 20.0) == pytest.approx(71.19715, abs=1e-12)               # d = 0
    assert M270_V3.force(18.0, 20.0) == pytest.approx(21.191957232369177, rel=1e-15)     # d = 2
    for touch, pos in ((20.0, 21.0), (20.0, 15.0), (40.0, 30.0), (40.0, 0.0), (12.5, 3.25)):
        assert M270_V3.force(pos, touch) == pytest.approx(_formula(touch - pos), rel=1e-15)
    arr = M270_V3.force(np.array([18.0, 20.0]), 20.0)
    assert arr.shape == (2,) and arr[1] == pytest.approx(71.19715, abs=1e-12)
    assert forcecal.DEFAULT is M270_V3 and M270_CASE0 is not forcecal.DEFAULT
    assert M270_CASE0.force(10.0, 10.0) == pytest.approx(40.38409 + 37.73288)
    d = M270_V3.describe(20.0)
    assert d["name"] == "M270 v3 (LabVIEW Magnet2Force v3, case 1)" and d["touch_mm"] == 20.0
    assert d["constants"] == {"a1_pN": 48.8162, "t1_mm": 1.13483, "a2_pN": 22.8394, "t2_mm": 3.68428,
                              "c_pN": -0.45845}
    assert "48.8162*exp(-d/1.13483) + 22.8394*exp(-d/3.68428) - 0.45845" in d["equation"]


def test_force_rises_with_position_and_the_inverse_round_trips_to_1e_9_mm():
    touch, lo, hi = 40.0, 0.0, 39.0
    p = np.linspace(lo, hi, 400)
    assert np.all(np.diff(M270_V3.force(p, touch)) > 0)
    for pos in (0.0, 1e-6, 3.3, 17.25, 30.0, 38.999999, 39.0):
        f = M270_V3.force(pos, touch)
        back = M270_V3.position(f, lo, hi, touch)
        assert abs(back - pos) <= 1e-9, (pos, back)
    assert M270_V3.position(1e6, lo, hi, touch) == hi and M270_V3.position(-5.0, lo, hi, touch) == lo


def test_live_force_is_cheap():
    """The poller / display may call it per reading: far below a millisecond."""
    t = time.perf_counter()
    for i in range(2000):
        M270_V3.force(20.0 + i * 1e-3, 40.0)
    assert (time.perf_counter() - t) / 2000 < 1e-4
    t = time.perf_counter()
    M270_V3.position(10.0, 0.0, 39.0, 40.0)
    assert time.perf_counter() - t < 0.01


def test_table_calibration_behind_the_same_interface():
    t = TableCalibration({"name": "t", "version": "1", "position_mm": [20.0, 10.0, 0.0], "force_pN": [0.1, 1.0, 10.0]})
    assert t.domain() == (0.0, 20.0) and t.force(10.0) == 1.0 and t.position(1.0, 0.0, 20.0) == 10.0
    assert t.describe()["kind"] == "table" and not t.needs_touch
    with pytest.raises(ValueError, match="strictly"):
        TableCalibration({"name": "t", "version": "1", "position_mm": [0.0, 1.0], "force_pN": [2.0, 1.0]})
