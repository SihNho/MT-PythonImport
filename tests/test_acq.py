"""WP3: the acquisition pipeline (camera -> ring -> tracking -> sink) on the simulators. Tests marked by the `replay`
fixture need the recorded G: fixture and skip without it; the others run on the synthetic camera."""
import threading
import time

import numpy as np
import pytest
from conftest import FIXTURE, need
from test_devices import _config

from mtpy import api
from mtpy.acq import Beads, FrameRing, MemorySink
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


def _no_poll(evs):
    """Events without the motor poller's normal readings (WP6): they arrive at ~20 Hz from their own thread while
    acquisition runs, so a test that lists event kinds leaves them out. A `motor_reading_error` stays visible
    (review l2s-wp6-r1)."""
    return [e for e in evs if e.kind != "motor_reading"]


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
    monkeypatch.setattr(api.acq, "_make_kernel", lambda beads, *_: SlowKernel())
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
    evs = _no_poll(sink.events)
    kinds = [e.kind for e in evs]
    assert kinds[0] == "recording" and kinds[-1] == "recording" and "mark" in kinds, kinds
    assert evs[0].extra["action"] == "on" and evs[0].extra["name"] == "r1"
    assert evs[-1].extra["action"] == "off" and sink.closed
    on, off = evs[0].extra["buffer_number"], evs[-1].extra["buffer_number"]
    # exactly the frames received after the 'on' event up to the 'off' event (one segment, no drops, no gaps)
    assert [r.record.buffer_number for r in sink.frames] == list(range(on + 1, off + 1))
    assert off - on >= 20 and len(sink.frames) < st["frames_received"] and all(r.record.recording for r in sink.frames)


def test_average_runs_at_the_camera_rate_not_the_display_tap(cam):
    api.camera.set_rate(150.0)
    api.acq.start()
    api.acq.wait_frames(15, 5)
    t0 = time.perf_counter()
    img = api.acq.average(60)                                     # 60 frames: 0.4 s at 150 fps, 2 s from the tap
    dt = time.perf_counter() - t0
    shape = api.acq.display().image.shape
    api.acq.stop()
    assert img.dtype == np.float64 and img.shape == shape and dt < 1.2
    with pytest.raises(NotReady):
        api.acq.average(1)


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


# --- review l2s-wp3-r1 fixes ------------------------------------------------------------------------------------------
class StubKernel:
    """Stands in for FastKernel: returns the input positions after `delay_s`."""

    def __init__(self, delay_s=0.0):
        self.delay_s = delay_s

    def track(self, image, xin, yin, good_in):
        if self.delay_s:
            time.sleep(self.delay_s)
        n = len(xin)
        return np.column_stack([xin, yin, np.zeros(n)]).astype(float), np.zeros(n, dtype=np.int64), np.ones(n, bool)


def _stub_beads(monkeypatch, delay_s=0.0):
    """One bead at (640, 512), cross 120 -> tracking window half-size 72 px."""
    monkeypatch.setattr(api.acq, "_make_kernel", lambda beads, *_: StubKernel(delay_s))
    monkeypatch.setattr(api.beads, "_selected", Beads((1,), np.array([[640.0, 512.0]]), [], 120, None, None, "test"))


class SlowSink(MemorySink):
    def write_frame(self, result):
        time.sleep(0.05)
        super().write_frame(result)


def _all_buffers(res, seg):
    return sorted(r.record.buffer_number for r in res) == list(range(seg["last_buffer"] + 1))


def test_stop_timeout_slow_worker_keeps_incomplete_pipeline(cam, monkeypatch):
    _stub_beads(monkeypatch, delay_s=0.3)
    api.acq.start(record=True, ring_capacity=8)
    api.acq.wait_frames(30, 5)
    n = len(events.events())
    st = api.acq.stop(timeout_s=0.1)
    assert st["running"] and st["stop"].startswith("incomplete") and "acq-tracking" in st["stop"], st["stop"]
    assert api.acq.running() and not api.acq.sink().closed           # no end marker sent, reference kept
    assert not cam.device.acquiring() and not st["recording"]
    assert any(e.kind == "acquisition" and e.extra.get("action") == "stop incomplete" for e in events.events()[n:])
    with pytest.raises(NotReady, match="stopping"):
        api.acq.set_recording(True)
    with pytest.raises(NotReady, match="already running"):
        api.acq.start()
    st = api.acq.stop(timeout_s=30)                                   # resumes the draining
    assert st["stop"] == "complete" and not st["running"] and not api.acq.running()
    sink = api.acq.sink()
    assert sink.closed and _all_buffers(sink.frames, st["segments"][0])
    assert sum(r.dropped for r in sink.frames) == st["pipeline_drops"] == st["frames_received"] - st["frames_tracked"]
    ends = [e for e in sink.events if e.kind == "segment" and e.extra["action"] == "end"]
    last = _no_poll(sink.events)[-1]
    assert len(ends) == 1 and last.kind == "recording" and last.extra["action"] == "off"


