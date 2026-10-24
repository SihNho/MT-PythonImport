"""WP4: the HDF5 v1 run file writer, reader, .tra / .cal export and the MATLAB reader's layout. Synthetic tests feed
the writer directly (frames and events in any order); API tests run the simulated rig; tests that need the recorded G:
fixture skip without it."""
import re
import subprocess
import sys
import time
from pathlib import Path

import h5py
import numpy as np
import pytest
from conftest import FIXTURE, need
from test_acq import SlowKernel, _connect

from mtpy import api
from mtpy.acq import Beads, FrameRecord, FrameResult
from mtpy.api.events import Event
from mtpy.data import HDF5Writer, RecordingRefused, export_cal, export_tra, legacy_matrix, read_run
from mtpy.lvfiles import read_cal, read_tra

REPO = Path(__file__).resolve().parents[1]
T0 = time.time()
ROI = (0, 0, 1280, 1024)
SET = {"roi": ROI, "rate_Hz": 90.0, "exposure_ms": 2.0, "gain_dB": 0.0}


@pytest.fixture
def cam(tmp_path, monkeypatch):
    """Simulated rig with the synthetic camera (as tests/test_acq.py)."""
    yield from _connect(tmp_path, monkeypatch)


@pytest.fixture
def fixture_cam(tmp_path, monkeypatch):
    """Simulated rig replaying the recorded fixture frames (skips without them)."""
    need(FIXTURE / "cal002", FIXTURE / "img00004.tif")
    yield from _connect(tmp_path, monkeypatch, str(FIXTURE))


def ev(t, kind, request=None, readback=None, **extra):
    return Event(T0 + t, kind, "gui", request, readback, extra)


def rec_on(t, seg=1, buf=None, name="r1", settings=SET):
    info = {"number": seg, "start_pc_s": T0, "rate_Hz": 90.0, "roi": ROI, "exposure_ms": 2.0, "t_source": "sim",
            "reason": "start", "first_buffer": 0 if buf is not None else None, "last_buffer": buf,
            "frames_received": 0 if buf is None else buf + 1, "end_loss": None}
    return ev(t, "recording", action="on", name=name, segment=seg, buffer_number=buf, segment_info=info,
              settings=settings)


def seg_begin(t, seg=1, rate=90.0, reason="start"):
    return ev(t, "segment", action="begin", segment=seg, reason=reason, rate_Hz=rate, roi=ROI, exposure_ms=2.0,
              t_source="sim", pc_gap_s=None, first_buffer=None, last_buffer=None, frames_received=0, camera_gaps=0,
              pipeline_drops=0, end_loss="unknown")


def seg_end(t, seg=1, last=9, gaps=1, drops=1, rate=90.0):
    return ev(t, "segment", action="end", segment=seg, reason="start", rate_Hz=rate, roi=ROI, exposure_ms=2.0,
              t_source="sim", pc_gap_s=None, first_buffer=0, last_buffer=last, frames_received=last + 1 - gaps,
              camera_gaps=gaps, pipeline_drops=drops, end_loss="unknown")


def frame(seg, b, t, rate=90.0, dropped=False, gap=0, nb=2, error=False):
    rec = FrameRecord(seg, b, b / rate, "sim", T0 + t, rate, ROI, gap, True)
    if dropped:
        return FrameResult(rec, tuple(range(1, nb + 1)), None, None, dropped=True)
    if error:
        return FrameResult(rec, tuple(range(1, nb + 1)), None, None, 0.1, extra={"error": "ValueError: x"})
    xyz = np.array([[10.0 * i + b, 20.0 * i + b, 0.01 * b + i] for i in range(nb)])
    if b == 3:
        xyz[1] = -1.0                                         # a lost bead (LabVIEW marker)
    good = np.ones(nb, dtype=bool)
    good[1:2] = b != 3
    return FrameResult(rec, tuple(range(1, nb + 1)), xyz, good, 0.5)


