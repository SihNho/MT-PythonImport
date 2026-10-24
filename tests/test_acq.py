"""WP3: the acquisition pipeline (camera -> ring -> tracking -> sink) on the simulators. Tests marked by the `replay`
fixture need the recorded G: fixture and skip without it; the others run on the synthetic camera."""
import threading
import time

import numpy as np
import pytest
from conftest import FIXTURE, need
from test_devices import _config

from mtpy import api
from mtpy.acq import Beads, FrameRing
from mtpy.api import estop, events
from mtpy.api.errors import NotReady, SafetyRefused
from mtpy.track import Tracker

TOL_XY, TOL_Z, TOL_BAD = 1e-6, 1e-4, 1e-4        # as tests/test_track_replay.py


def _connect(tmp_path, monkeypatch, fixture=None):
    _config(tmp_path, monkeypatch, test_limits=True)
    monkeypatch.setattr(api.beads, "_selected", None)
    with events.as_caller("gui"):
        estop.clear()
        api.devices.connect({"backend": "sim", "fixture": fixture})
    yield api.devices.service("camera")
    if api.acq.running():
        api.acq.stop()
    api.devices.disconnect()
    with events.as_caller("gui"):
        estop.clear()


@pytest.fixture
def cam(tmp_path, monkeypatch):
    """Simulated rig with the synthetic camera (no G: data needed)."""
    yield from _connect(tmp_path, monkeypatch)


@pytest.fixture
def fixture_cam(tmp_path, monkeypatch):
    """Simulated rig replaying the recorded fixture frames."""
    need(FIXTURE / "cal002", FIXTURE / "img00004.tif")
    yield from _connect(tmp_path, monkeypatch, str(FIXTURE))


def _offline(files, results, beads):
    """Run the reference port track.Tracker over the same frames, in order, and compare every result."""
    from PIL import Image
    t = Tracker(beads.xy0, beads.cross, beads.win_rs, beads.win_h, beads.cals)
    worst_bad = 0.0
    for r in results:
        img = np.asarray(Image.open(files[r.record.buffer_number % len(files)]))
        xyz = t.step(img)
        np.testing.assert_array_equal(r.xyz == -1.0, xyz == -1.0, err_msg=f"buffer {r.record.buffer_number}")
        np.testing.assert_array_equal(r.good, t.good, err_msg=f"buffer {r.record.buffer_number}")
        d = np.abs(r.xyz - xyz)
        good = t.good
        assert d[good, :2].max(initial=0) < TOL_XY and d[good, 2].max(initial=0) < TOL_Z, (r.record, d)
        worst_bad = max(worst_bad, d[~good].max(initial=0.0))
    assert worst_bad < TOL_BAD


def _run(n_frames, timeout_s=30, **start):
    api.acq.start(**start)
    api.acq.wait_frames(n_frames, timeout_s)
    return api.acq.stop()


# --- ring buffer ------------------------------------------------------------------------------------------------------
def test_ring_drops_oldest_and_reports_it():
    ring = FrameRing(2)
    assert ring.push("a", "ra") is None and ring.push("b", "rb") is None
    assert ring.push("c", "rc") == "ra"                       # full: the oldest unprocessed frame goes
    assert ring.pop(0) == ("b", ["ra"])                       # the worker learns about the drop with its next pop
    assert ring.pop(0) == ("c", []) and ring.pop(0) == (None, [])


# --- end-to-end replay ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("rate_Hz", "seconds"), [(90.0, 2.0), (150.0, 2.0)])
def test_replay_matches_offline_tracker(fixture_cam, rate_Hz, seconds):
    api.camera.set_rate(rate_Hz)
    api.beads.select([1, 2, 3, 4, 5])
    st = _run(int(rate_Hz * seconds), record=True)
    assert st["pipeline_drops"] == 0 and st["camera_gaps"] == 0 and st["tracking_errors"] == 0, st
    assert st["fps_measured"] == pytest.approx(rate_Hz, rel=1e-3)
    res = api.acq.sink().frames
    assert [r.record.buffer_number for r in res] == list(range(len(res))) and len(res) >= rate_Hz * seconds
    assert all(r.record.segment == 1 and r.record.rate_Hz == pytest.approx(rate_Hz, rel=1e-4) for r in res)
    _offline(fixture_cam.device.files, res, api.beads.selected())
    last = api.tracking.latest(1)
    assert last["buffer_number"] == res[-1].record.buffer_number and last["x_px"] == res[-1].xyz[0, 0]
    assert last["uncertainty"] is None and last["uncertainty_note"] == "not yet computed"