def test_stop_timeout_slow_sink_keeps_incomplete_pipeline(cam):
    sink = SlowSink()
    api.acq.start(record=True, sink=sink)
    api.acq.wait_frames(45, 5)
    st = api.acq.stop(timeout_s=0.2)
    assert st["running"] and "acq-sink" in st["stop"] and not sink.closed, st["stop"]
    n_before = len(sink.frames)
    st = api.acq.stop(timeout_s=30)
    assert st["stop"] == "complete" and sink.closed and len(sink.frames) > n_before
    assert _all_buffers(sink.frames, st["segments"][0]) and st["pipeline_drops"] == 0


@pytest.mark.parametrize("change", [
    lambda: api.camera.set_roi(8, 0, 1272, 1024),                               # ROI move (origin changes)
    lambda: api.camera.set_roi(0, 0, 640, 512),                                 # ROI shrink: bead window outside
    lambda: api.camera.apply_preset({"name": "moved", "roi": (0, 8, 1280, 1016)}),
    lambda: api.camera.apply_preset({"name": "small", "roi": (0, 0, 704, 1024), "exposure_ms": 2.0}),
], ids=["set_roi-move", "set_roi-shrink", "preset-move", "preset-shrink"])
def test_roi_incompatible_with_beads_refused_before_stop(cam, monkeypatch, change):
    _stub_beads(monkeypatch)
    api.acq.start()
    api.acq.wait_frames(10, 5)
    n = len(events.events())
    with pytest.raises(SafetyRefused, match="beads"):
        change()
    new = _no_poll(events.events()[n:])
    assert [e.kind for e in new] == ["refused"], [e.kind for e in new]   # nothing paused, nothing sent
    assert cam.device.acquiring() and cam.device.get("roi") == (0, 0, 1280, 1024)
    assert cam.device.get("exposure_ms") == pytest.approx(1.909)
    f0 = api.acq.status()["frames_received"]
    api.acq.wait_frames(10, 5)
    st = api.acq.stop()
    assert len(st["segments"]) == 1 and st["frames_received"] > f0 and st["tracking_errors"] == 0


def test_roi_compatible_with_beads_allowed(cam, monkeypatch):
    _stub_beads(monkeypatch)
    api.acq.start()
    api.acq.wait_frames(10, 5)
    assert api.camera.set_roi(0, 0, 1024, 1024) == (0, 0, 1024, 1024)   # same origin, bead window still inside
    api.acq.wait_frames(10, 5)
    st = api.acq.stop()
    assert len(st["segments"]) == 2 and st["segments"][1]["roi"] == (0, 0, 1024, 1024) and st["tracking_errors"] == 0


def test_recording_on_carries_segment_and_settings_read_then(cam):
    api.acq.start(record=False)
    api.acq.wait_frames(10, 5)
    api.camera.set_exposure(4.0)                                  # changed while exploring (not recorded)
    api.camera.set_gain(6.0)
    api.acq.set_recording(True, name="r1")
    api.acq.wait_frames(10, 5)
    api.acq.set_recording(False)
    api.acq.set_recording(True, name="r2")                        # every 'on' carries both again
    api.acq.wait_frames(5, 5)
    api.acq.stop()
    ons = [e.extra for e in api.acq.sink().events if e.kind == "recording" and e.extra["action"] == "on"]
    assert [o["name"] for o in ons] == ["r1", "r2"]
    for o in ons:
        s = o["settings"]
        assert s["exposure_ms"] == pytest.approx(4.0) and s["gain_dB"] == pytest.approx(6.0)
        assert s["roi"] == (0, 0, 1280, 1024) and s["rate_Hz"] == pytest.approx(90.0009, rel=1e-5)
        seg = o["segment_info"]                                   # opened before the exposure change
        assert seg["number"] == o["segment"] == 1 and seg["exposure_ms"] == pytest.approx(1.909)
        assert o["segment_info"]["frames_received"] <= o["buffer_number"] + 1