def _items():
    """One recording, one segment: 10 buffers, 0..9, buffer 5 a pipeline drop, buffer 7 missing (camera gap)."""
    frames = [frame(1, b, 0.1 + b / 90, dropped=(b == 5), gap=(1 if b == 8 else 0)) for b in range(10) if b != 7]
    events = [rec_on(0.05), ev(0.06, "acquisition", action="start", name="r1", record=True, beads=[1, 2], cal=None),
              seg_begin(0.07), ev(0.105, "act", {"quantity": "magnet_position_mm", "value": 5.0}, 5.0),
              ev(0.2, "mark", text="hello", segment=1, buffer_number=4), seg_end(0.3),
              ev(0.31, "recording", action="off", name="r1", segment=1, buffer_number=9)]
    return frames, events


def _write(path, order, **kw):
    w = HDF5Writer(path, **kw)
    frames, events = _items()
    if order == "events first":                               # recording-on precedes the acquisition start
        for e in events[:3]:
            w.write_event(e)
        for x in frames:
            w.write_frame(x)
        for e in events[3:]:
            w.write_event(e)
    else:                                                     # frames first, recording-on arrives last
        for x in frames:
            w.write_frame(x)
        for e in reversed(events):
            w.write_event(e)
    w.close()
    return read_run(path)


def test_roundtrip_both_arrival_orders_same_file(tmp_path):
    a = _write(tmp_path / "a.h5", "events first")
    b = _write(tmp_path / "b.h5", "frames first")
    for run in (a, b):
        assert run["attrs"]["schema_version"] == "1.0" and run["attrs"]["closed_cleanly"] == 1
        mt = run["mt"]
        assert mt["buffer_number"].tolist() == [0, 1, 2, 3, 4, 5, 6, 8, 9]
        assert mt["dropped"].tolist() == [0, 0, 0, 0, 0, 1, 0, 0, 0]
        assert mt["lost_before"].tolist() == [0, 0, 0, 0, 0, 0, 0, 1, 0]
        assert np.isnan(mt["x_px"][5]).all() and mt["x_px"][2].tolist() == [2.0, 12.0]
        assert mt["bead_lost"][3].tolist() == [0, 1] and mt["bead_good"][3].tolist() == [1, 0]
        assert np.allclose(mt["z_um"][4], [0.04, 1.04])
        assert np.isnan(mt["magnet_mm"][0]) and (mt["magnet_mm"][1:] == 5.0).all()     # act at 0.105 s
        seg = run["segments"]
        assert seg["number"].tolist() == [1] and seg["rate_Hz"][0] == 90.0 and seg["gain_dB"][0] == 0.0
        assert seg["frames_recorded"][0] == 9 and seg["frames_dropped"][0] == 1 and seg["camera_gaps"][0] == 1
        assert seg["camera_gaps_segment"][0] == 1 and seg["end_loss"][0] == -1 and seg["first_buffer"][0] == 0
        assert seg["rate_Hz_measured"][0] == pytest.approx(90.0)
        assert run["recordings"]["name"].tolist() == ["r1"] and run["recordings"]["off_buffer"][0] == 9
        assert run["events"]["mark"]["data"][0]["text"] == "hello"
        assert run["events"]["mark"]["buffer_number"][0] == 4
        assert run["metadata"]["devices"]["jai"]["readback"]["rate_Hz"] == 90.0
        assert run["beads"]["bead_id"].tolist() == [1, 2] and run["beads"]["role"].tolist() == ["candidate"] * 2
    times = ("t_host", "magnet_t", "rotor_t", "t_start", "t_end")     # from each writer's own t0
    for tab, keys in (("mt", list(a["mt"])), ("segments", ["number", "rate_Hz", "roi", "exposure_ms", "gain_dB",
                      "first_buffer", "last_buffer", "frames_received", "frames_recorded", "frames_dropped",
                      "camera_gaps", "end_loss", "t_start", "t_end"])):
        for k in keys:
            if k in times:
                np.testing.assert_allclose(a[tab][k] + a["attrs"]["t0_unix"], b[tab][k] + b["attrs"]["t0_unix"],
                                           rtol=0, atol=1e-6, err_msg=k)
            else:
                np.testing.assert_array_equal(a[tab][k], b[tab][k], err_msg=k)
    assert sorted(a["events"]) == sorted(b["events"])
    assert (tmp_path / "a.meta.json").is_file()


