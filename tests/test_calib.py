"""Phase 4a: the calibration cluster built from the .cal file must give the same tracking as LabVIEW's own cluster."""
import numpy as np
from conftest import FIXTURE, read_image

from mtpy import calib
from mtpy.fast import FastKernel
from mtpy.lvfiles import read_cal
from mtpy.track import lv_round


def test_windows_and_band_shape():
    win_rs, win_h = calib.windows(120)
    assert win_rs[0] == 0 and abs(win_rs[-1]) < 1e-15 and win_h[61:].max() == 0
    band = calib.cosband(0, 25, 120)
    assert band[0] == 0 and band[26:].max() == 0 and abs(band[12] - 0.5 * (1 - np.cos(2 * np.pi * 12 / 25))) < 1e-15


def test_cal_file_cluster_tracks_like_labview(replay):
    """Same frames as test_fast; LabVIEW's windows and cluster replaced by the ones built here from cal002."""
    rows = replay["rows"]
    cal = read_cal(FIXTURE / "cal002")
    win_rs, win_h = calib.windows(120)
    fk = FastKernel(120, win_rs, win_h, calib.clusters(cal))
    worst, n = np.zeros(3), 0
    for k in range(1, len(rows), 97):
        prev, row = rows[k - 1], rows[k]
        if any(v == -1.0 for v in prev["ff"]):
            continue
        st = np.array(prev["ff"]).reshape(-1, 3)
        xyz, idx, good = fk.track(read_image(row["frame"]).astype(np.uint8), [lv_round(v) for v in st[:, 0]],
                                  [lv_round(v) for v in st[:, 1]], prev["good"])
        ref = np.array(row["ff"]).reshape(-1, 3)
        ok = np.array(prev["good"])
        assert np.array_equal(idx[ok], np.array(row["pos"])[ok]) and np.array_equal(good[ok], np.array(row["good"])[ok])
        worst = np.maximum(worst, np.abs(xyz[ok] - ref[ok]).max(axis=0))
        n += ok.sum()
    print(f"{n} bead-frames, worst vs LabVIEW {worst}")
    assert worst[:2].max() < 1e-6 and worst[2] < 1e-4
