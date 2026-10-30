"""The .cal the GUI's z scan writes carries (LOW, HIGH, forget) per bead, as LabVIEW's file does, and a .cal with an
empty band is refused at select (rig 2026-10-30: the first scan wrote (x, y, cross) there and the kernel divided by
zero at acquisition start)."""
import numpy as np
import pytest

from mtpy import api, calib
from mtpy.api.errors import NotReady
from mtpy.lvfiles import read_cal, write_cal


def _cal(bead_i32):
    rng = np.random.default_rng(0)
    return {"xy": np.array([[100.0, 100.0], [300.0, 200.0]]), "stack": 100 + rng.random((2, 12, 119)),
            "n_slices": 12, "bead_i32": np.asarray(bead_i32, dtype=np.int32), "z_step": 0.1, "n_avg": 2,
            "date": "2026-10-30 00:00:00", "bead_flags": np.zeros(2, dtype=np.int32), "nm_per_px": 84.0}


def test_select_refuses_an_empty_band(tmp_path):
    bad = tmp_path / "cal_bad"
    write_cal(bad, _cal([[100, 100, 120], [300, 200, 120]]))
    with pytest.raises(NotReady, match=r"\(LOW, HIGH, forget\) = \(100, 100, 120\)"):
        api.beads.select([1, 2], cal_path=bad)
    good = tmp_path / "cal_good"
    write_cal(good, _cal([[0, 40, 10], [0, 40, 10]]))
    api.beads.select([1, 2], cal_path=good)
    assert all((c["cosband"] != 0).any() for c in calib.clusters(read_cal(good)))


def test_zscan_writes_the_band_not_the_position(tmp_path, monkeypatch):
    from mtpy.gui import zscan
    frames = iter([np.full((1024, 1280), 100.0) + k for k in range(200)])
    monkeypatch.setattr(api.acq, "average", lambda n, timeout_s=10.0: next(frames))

    class _M:
        def wait(self, t):
            return 0.0
    monkeypatch.setattr(api.focus, "position", lambda: 0.0)
    monkeypatch.setattr(api.focus, "move_to", lambda z: _M())
    monkeypatch.setattr(api.events, "log", lambda *a, **k: None)
    cal = zscan.run(tmp_path / "cal_z", [(200.0, 200.0), (640.0, 512.0)], slices=5, n_avg=1)
    assert cal["bead_i32"].tolist() == [[0, 40, 10], [0, 40, 10]]
    assert read_cal(tmp_path / "cal_z")["bead_i32"].tolist() == [[0, 40, 10], [0, 40, 10]]