@pytest.mark.parametrize("missing", ["roi", "rate_Hz", "exposure_ms", "gain_dB", "all"])
def test_recording_on_without_the_four_settings_refused(tmp_path, missing):
    s = {} if missing == "all" else {k: v for k, v in SET.items() if k != missing}
    w = HDF5Writer(tmp_path / "r.h5")
    with pytest.raises(RecordingRefused, match="lacks the settings"):
        w.write_event(rec_on(0.0, settings=s or None))
    assert not (tmp_path / "r.h5").exists() and len(w.refused) == 1 and w.f is None
    w.write_frame(frame(1, 0, 0.1))                           # held, not written: no accepted recording-on
    with pytest.raises(RecordingRefused, match="1 recorded frames not written"):
        w.close()
    assert not (tmp_path / "r.h5").exists()


def test_refused_then_accepted_recording_on(tmp_path):
    w = HDF5Writer(tmp_path / "r.h5")
    with pytest.raises(RecordingRefused):
        w.write_event(rec_on(0.0, name="bad", settings={"roi": ROI}))
    w.write_event(rec_on(0.1, name="good"))
    w.write_frame(frame(1, 0, 0.2))
    w.close()
    run = read_run(tmp_path / "r.h5")
    assert run["recordings"]["name"].tolist() == ["good"] and run["attrs"]["recordings_refused"] == 1
    refused = run["events"]["writer_refused"]["data"][0]
    assert refused["missing"] == ["rate_Hz", "exposure_ms", "gain_dB"] and refused["event"]["extra"]["name"] == "bad"
    assert "recording" in run["events"] and len(run["events"]["recording"]["event_id"]) == 1


def test_segment_restart_and_two_recordings_synthetic(tmp_path):
    w = HDF5Writer(tmp_path / "s.h5")
    w.write_event(rec_on(0.0, name="r1"))
    for b in range(5):
        w.write_frame(frame(1, b, 0.1 + b / 90))
    w.write_event(seg_end(0.2, seg=1, last=4, gaps=0, drops=0))
    w.write_event(seg_begin(0.25, seg=2, rate=60.0, reason="settings change"))
    w.write_event(ev(0.26, "act", {"quantity": "camera_gain_dB", "value": 3.0}, 3.0))
    for b in range(4):
        w.write_frame(frame(2, b, 0.3 + b / 60, rate=60.0))
    w.write_event(ev(0.4, "recording", action="off", name="r1", segment=2, buffer_number=3))
    w.write_event(rec_on(0.5, seg=2, buf=3, name="r2"))
    w.write_frame(frame(2, 4, 0.55, rate=60.0, error=True))
    w.close()
    run = read_run(tmp_path / "s.h5")
    seg = run["segments"]
    assert seg["number"].tolist() == [1, 2] and seg["rate_Hz"].tolist() == [90.0, 60.0]
    assert seg["reason"].tolist() == ["start", "settings change"]
    assert seg["gain_dB"].tolist() == [0.0, 3.0]                 # spliced from the act event (U15)
    assert seg["frames_recorded"].tolist() == [5, 5] and seg["tracking_errors"].tolist() == [0, 1]
    assert seg["end_loss"].tolist() == [-1, -1] and seg["frames_received"].tolist() == [5, -1]
    assert run["mt"]["track_error"].tolist()[-1] == 1 and "writer_tracking_error" in run["events"]
    assert run["recordings"]["name"].tolist() == ["r1", "r2"]
    assert run["recordings"]["off_buffer"].tolist() == [3, -1]
    assert "warning" in h5py.File(tmp_path / "s.h5", "r")["metadata/run/frame_rate_hz"].attrs
    m = legacy_matrix(tmp_path / "s.h5")
    assert sorted(m) == [1, 2] and m[1][:, 0].tolist() == [0, 1, 2, 3, 4] and m[2][:, 0].tolist() == [0, 1, 2, 3]


