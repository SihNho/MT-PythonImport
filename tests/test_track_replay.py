"""Tier 2: replay recorded frames and compare with LabVIEW's kernel output (decision 0004).
Default: every 20th frame; MTPY_FULL_REPLAY=1 runs all 10 043."""
import os

import numpy as np
from conftest import read_image

from mtpy.track import Tracker, lv_round, track_bead

TOL_XY, TOL_Z = 1e-6, 1e-4          # px, um (z relaxed by the owner 2026-09-07)
CROSS = 120
# (frame, bead) where the calibration-slice fit is a near tie (SSD of slices 25 and 26 differ by 3e-5 relative) and
# LabVIEW's single-precision radial profile picks the other slice: z differs by 4.7e-3 um. Known since MT_LabVIEW
# 2026-09-07; exact fix needs LabVIEW's SGL rounding order (docs/spec/questions-for-owner.md).
KNOWN_SLICE_FLIPS = {(1937, 4)}


def test_kernel_matches_labview(replay):
    """Each frame starts from LabVIEW's own previous output, as the MT_LabVIEW harness did (check_all.py)."""
    rows, cals = replay["rows"], replay["cals"]
    every = 1 if os.environ.get("MTPY_FULL_REPLAY") else 20
    worst, n_cmp, n_good_flag, flips = np.zeros(3), 0, 0, set()
    for k in range(1, len(rows), every):
        prev, row = rows[k - 1], rows[k]
        if any(v == -1.0 for v in prev["ff"]):
            continue                                       # reseed frames are covered by test_tracker_state_machine
        img = read_image(row["frame"])
        for b, cal in enumerate(cals):
            if not prev["good"][b] or row["ff"][3 * b] == -1.0:
                continue
            x0, y0 = prev["ff"][3 * b], prev["ff"][3 * b + 1]
            x, y, z, idx, good = track_bead(img, lv_round(x0), lv_round(y0), CROSS, replay["win_rs"], replay["win_h"], cal)
            ref = row["ff"][3 * b:3 * b + 3]
            n_good_flag += good == row["good"][b]
            n_cmp += 1
            if idx != row["pos"][b]:
                flips.add((row["frame"], b))
                continue
            worst = np.maximum(worst, np.abs(np.array([x, y, z]) - ref))
    print(f"compared {n_cmp} bead-frames, worst |dx| {worst[0]:.2e} |dy| {worst[1]:.2e} |dz| {worst[2]:.2e}")
    assert n_cmp > 0
    assert worst[0] < TOL_XY and worst[1] < TOL_XY and worst[2] < TOL_Z
    assert n_good_flag == n_cmp
    assert flips <= KNOWN_SLICE_FLIPS, flips - KNOWN_SLICE_FLIPS


def test_tracker_state_machine(replay):
    """Tracker fed with its own output: the first 300 frames, and the end of the recording where beads are lost."""
    rows = replay["rows"]
    worst_bad = 0.0
    for start, stop in ((0, 300), (len(rows) - 60, len(rows))):
        t = Tracker(replay["xy0"], CROSS, replay["win_rs"], replay["win_h"], replay["cals"])
        if start:
            prev = np.array(rows[start - 1]["ff"]).reshape(-1, 3)
            t.xy, t.good, t.lost = prev[:, :2].copy(), np.array(rows[start - 1]["good"]), bool((prev == -1.0).any())
        for k in range(start, stop):
            xyz = t.step(read_image(rows[k]["frame"]))
            ref = np.array(rows[k]["ff"]).reshape(-1, 3)
            np.testing.assert_array_equal(xyz == -1.0, ref == -1.0, err_msg=f"frame {rows[k]['frame']}")
            good = np.array(rows[k]["good"])
            d = np.abs(xyz - ref)
            assert d[good, :2].max() < TOL_XY and d[good, 2].max() < TOL_Z, (rows[k]["frame"], d.max(axis=0))
            # A bead flagged bad (defocused, z at the stack edge) has a nearly flat correlation peak, so the parabola
            # fit amplifies rounding: x,y differ from LabVIEW by up to 3.1e-5 px (z is exact). Looser bound pending the
            # owner's decision (docs/spec/questions-for-owner.md).
            worst_bad = max(worst_bad, d[~good].max(initial=0.0))
            assert worst_bad < 1e-4, (rows[k]["frame"], d.max(axis=0))
            np.testing.assert_array_equal(t.good, good, err_msg=f"frame {rows[k]['frame']}")
    print(f"worst difference on beads flagged bad: {worst_bad:.2e}")