def test_start_record_reuses_the_settings_read(cam, monkeypatch):
    dev, calls = cam.device, []
    real = dev.settings
    monkeypatch.setattr(dev, "settings", lambda: calls.append(1) or real())
    for record in (False, True):
        calls.clear()
        api.acq.start(record=record)
        n_start = len(calls)
        api.acq.wait_frames(5, 5)
        api.acq.stop()
        assert n_start == 1, (record, n_start)                     # no second read for the snapshot
    on = next(e.extra for e in api.acq.sink().events if e.kind == "recording")
    assert on["settings"]["exposure_ms"] == pytest.approx(1.909) and on["segment_info"]["number"] == 1


def test_settings_read_failure_refuses_recording_acquisition_continues(cam, monkeypatch):
    api.acq.start(record=False)
    api.acq.wait_frames(10, 5)

    real, broken_on = cam.device.settings, [True]

    def broken():
        if broken_on[0]:
            raise TimeoutError("no reply")
        return real()
    monkeypatch.setattr(cam.device, "settings", broken)
    n = len(events.events())
    f0 = api.acq.status()["frames_received"]
    d0 = api.acq.status()["display_updates"]
    with pytest.raises(NotReady, match="settings could not be read back"):
        api.acq.set_recording(True, name="r1")
    st = api.acq.status()
    assert not st["recording"] and not cam.recording and st["running"]
    refused = [e for e in events.events()[n:] if e.kind == "refused"]
    assert len(refused) == 1 and refused[0].request == {"recording": "on", "name": "r1"}
    assert not any(e.kind == "recording" for e in events.events()[n:])
    api.acq.wait_frames(30, 5)
    st = api.acq.status()
    assert st["frames_received"] >= f0 + 30 and st["display_updates"] > d0
    broken_on[0] = False
    api.acq.stop()
    assert api.acq.sink().frames == [] and api.acq.sink().events == []


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


class _DiskFullSink(MemorySink):
    def write_frame(self, result):
        raise OSError(28, "No space left on device")


def test_sink_io_failure_switches_recording_off_with_an_event(cam):
    """Fault list P1: disk full while recording -> one `acquisition fault` event, recording off, acquisition and
    display go on (the first failure is counted, nothing more is fed to the sink)."""
    n0 = len(events.events())
    api.acq.start(record=True, name="full", sink=_DiskFullSink())
    t0 = time.time()
    while api.acq.status()["recording"] and time.time() - t0 < 15:     # generous: the sim camera slows under load
        time.sleep(0.02)
    st = api.acq.status()
    assert st["running"] and not st["recording"] and st["sink_failures"] >= 1 and "No space left" in st["sink_error"]
    faults = [e for e in events.events()[n0:] if e.kind == "acquisition" and e.extra.get("action") == "fault"]
    assert len(faults) == 1 and faults[0].extra["source"] == "sink" and "OSError" in faults[0].extra["error"]
    assert [e.extra.get("action") for e in events.events()[n0:] if e.kind == "recording"] == ["on", "off"]
    received = st["frames_received"]
    assert api.acq.wait_frames(5, 5) and api.acq.status()["frames_received"] > received


def test_camera_thread_death_is_visible_in_status_and_as_an_event(cam):
    """Fault list D13: an exception in next_frame used to end the camera thread silently while running() stayed True."""
    n0 = len(events.events())
    api.acq.start()
    api.acq.wait_frames(3, 5)

    def boom(timeout_s):
        raise RuntimeError("frame path broke")
    cam.device.next_frame = boom
    t0 = time.time()
    while api.acq.status()["camera_error"] is None and time.time() - t0 < 5:
        time.sleep(0.02)
    st = api.acq.status()
    assert st["running"] and st["camera_error"] == "RuntimeError: frame path broke"
    faults = [e for e in events.events()[n0:] if e.kind == "acquisition" and e.extra.get("action") == "fault"]
    assert len(faults) == 1 and faults[0].extra["source"] == "camera"
    assert api.acq.stop()["camera_error"] == "RuntimeError: frame path broke"