def test_replay_lost_bead_rule(fixture_cam):
    """The end of the recording, where beads are lost: -1 and the restart from the calibration positions as in
    track.Tracker."""
    dev = fixture_cam.device
    dev.files = dev.files[-60:]
    api.camera.set_rate(150.0)
    api.beads.select([1, 2, 3, 4, 5])
    st = _run(60, record=True)
    assert st["pipeline_drops"] == 0, st
    res = api.acq.sink().frames
    assert any((r.xyz == -1.0).any() for r in res)              # the rule is exercised
    _offline(dev.files, res, api.beads.selected())


# --- drops, gaps, segments --------------------------------------------------------------------------------------------
class SlowKernel:
    """Stands in for FastKernel: every frame takes 50 ms (far beyond the 11 ms frame period at 90 Hz)."""

    def track(self, image, xin, yin, good_in):
        time.sleep(0.05)
        n = len(xin)
        return np.zeros((n, 3)), np.zeros(n, dtype=np.int64), np.ones(n, dtype=bool)


def test_slow_tracker_drops_are_pipeline_drops_camera_not_blocked(cam, monkeypatch):
    monkeypatch.setattr(api.acq, "_make_kernel", lambda beads: SlowKernel())
    monkeypatch.setattr(api.beads, "_selected", Beads((1,), np.array([[640.0, 512.0]]), [], 120, None, None, "test"))
    st = _run(135, record=True, ring_capacity=8)
    seg = st["segments"][0]
    assert st["pipeline_drops"] > 50 and st["tracking_errors"] == 0
    # the camera thread kept taking every frame from the camera's own buffer: no camera-side gap at all
    assert st["camera_gaps"] == 0 and seg["frames_received"] == seg["last_buffer"] + 1
    res = api.acq.sink().frames
    assert sorted(r.record.buffer_number for r in res) == list(range(seg["last_buffer"] + 1))
    assert sum(r.dropped for r in res) == st["pipeline_drops"] == st["frames_received"] - st["frames_tracked"]


def test_camera_gaps_counted_from_buffer_numbers(cam):
    cam.device.drop_every = 10                                   # the camera / driver loses every 10th buffer
    st = _run(100, record=True)
    last = st["segments"][0]["last_buffer"]
    missing = [b for b in range(last + 1) if b % 10 == 9]
    assert st["camera_gaps"] == len(missing) and st["pipeline_drops"] == 0
    got = {r.record.buffer_number: r.record.gap_before for r in api.acq.sink().frames}
    assert all(got[b + 1] == 1 for b in missing) and sum(got.values()) == len(missing)


def test_rate_change_starts_new_segment_keeps_buffer_numbers(cam):
    api.acq.start(record=True)
    api.acq.wait_frames(30, 5)
    with pytest.raises(SafetyRefused, match="confirm=True"):    # guarded while recording (U17) sees the flag
        api.camera.set_rate(60.0)
    api.camera.set_rate(60.0, confirm=True)
    api.acq.wait_frames(30, 5)
    st = api.acq.stop()
    s1, s2 = st["segments"]
    assert (s1["number"], s2["number"], s2["reason"]) == (1, 2, "settings change")
    assert s1["rate_Hz"] == pytest.approx(90.0009, rel=1e-5) and s2["rate_Hz"] == pytest.approx(60.0, rel=1e-4)
    assert s1["first_buffer"] == s2["first_buffer"] == 0          # original buffer numbers, restarted by the camera
    assert s2["pc_gap_s"] is not None and s2["pc_gap_s"] >= 0 and s2["start_pc_s"] >= s1["end_pc_s"]
    assert s1["end_loss"] is None and s2["end_loss"] is None and st["unknown_loss_segments"] == 2
    res = api.acq.sink().frames
    by_seg = {k: [r.record.buffer_number for r in res if r.record.segment == k] for k in (1, 2)}
    assert by_seg[1] == list(range(s1["last_buffer"] + 1)) and by_seg[2] == list(range(s2["last_buffer"] + 1))
    assert {r.record.rate_Hz for r in res if r.record.segment == 2} == {s2["rate_Hz"]}
    seg_events = [e.extra for e in api.acq.sink().events if e.kind == "segment"]
    assert [(e["action"], e["segment"]) for e in seg_events] == [("begin", 1), ("end", 1), ("begin", 2), ("end", 2)]
    assert seg_events[1]["end_loss"] == "unknown" and seg_events[2]["pc_gap_s"] == s2["pc_gap_s"]


