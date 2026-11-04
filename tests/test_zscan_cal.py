"""The .cal the GUI's z scan writes carries (LOW, HIGH, forget) per bead, as LabVIEW's file does, and a .cal with an
empty band is refused at select (rig 2026-10-30: the first scan wrote (x, y, cross) there and the kernel divided by
zero at acquisition start)."""
import numpy as np
import pytest

from mtpy import api, calib
from mtpy.api.errors import NotReady
from mtpy.lvfiles import read_cal, write_cal


@pytest.fixture
def sim(tmp_path, monkeypatch):
    """A connected simulated rig: the z scan locks the camera service while it runs."""
    from test_devices import _config

    from mtpy.api import estop, events
    _config(tmp_path, monkeypatch, test_limits=True)
    with events.as_caller("gui"):
        estop.clear()
        api.devices.connect({"backend": "sim"})
    yield
    api.devices.disconnect()


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


def test_zscan_writes_the_band_not_the_position(sim, tmp_path, monkeypatch):
    from mtpy.api import zscan
    frames = iter([np.full((1024, 1280), 100.0) + k for k in range(200)])
    monkeypatch.setattr(api.acq, "average", lambda n, timeout_s=10.0: next(frames))

    class _M:
        def wait(self, t):
            return 0.0
    monkeypatch.setattr(api.focus, "position", lambda: 0.0)
    monkeypatch.setattr(api.focus, "move_to", lambda z: _M())
    monkeypatch.setattr(api.events, "log", lambda *a, **k: None)
    waits = []
    monkeypatch.setattr(zscan.time, "sleep", waits.append)
    cal = zscan.run(tmp_path / "cal_z", [(200.0, 200.0), (640.0, 512.0)], slices=5, n_avg=1)
    assert waits == [0.2] * 5                                   # owner 2026-11-01: 0.2 s settle after each move
    assert cal["bead_i32"].tolist() == [[0, 40, 10], [0, 40, 10]]
    assert read_cal(tmp_path / "cal_z")["bead_i32"].tolist() == [[0, 40, 10], [0, 40, 10]]


def test_zscan_refuses_an_empty_pick_list(tmp_path):
    """Rig 2026-10-31: an empty pick list scanned 60 slices and then crashed in write_cal; refuse before any move."""
    from mtpy.api import zscan
    with pytest.raises(ValueError, match="no bead positions"):
        zscan.run(tmp_path / "cal_none", [], slices=5, n_avg=1)