def test_export_tra_roundtrip_against_reader(tmp_path):
    _write(tmp_path / "x.h5", "events first")
    run = read_run(tmp_path / "x.h5")
    paths = export_tra(tmp_path / "x.h5")
    assert paths == [tmp_path / "x-000"]
    hdr, rows = read_tra(paths[0])
    keep = run["mt"]["dropped"] == 0
    assert rows.shape == (keep.sum(), 3 + 3 * 2)
    assert rows[:, 0].tolist() == run["mt"]["buffer_number"][keep].astype(float).tolist()   # first buffer is 0
    np.testing.assert_array_equal(rows[:, 1], run["mt"]["magnet_mm"][keep])
    for i in range(2):
        np.testing.assert_array_equal(rows[:, 3 + 3 * i], run["mt"]["x_px"][keep, i])
        np.testing.assert_array_equal(rows[:, 4 + 3 * i], run["mt"]["y_px"][keep, i])
        np.testing.assert_array_equal(rows[:, 5 + 3 * i], run["mt"]["z_um"][keep, i])
    lines = hdr.split("\n")
    assert lines[1] == "Raw data file of N bead xyz trace" and lines[5] == f"actual data points/nominal: {len(rows)}/2000000"
    with pytest.raises(FileExistsError):
        export_tra(tmp_path / "x.h5")
    split = export_tra(tmp_path / "x.h5", base=tmp_path / "y", nominal=5)
    assert [p.name for p in split] == ["y-000", "y-001"] and read_tra(split[1])[0].split("\n")[4] == "file 1 of a series"


def test_magnet_reading_arriving_after_frames(tmp_path):
    w = HDF5Writer(tmp_path / "m.h5", flush_frames=1000, flush_s=1000)
    w.write_event(rec_on(0.0))
    w.write_frame(frame(1, 0, 0.5))
    w.write_frame(frame(1, 1, 1.5))
    w.write_event(ev(1.0, "act", {"quantity": "magnet_position_mm", "value": 7.0}, 7.0))   # logged at 1.0 s
    w.write_event(ev(1.2, "act", {"quantity": "rotor_turns", "value": 0.5}, 0.5))
    w.close()
    mt = read_run(tmp_path / "m.h5")["mt"]
    assert np.isnan(mt["magnet_mm"][0]) and mt["magnet_mm"][1] == 7.0 and mt["rotor_deg"][1] == 180.0


_CRASH = r"""
import os, sys, time
sys.path.insert(0, sys.argv[2])
from test_data import HDF5Writer, frame, rec_on
w = HDF5Writer(sys.argv[1], flush_frames=10**6, flush_s=10**6)
w.write_event(rec_on(0.0))
for b in range(100):
    w.write_frame(frame(1, b, 0.1 + b / 90))
w.flush()
if sys.argv[3] == "new group":    # an event of a kind not seen before: its group is created at once, then a crash
    from test_data import ev
    w.write_event(ev(2.0, "never_seen_kind", text="x"))
else:
    for b in range(100, 140):
        w.write_frame(frame(1, b, 0.1 + b / 90))
os._exit(1)                       # a crash: no close, nothing flushed after the 100 rows
"""


@pytest.mark.parametrize("mode", ["unflushed rows", "new group"])
def test_crash_keeps_everything_up_to_the_last_flush(tmp_path, mode):
    """Tested crash points only: after a flush with 40 rows waiting in memory, and right after a new event-kind
    group was created in the file. A crash during a flush itself is not tested (WP6 carry)."""
    script = tmp_path / "crash.py"
    script.write_text(_CRASH, encoding="utf-8")
    p = subprocess.run([sys.executable, str(script), str(tmp_path / "c.h5"), str(Path(__file__).parent), mode],
                       check=False, capture_output=True, text=True, timeout=60, cwd=str(REPO))
    assert p.returncode == 1, p.stderr
    with h5py.File(tmp_path / "c.h5", "r") as f:
        assert f.attrs["closed_cleanly"] == 0 and f.attrs["frames_written"] == 100
        assert f["mt/buffer_number"][()].tolist() == list(range(100))
        assert f["segments/frames_recorded"][0] == 100
        assert f["events/recording/event_id"].shape == (1,)


