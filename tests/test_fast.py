"""The numba executor must agree with the reference port (track.py) and with LabVIEW."""
import numpy as np
import pytest
from conftest import read_image

from mtpy.fast import FastKernel
from mtpy.track import Z_METHODS, Stages, lv_round, track_bead

CROSS = 120


def test_fast_matches_reference_and_labview(replay):
    rows, cals = replay["rows"], replay["cals"]
    fk = FastKernel(CROSS, replay["win_rs"], replay["win_h"], cals)
    worst_ref, worst_lv, n = np.zeros(3), np.zeros(3), 0
    for k in range(1, len(rows), 97):
        prev, row = rows[k - 1], rows[k]
        if any(v == -1.0 for v in prev["ff"]):
            continue
        img = read_image(row["frame"]).astype(np.uint8)
        st = np.array(prev["ff"]).reshape(-1, 3)
        xin = [lv_round(v) for v in st[:, 0]]
        yin = [lv_round(v) for v in st[:, 1]]
        xyz, idx, good = fk.track(img, xin, yin, prev["good"])
        ref_lv = np.array(row["ff"]).reshape(-1, 3)
        for b, cal in enumerate(cals):
            if not prev["good"][b]:
                assert (xyz[b] == -1.0).all()
                continue
            x, y, z, i, g = track_bead(img, xin[b], yin[b], CROSS, replay["win_rs"], replay["win_h"], cal)
            assert idx[b] == i == row["pos"][b] and good[b] == g == row["good"][b]
            worst_ref = np.maximum(worst_ref, np.abs(xyz[b] - (x, y, z)))
            worst_lv = np.maximum(worst_lv, np.abs(xyz[b] - ref_lv[b]))
            n += 1
    print(f"{n} bead-frames; fast vs reference {worst_ref}, fast vs LabVIEW {worst_lv}")
    assert n > 100
    assert worst_ref.max() < 1e-9
    assert worst_lv[:2].max() < 1e-6 and worst_lv[2] < 1e-4


@pytest.mark.parametrize("z_method", list(Z_METHODS))
def test_fast_z_methods_match_reference(replay, z_method):
    """Every Z stage of track.Z_METHODS: the numba executor equals the numpy reference (same frames, same LUT)."""
    rows, cals = replay["rows"], replay["cals"]
    fk = FastKernel(CROSS, replay["win_rs"], replay["win_h"], cals, z_method=z_method)
    stages = Stages(z=Z_METHODS[z_method])
    worst, n = 0.0, 0
    for k in range(1, len(rows), 397):
        prev, row = rows[k - 1], rows[k]
        if any(v == -1.0 for v in prev["ff"]):
            continue
        img = read_image(row["frame"]).astype(np.uint8)
        st = np.array(prev["ff"]).reshape(-1, 3)
        xin = [lv_round(v) for v in st[:, 0]]
        yin = [lv_round(v) for v in st[:, 1]]
        xyz, idx, good = fk.track(img, xin, yin, prev["good"])
        for b, cal in enumerate(cals):
            if not prev["good"][b]:
                continue
            _, _, z, i, g = track_bead(img, xin[b], yin[b], CROSS, replay["win_rs"], replay["win_h"], cal, stages=stages)
            assert idx[b] == i and good[b] == g
            worst = max(worst, abs(xyz[b, 2] - z))
            n += 1
    print(f"{z_method}: {n} bead-frames, fast vs reference z {worst:.2e} um")
    assert n > 20 and worst < 1e-9