def test_zscan_locks_the_camera_settings_while_it_runs(sim, tmp_path, monkeypatch):
    """Fault list P5 / G5 (owner 2026-10-30): a .cal must come from one camera setting; every camera change is
    refused while the scan runs and allowed again afterwards (also after a failed scan)."""
    from mtpy.api import zscan
    from mtpy.api.errors import SafetyRefused
    seen = []

    def average(n, timeout_s=10.0):
        try:
            api.camera.set_exposure(2.0)
        except SafetyRefused as e:
            seen.append(str(e))
        return np.full((1024, 1280), 100.0)

    class _M:
        def wait(self, t):
            return 0.0
    monkeypatch.setattr(api.acq, "average", average)
    monkeypatch.setattr(api.focus, "position", lambda: 0.0)
    monkeypatch.setattr(api.focus, "move_to", lambda z: _M())
    zscan.run(tmp_path / "cal_lock", [(200.0, 200.0)], slices=3, n_avg=1)
    assert len(seen) == 3 and "locked while a z scan runs" in seen[0]
    assert api.camera.set_exposure(2.0) == 2.0                 # unlocked again
    monkeypatch.setattr(api.acq, "average", lambda n, timeout_s=10.0: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        zscan.run(tmp_path / "cal_fail", [(200.0, 200.0)], slices=3, n_avg=1)
    assert api.camera.set_exposure(3.0) == 3.0                 # a failed scan unlocks too


def test_zscan_refuses_a_pick_inside_the_edge_margin_before_any_move(sim, tmp_path, monkeypatch):
    """Owner 2026-11-04: a pick 50 px from the right edge made the scan move through 60 slices and then fail with an
    IndexError; refuse first, naming the bead, and move nothing."""
    from mtpy.api import zscan
    monkeypatch.setattr(api.acq, "average", lambda n, timeout_s=10.0: np.full((1024, 1280), 100.0))
    moves = []
    monkeypatch.setattr(api.focus, "move_to", lambda z: moves.append(z))
    with pytest.raises(ValueError, match="bead 2 .* 50 px from the right edge; the 120-px window needs 72"):
        zscan.run(tmp_path / "cal_edge", [(640.0, 512.0), (1230.0, 500.0)], slices=5, n_avg=1)
    assert moves == []
    assert zscan.outside_margin((1024, 1280), [(72.0, 72.0), (1208.0, 952.0)], 120) == []


def test_zscan_refuses_a_folder_or_an_existing_file_as_the_cal_path(sim, tmp_path, monkeypatch):
    """Owner 2026-11-04: the GUI's "Write .cal to" held a folder; the scan ran 60 slices and then 'Permission denied'."""
    from mtpy.api import zscan
    moves = []
    monkeypatch.setattr(api.focus, "move_to", lambda z: moves.append(z))
    with pytest.raises(ValueError, match="is a folder; give the .cal file path"):
        zscan.run(tmp_path, [(640.0, 512.0)], slices=5, n_avg=1)
    (tmp_path / "cal_old").write_bytes(b"x")
    with pytest.raises(FileExistsError, match="never overwritten"):
        zscan.run(tmp_path / "cal_old", [(640.0, 512.0)], slices=5, n_avg=1)
    assert moves == []


def test_radial_profile_reads_zero_outside_the_sub_image():
    """Rig 2026-11-05: a pick whose xy fit moved 20 px off ended the z scan with IndexError (index 118 of 118); the
    window now reads 0 outside, as LabVIEW does, and an in-range window is unchanged."""
    from mtpy import track
    sub = np.random.default_rng(1).uniform(50, 200, (144, 144))
    for sgl in (False, True):
        prof = track.radial_profile(sub, 92.3, 72.0, 60, sgl)
        assert prof.shape == (60,) and np.all(np.isfinite(prof))
        assert np.array_equal(track.radial_profile(sub, 72.3, 71.6, 60, sgl), track.radial_profile(sub, 72.3, 71.6, 60, sgl))
    before = track.radial_profile(sub, 72.3, 71.6, 60)
    assert np.allclose(before, track.radial_profile(np.pad(sub, 10), 82.3, 81.6, 60))


def test_zscan_starts_at_the_current_focus_and_stacks_upwards(sim, tmp_path, monkeypatch):
    """Owner 2026-11-05: no jump down first (drift); from the start position up, step by step, back at the end.
    centred=True keeps the bench tools' LUT centred on the start."""
    from mtpy.api import zscan
    monkeypatch.setattr(api.acq, "average", lambda n, timeout_s=10.0: np.full((1024, 1280), 100.0))
    moves = []

    class _M:
        def wait(self, t):
            return None
    monkeypatch.setattr(api.focus, "move_to", lambda z: (moves.append(round(z, 4)), _M())[1])
    z0 = api.focus.position()
    zscan.run(tmp_path / "cal_up", [(640.0, 512.0)], slices=3, n_avg=1)
    assert moves == [round(z0, 4), round(z0 + 0.1, 4), round(z0 + 0.2, 4), round(z0, 4)]
    moves.clear()
    zscan.run(tmp_path / "cal_mid", [(640.0, 512.0)], slices=3, n_avg=1, centred=True)
    assert moves == [round(z0 - 0.1, 4), round(z0, 4), round(z0 + 0.1, 4), round(z0, 4)]