def test_frames_outside_accepted_intervals_reported_at_close(tmp_path):
    """Review l2s-wp4-r1 fix 2: refused on -> frames -> accepted on (at buffer 4) -> frames -> off (at 7) ->
    a frame after the off. Only frames inside (on, off] are written; the others are reported at close."""
    w = HDF5Writer(tmp_path / "i.h5")
    with pytest.raises(RecordingRefused):
        w.write_event(rec_on(0.0, name="bad", settings={"roi": ROI}))
    for b in range(5):
        w.write_frame(frame(1, b, 0.1 + b / 90))               # covered by no accepted recording
    w.write_event(rec_on(0.2, buf=4, name="good"))
    for b in range(5, 8):
        w.write_frame(frame(1, b, 0.1 + b / 90))
    w.write_event(ev(0.3, "recording", action="off", name="good", segment=1, buffer_number=7))
    w.write_frame(frame(1, 9, 0.4))                             # after the off, no later on
    with pytest.raises(RecordingRefused, match="6 recorded frames not written"):
        w.close()
    with h5py.File(tmp_path / "i.h5", "r") as f:
        assert f["mt/buffer_number"][()].tolist() == [5, 6, 7]
        assert f.attrs["frames_not_written"] == 6 and f.attrs["frames_outside_recordings"] == 0
        assert f.attrs["closed_cleanly"] == 1 and f["segments/frames_recorded"][0] == 3


def test_frames_held_until_their_interval_arrives(tmp_path):
    """A frame that arrives before the on event placing it is held, then written (no order assumed)."""
    w = HDF5Writer(tmp_path / "h.h5")
    w.write_event(rec_on(0.0, name="r1"))
    w.write_frame(frame(1, 0, 0.1))
    w.write_event(ev(0.15, "recording", action="off", name="r1", segment=1, buffer_number=0))
    w.write_frame(frame(1, 3, 0.3))                             # belongs to r2, whose on has not arrived yet
    assert len(w._pending_frames) == 1
    w.write_event(rec_on(0.25, buf=2, name="r2"))
    w.close()
    assert read_run(tmp_path / "h.h5")["mt"]["buffer_number"].tolist() == [0, 3]


def _late_cal_file(path, cal_first):
    w = HDF5Writer(path, flush_frames=1)
    start = ev(0.0, "acquisition", action="start", cal=str(FIXTURE / "cal002"))
    if cal_first:
        w.write_event(start)
    w.write_event(rec_on(0.01))
    for b in range(3):
        w.write_frame(frame(1, b, 0.1 + b / 90, nb=5))          # flush_frames=1: /beads written without a .cal
    if not cal_first:
        assert w._mt.n >= 1 and w._cal is None
        w.write_event(start)
    w.close()
    return read_run(path)


def test_late_cal_applied_and_beads_rebuilt_order_independent(tmp_path):
    need(FIXTURE / "cal002")
    a = _late_cal_file(tmp_path / "a.h5", True)
    b = _late_cal_file(tmp_path / "b.h5", False)
    for k in a["beads"]:
        np.testing.assert_array_equal(a["beads"][k], b["beads"][k], err_msg=k)
    assert b["beads"]["role"].tolist() == ["reference"] + ["tethered"] * 4
    assert np.isfinite(b["beads"]["pick_xy_px"]).all()
    for k in ("xy_px", "stack", "exp_ref", "bandpass_forget", "cal_bytes", "sha256", "date"):
        np.testing.assert_array_equal(a["metadata"]["calibration"][k], b["metadata"]["calibration"][k], err_msg=k)
    assert a["attrs"]["legacy_cal_file"] == b["attrs"]["legacy_cal_file"] == str(FIXTURE / "cal002")
    assert (export_cal(tmp_path / "a.h5", tmp_path / "a.cal").read_bytes()
            == export_cal(tmp_path / "b.h5", tmp_path / "b.cal").read_bytes() == (FIXTURE / "cal002").read_bytes())


