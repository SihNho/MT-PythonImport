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


class _FakeKernel:
    """Bead 0 is always found at its true position. Bead 1 is found there too, but flagged bad unless the start is
    within `reach` px of it (as a real bead far from its start: z out of the LUT); always bad with reach < 0."""

    def __init__(self, true_xy, reach):
        self.true, self.reach, self.starts = np.asarray(true_xy, float), reach, []

    def track(self, image, xin, yin, good_in):
        self.starts.append(np.column_stack([xin, yin]).tolist())
        xyz = np.column_stack([self.true, [1.0, 1.0]])
        good = np.array([True, np.hypot(xin[1] - self.true[1, 0], yin[1] - self.true[1, 1]) <= self.reach])
        xyz[~good_in], good[~good_in] = -1.0, False
        return xyz, None, good


def _fake_beads(xy0):
    from types import SimpleNamespace
    return SimpleNamespace(xy0=np.asarray(xy0, float), cross=120, fit=lambda shape: True)


def test_only_the_lost_bead_restarts_and_from_where_it_was_seen():
    """Decision 0032 (owner 2026-11-15): LabVIEW restarts EVERY bead from its calibration position after any -1; a
    bead 20 px from its pick then came back as -1 every second frame for ever and the others read differently on
    each restart frame. Now the other bead never goes back to its pick and the lost one is found on the next try."""
    from mtpy.acq.pipeline import BeadTracker
    xy0, true = [[200.0, 200.0], [400.0, 300.0]], [[210.0, 200.0], [420.0, 300.0]]
    k = _FakeKernel(true, reach=5)
    t = BeadTracker(_fake_beads(xy0), k)
    img = np.zeros((600, 800))
    out = [t.step(img)[0] for _ in range(6)]
    lost = [bool((o[1] == -1.0).all()) for o in out]
    assert lost == [False, True, False, False, False, False]          # one -1 frame, then found again
    assert all((o[0] != -1.0).all() for o in out)                      # bead 0 is never lost
    assert [s[0] for s in k.starts] == [[200, 200]] + [[210, 200]] * 5  # bead 0: its pick once, then its own output
    assert k.starts[2][1] == [420, 300]                                # bead 1 restarts from where it was seen


def test_a_bead_that_stays_bad_is_tried_from_its_pick_every_second_time():
    from mtpy.acq.pipeline import BeadTracker
    xy0, true = [[200.0, 200.0], [400.0, 300.0]], [[210.0, 200.0], [420.0, 300.0]]
    k = _FakeKernel(true, reach=-1)
    t = BeadTracker(_fake_beads(xy0), k)
    img = np.zeros((600, 800))
    out = [t.step(img)[0] for _ in range(9)]
    assert [bool((o[1] == -1.0).all()) for o in out] == [False, True] * 4 + [False]
    assert [k.starts[i][1] for i in (0, 2, 4, 6, 8)] == [[400, 300], [420, 300], [400, 300], [420, 300], [400, 300]]
    assert [s[0] for s in k.starts[1:]] == [[210, 200]] * 8            # the other bead is left alone