def test_recording_on_off_events_and_guard_flag(cam):
    api.acq.start(record=False)                                   # exploration: nothing recorded
    api.acq.wait_frames(20, 5)
    assert api.acq.sink().frames == [] and api.acq.sink().events == []
    assert not cam.recording
    api.camera.set_rate(60.0)                                     # not recording: no confirmation needed
    api.acq.set_recording(True, name="r1")
    assert cam.recording
    api.acq.wait_frames(20, 5)
    api.acq.mark("buffer exchanged")
    api.acq.set_recording(False)
    assert not cam.recording
    api.acq.wait_frames(20, 5)
    st = api.acq.stop()
    sink = api.acq.sink()
    kinds = [e.kind for e in sink.events]
    assert kinds[0] == "recording" and kinds[-1] == "recording" and "mark" in kinds, kinds
    assert sink.events[0].extra["action"] == "on" and sink.events[0].extra["name"] == "r1"
    assert sink.events[-1].extra["action"] == "off" and sink.closed
    on, off = sink.events[0].extra["buffer_number"], sink.events[-1].extra["buffer_number"]
    # exactly the frames received after the 'on' event up to the 'off' event (one segment, no drops, no gaps)
    assert [r.record.buffer_number for r in sink.frames] == list(range(on + 1, off + 1))
    assert off - on >= 20 and len(sink.frames) < st["frames_received"] and all(r.record.recording for r in sink.frames)


def test_display_tap_about_30_Hz_and_does_not_slow_acquisition(cam):
    api.camera.set_rate(150.0)
    api.acq.start()
    seen, stop = [], threading.Event()

    def gui():                                                    # a GUI reading the tap as often as it can
        while not stop.is_set():
            s = api.acq.display()
            if s is not None and (not seen or s.seq != seen[-1]):
                seen.append(s.seq)
            time.sleep(0.001)
    reader = threading.Thread(target=gui, daemon=True)
    reader.start()
    api.acq.wait_frames(15, 5)
    u0, t0 = api.acq.status()["display_updates"], time.perf_counter()
    api.acq.wait_frames(300, 10)
    rate = (api.acq.status()["display_updates"] - u0) / (time.perf_counter() - t0)
    stop.set()
    reader.join()
    st = api.acq.stop()
    assert 24 <= rate <= 36, rate
    assert seen == sorted(seen) and len(seen) > 30
    assert st["pipeline_drops"] == 0 and st["camera_gaps"] == 0
    assert st["fps_measured"] == pytest.approx(150.0, rel=1e-3)


def test_estop_stops_motion_acquisition_continues(cam):
    """Decision 0007: the emergency stop halts motion; it does not stop acquisition or recording."""
    api.acq.start(record=True)
    m = api.magnet.move_to(30.0, speed_mm_s=1.0)
    api.acq.wait_frames(20, 5)
    estop.engage("test")
    with pytest.raises(NotReady, match="emergency stop"):
        m.wait(5)
    n0 = api.acq.status()["frames_received"]
    api.acq.wait_frames(45, 5)                                    # frames keep coming while the stop is engaged
    st = api.acq.status()
    assert st["running"] and st["recording"] and st["frames_received"] >= n0 + 45
    api.acq.stop()
    kinds = [e.kind for e in api.acq.sink().events]
    assert "estop" in kinds and "cancelled" in kinds
    assert api.acq.sink().frames[-1].record.buffer_number > n0


def test_select_and_start_refusals(cam):
    with pytest.raises(NotReady, match="cal"):                    # synthetic camera: no fixture cal file
        api.beads.select([1])
    api.acq.start()
    with pytest.raises(NotReady, match="already running"):
        api.acq.start()
    with pytest.raises(NotReady, match="tracked"):
        api.tracking.latest(1)
    api.acq.stop()
    with pytest.raises(NotReady, match="not running"):
        api.acq.mark("x")