def _motor_file(path, event_first):
    w = HDF5Writer(path, flush_frames=2, flush_s=1000)
    move = ev(0.55, "act", {"quantity": "magnet_position_mm", "value": 7.0}, 7.0)
    w.write_event(rec_on(0.0))
    if event_first:
        w.write_event(move)
    for b, t in enumerate((0.5, 0.6, 0.7, 0.8, 0.9)):
        w.write_frame(frame(1, b, t))
    if not event_first:
        assert w._mt.n == 4                                      # rows at 0.6 .. 0.8 s already flushed
        w.write_event(move)
    w.close()
    return read_run(path)


def test_late_motor_reading_backfills_flushed_rows(tmp_path):
    a = _motor_file(tmp_path / "a.h5", True)
    b = _motor_file(tmp_path / "b.h5", False)
    assert np.isnan(b["mt"]["magnet_mm"][0]) and b["mt"]["magnet_mm"][1:].tolist() == [7.0] * 4
    np.testing.assert_array_equal(a["mt"]["magnet_mm"], b["mt"]["magnet_mm"])
    np.testing.assert_allclose(a["mt"]["magnet_t"] + a["attrs"]["t0_unix"], b["mt"]["magnet_t"] + b["attrs"]["t0_unix"],
                               rtol=0, atol=1e-6)


def test_file_written_with_hdf5_1_8_upper_bound(tmp_path):
    w = HDF5Writer(tmp_path / "y.h5")
    w.write_event(rec_on(0.0))
    assert w.f.libver == ("earliest", "v108")
    w.write_frame(frame(1, 0, 0.1))
    w.close()
    assert read_run(tmp_path / "y.h5")["attrs"]["closed_cleanly"] == 1


def test_matlab_reader_reads_existing_datasets(tmp_path):
    """The MATLAB reader cannot run here; check that every column it names exists in a written file."""
    _write(tmp_path / "x.h5", "events first")
    src = (REPO / "matlab" / "read_mtpy_h5.m").read_text(encoding="utf-8")
    used = set(re.findall(r"run\.(mt|segments|beads)\.(\w+)", src))
    assert {("mt", "x_px"), ("segments", "first_buffer")} <= used
    with h5py.File(tmp_path / "x.h5", "r") as f:
        for g, name in used:
            assert f"{g}/{name}" in f, (g, name)
        assert f["mt/x_px"].shape == (9, 2)                     # [frames, beads]; MATLAB transposes back


# --- through the API on the simulated rig ------------------------------------------------------------------------------
def test_api_record_rate_change_two_segments(cam, tmp_path):
    api.acq.start(record=True, name="run1", folder=tmp_path)
    api.acq.wait_frames(30, 5)
    api.camera.set_rate(60.0, confirm=True)
    api.acq.wait_frames(30, 5)
    st = api.acq.stop()
    assert st["stop"] == "complete" and st["sink_failures"] == 0, st["sink_error"]
    run = api.data.open_run(tmp_path / "run1.h5")
    seg = run["segments"]
    assert seg["number"].tolist() == [1, 2] and seg["reason"].tolist() == ["start", "settings change"]
    assert seg["rate_Hz"][0] == pytest.approx(90.0009, rel=1e-5) and seg["rate_Hz"][1] == pytest.approx(60.0, rel=1e-4)
    assert np.isfinite(seg["rate_Hz_measured"]).all() and np.isfinite(seg["gain_dB"]).all()
    assert seg["rate_Hz_measured"][1] == pytest.approx(60.0, rel=1e-3)
    for i, s in enumerate(st["segments"]):
        assert seg["frames_recorded"][i] == s["frames_received"] == seg["frames_received"][i]
        assert seg["first_buffer"][i] == 0 and seg["last_buffer"][i] == s["last_buffer"]
        b = run["mt"]["buffer_number"][run["mt"]["segment"] == i + 1]
        assert sorted(b.tolist()) == list(range(s["last_buffer"] + 1))
    assert run["attrs"]["closed_cleanly"] == 1 and "guarded_change" in run["events"]
    assert run["recordings"]["name"].tolist() == ["run1"]
    assert run["metadata"]["devices"]["jai"]["identity"]


def test_api_recording_started_later_keeps_rate_and_settings(cam, tmp_path):
    api.acq.start(record=False, name="late", folder=tmp_path)
    api.acq.wait_frames(10, 5)
    api.camera.set_exposure(4.0)                              # while exploring: its event is not recorded
    api.camera.set_gain(6.0)
    api.acq.set_recording(True, name="late")
    api.acq.wait_frames(20, 5)
    api.acq.stop()
    seg = api.data.open_run(tmp_path / "late.h5")["segments"]
    assert seg["rate_Hz"][0] == pytest.approx(90.0009, rel=1e-5)          # U15: never missing
    assert seg["exposure_ms"][0] == pytest.approx(4.0) and seg["gain_dB"][0] == pytest.approx(6.0)


def test_api_drops_and_gaps_visible_in_file(cam, tmp_path, monkeypatch):
    monkeypatch.setattr(api.acq, "_make_kernel", lambda beads: SlowKernel())
    monkeypatch.setattr(api.beads, "_selected", Beads((1,), np.array([[640.0, 512.0]]), [], 120, None, None, "test"))
    cam.device.drop_every = 10
    api.acq.start(record=True, name="drops", folder=tmp_path, ring_capacity=8)
    api.acq.wait_frames(100, 30)
    st = api.acq.stop()
    run = read_run(tmp_path / "drops.h5")
    mt, seg = run["mt"], run["segments"]
    assert st["pipeline_drops"] > 20 and st["camera_gaps"] > 5
    assert int(mt["dropped"].sum()) == st["pipeline_drops"] == seg["frames_dropped"][0] == seg[
        "pipeline_drops_segment"][0]
    assert int(mt["lost_before"].sum()) == st["camera_gaps"] == seg["camera_gaps"][0]
    assert np.isnan(mt["x_px"][mt["dropped"] == 1]).all()
    assert len(mt["buffer_number"]) == st["frames_received"]                # every received frame is a row


def test_api_recording_on_missing_setting_refused_before_flag(cam, tmp_path, monkeypatch):
    """Review l2s-wp4-r1 fix 1: a settings read without gain refuses the second recording before the flag
    changes; no frame of it reaches the file."""
    api.acq.start(record=True, name="two", folder=tmp_path)
    api.acq.wait_frames(10, 5)
    api.acq.set_recording(False)
    real = cam.device.settings
    monkeypatch.setattr(cam.device, "settings", lambda: {k: v for k, v in real().items() if k != "gain_dB"})
    n = len(api.events.events())
    with pytest.raises(api.NotReady, match="lack"):
        api.acq.set_recording(True, name="second")
    st = api.acq.status()
    assert not st["recording"] and not cam.recording
    assert [e.kind for e in api.events.events()[n:]] == ["refused"]
    api.acq.wait_frames(10, 5)
    monkeypatch.setattr(cam.device, "settings", real)
    st = api.acq.stop()
    assert st["sink_failures"] == 0, st["sink_error"]
    with h5py.File(tmp_path / "two.h5", "r") as f:
        assert f.attrs["frames_not_written"] == 0 and f.attrs["frames_outside_recordings"] == 0
        assert f["recordings/name"].asstr()[()].tolist() == ["two"]
        assert f["mt/buffer_number"][-1] == f["recordings/off_buffer"][0]


@pytest.mark.parametrize("missing", ["roi", "gain_dB"])
def test_api_start_record_missing_setting_refused_first(cam, tmp_path, monkeypatch, missing):
    """Review l2s-wp4-r2: start(record=True) checks the four settings before the sink, the ROI or the pipeline."""
    monkeypatch.setattr(api.beads, "_selected", Beads((1,), np.array([[640.0, 512.0]]), [], 120, None, None, "test"))
    real = cam.device.settings
    monkeypatch.setattr(cam.device, "settings", lambda: {k: v for k, v in real().items() if k != missing})
    n = len(api.events.events())
    with pytest.raises(api.NotReady, match="lack"):
        api.acq.start(record=True, name="norec", folder=tmp_path)
    assert [e.kind for e in api.events.events()[n:]] == ["refused"]
    assert not api.acq.running() and not cam.device.acquiring() and not cam.recording
    assert not list(tmp_path.glob("*.h5"))


def test_late_off_reports_written_rows_outside(tmp_path):
    """An off event that arrives after frames beyond it were written: the rows stay, their count is reported."""
    w = HDF5Writer(tmp_path / "o.h5", flush_frames=1)
    w.write_event(rec_on(0.0))
    for b in range(6):
        w.write_frame(frame(1, b, 0.1 + b / 90))               # interval still open-ended: all written
    w.write_event(ev(0.2, "recording", action="off", name="r1", segment=1, buffer_number=2))
    with pytest.raises(RecordingRefused, match="3 written rows outside"):
        w.close()
    with h5py.File(tmp_path / "o.h5", "r") as f:
        assert f.attrs["frames_outside_recordings"] == 3 and f.attrs["frames_not_written"] == 0
        assert f["mt/buffer_number"].shape == (6,) and f.attrs["closed_cleanly"] == 1


def test_api_existing_file_refused(cam, tmp_path):
    (tmp_path / "taken.h5").write_bytes(b"")
    with pytest.raises(api.NotReady, match="exists"):
        api.acq.start(record=True, name="taken", folder=tmp_path)
    assert not api.acq.running()


# --- recorded fixture -------------------------------------------------------------------------------------------------
def test_fixture_replay_export_tra_and_cal(fixture_cam, tmp_path):
    api.camera.set_rate(90.0)
    api.beads.select([1, 2, 3, 4, 5])
    api.acq.start(record=True, name="tra900", folder=tmp_path)
    api.acq.wait_frames(90, 30)
    st = api.acq.stop()
    assert st["pipeline_drops"] == 0 and st["sink_failures"] == 0, st["sink_error"]
    h5 = tmp_path / "tra900.h5"
    run = read_run(h5)
    assert run["beads"]["role"].tolist() == ["reference"] + ["tethered"] * 4        # cal002 exp/ref flags 0,1,1,1,1
    assert run["beads"]["role_source"][0].startswith("cal exp/ref flag")
    np.testing.assert_array_equal(run["beads"]["pick_xy_px"], read_cal(FIXTURE / "cal002")["xy"][:, :2])
    sink_rows = len(run["mt"]["buffer_number"])
    [tra] = export_tra(h5)
    hdr, rows = read_tra(tra)
    assert len(rows) == sink_rows and rows.shape[1] == 3 + 15 and str(FIXTURE / "cal002") in hdr
    np.testing.assert_array_equal(rows[:, 5::3], run["mt"]["z_um"])
    cal = export_cal(h5, tmp_path / "cal_copy")
    assert cal.read_bytes() == (FIXTURE / "cal002").read_bytes()


def test_cal_stored_from_acquisition_start_event(tmp_path):
    need(FIXTURE / "cal002")
    w = HDF5Writer(tmp_path / "c.h5")
    w.write_event(ev(0.0, "acquisition", action="start", cal=str(FIXTURE / "cal002")))
    w.write_event(rec_on(0.01))
    w.write_frame(frame(1, 0, 0.1, nb=5))
    w.close()
    run = read_run(tmp_path / "c.h5")
    assert run["metadata"]["calibration"]["exp_ref"].tolist() == [0, 1, 1, 1, 1]
    assert run["beads"]["role"][0] == "reference"
    assert export_cal(tmp_path / "c.h5", tmp_path / "c.cal").read_bytes() == (FIXTURE / "cal002").read_bytes()
