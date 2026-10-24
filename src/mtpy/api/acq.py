"""Acquisition and recording (docs/design/api.md 2.3), WP3: camera -> ring buffer -> tracking -> results sink.

    api.beads.select([1, 2, 3, 4, 5])
    api.acq.start(record=False)          # exploration: live image and tracking, nothing recorded (U17)
    api.acq.set_recording(True, name="run01")
    api.acq.wait_frames(n=900, timeout_s=15)
    api.acq.mark("buffer exchanged")
    api.acq.stop()

- Every camera start opens a new **segment** (also the restart inside `api.camera.set_rate` / `set_roi`); buffer
  numbers are kept as the camera gives them, the rate and ROI read back are recorded per segment, the loss at a
  segment end is unknown (None), and the PC time between segments is recorded (WP3 frame contract).
- **Recording** on / off is an event; while it is on, the camera's "guarded while recording" settings (rate, ROI)
  need `confirm=True` (U17). Recorded frames and every event logged while recording go to the results sink.
- **Emergency stop**: decision 0007 stops motion only; acquisition (an observation, not a motion) keeps running and
  `start` is allowed while the stop is engaged, so the data keep showing what happens after a stop.
"""
import numpy as np

from mtpy.acq import Pipeline, make_kernel

from . import beads as _beads
from . import events
from .devices import _services, service
from .errors import NotReady, Timeout

_pipe = None          # the running Pipeline
_last = None          # the last finished one (status, sink and latest stay readable after stop)
_svc = None           # the camera service of the running acquisition
_make_kernel = make_kernel
SNAPSHOT_FIELDS = ("roi", "rate_Hz", "exposure_ms", "gain_dB")   # = api.camera.PRESET_FIELDS (no import: cycle)


def running():
    return _pipe is not None


def _require():
    if _pipe is None:
        raise NotReady("acquisition is not running; api.acq.start() first")
    return _pipe


def _seg_event(action, seg):
    if seg is not None:
        events.log("segment", action=action, segment=seg.number, reason=seg.reason, rate_Hz=seg.rate_Hz,
                   roi=seg.roi, exposure_ms=seg.exposure_ms, t_source=seg.t_source, pc_gap_s=seg.pc_gap_s,
                   first_buffer=seg.first_buffer, last_buffer=seg.last_buffer, frames_received=seg.frames_received,
                   camera_gaps=seg.camera_gaps, pipeline_drops=seg.pipeline_drops,
                   end_loss="unknown" if seg.end_loss is None else seg.end_loss)


def start(record=False, name=None, sink=None, ring_capacity=64, folder=None, roles=None):
    """Start acquisition (and tracking of the selected beads, if any). record=True also starts recording.

    name: the run name. sink: a `mtpy.acq.ResultSink`. folder (WP4): with no sink given, the recorded data go to the
    HDF5 v1 file `<folder>/<name>.h5` (`mtpy.data.HDF5Writer`; name None -> `run_<local time>`; an existing file is
    refused, NotReady); roles: {bead_id: "reference" | "tethered" | "candidate"} for that file. Neither sink nor
    folder -> an in-memory sink (read it with `api.acq.sink()`). NotReady if acquisition already runs, the camera is
    not connected or the selected beads do not fit the camera ROI. Returns status()."""
    global _pipe, _svc
    if _pipe is not None:
        raise NotReady("acquisition is already running")
    svc = service("camera")
    dev = svc.require()
    if svc.call(dev.acquiring, what="acquiring?"):
        raise NotReady("the camera is already acquiring outside api.acq")
    beads = _beads.selected()
    s = svc.call(dev.settings, what="read settings")
    if record:            # review l2s-wp4-r2: the four settings first, before any sink, ROI use or pipeline
        _settings_snapshot(name, s)
    if sink is None and folder is not None:
        sink = _hdf5_sink(folder, name, beads, roles, svc, dev, s)
    kernel = None
    if beads is not None:
        _, _, w, h = s["roi"]
        if not beads.fit((h, w)):
            raise NotReady(f"the selected beads do not fit the camera ROI {tuple(s['roi'])}; select beads again")
        kernel = _make_kernel(beads)
        # warm-up: numba compilation / cache load and its thread pool start here, not on the first frame
        kernel.track(np.zeros((h, w), dtype=np.uint8), np.rint(beads.xy0[:, 0]).astype(np.int64),
                     np.rint(beads.xy0[:, 1]).astype(np.int64), np.ones(len(beads.ids), dtype=bool))
    pipe = Pipeline(dev, beads, kernel, sink, ring_capacity, t_source=getattr(dev, "timestamp_source", "unknown"))
    pipe.start(events.subscribe)
    _pipe, _svc = pipe, svc
    try:
        seg = pipe.begin_segment(s)
        if record:
            set_recording(True, name, _settings=s)       # the read above is the snapshot: nothing ran in between
        events.log("acquisition", action="start", name=name, record=bool(record),
                   beads=list(pipe.bead_ids), cal=beads.source if beads is not None else None)
        _seg_event("begin", seg)
        svc.call(dev.start_acquisition, what="start acquisition")
    except BaseException:
        _finish()
        raise
    return status()


def _hdf5_sink(folder, name, beads, roles, svc, dev, settings):
    """The WP4 writer for start(folder=...): file name, beads and the camera's identity / settings at start."""
    import time
    from pathlib import Path

    from mtpy.data import HDF5Writer
    name = name or time.strftime("run_%Y%m%d_%H%M%S")
    path = Path(folder) / f"{name}.h5"
    if path.exists():
        raise NotReady(f"{path} exists; choose another run name (a data file is never overwritten)")
    try:
        identity = svc.call(dev.identity, what="identity")
    except Exception as e:  # noqa: BLE001 - identity is metadata; its absence is recorded, acquisition goes on
        identity = {"error": f"{type(e).__name__}: {e}"}
    meta = {"devices": {"jai": {"identity": identity, "settings_at_start": settings}}}
    return HDF5Writer(path, beads=beads, roles=roles, metadata=meta)


def _finish(timeout_s=10.0):
    global _pipe, _last, _svc
    pipe = _pipe
    done = False
    try:
        if pipe.stop_state is None:               # first stop: camera, segment end, recording off (once)
            try:
                _svc.call(_svc.device.stop_acquisition, what="stop acquisition")
            finally:
                _seg_event("end", pipe.end_segment())
                events.log("acquisition", action="stop", frames_received=pipe.frames_received,
                           pipeline_drops=sum(s.pipeline_drops for s in pipe.segments),
                           camera_gaps=sum(s.camera_gaps for s in pipe.segments))
                if pipe.recording:
                    set_recording(False)
    finally:
        done = pipe.stop(timeout_s)
        if done:
            _pipe, _last, _svc = None, pipe, None
        else:                                     # keep _pipe: inspect it (status) or call stop() again
            events.log("acquisition", action="stop incomplete", state=pipe.stop_state,
                       frames_received=pipe.frames_received, frames_tracked=pipe.frames_tracked,
                       ring_fill=len(pipe.ring))
    return done


def stop(timeout_s=10.0):
    """Stop acquisition (and recording); the worker finishes the frames already received, the sink is flushed and
    closed. Returns the final status(); its `stop` is "complete" when everything was drained into the sink.

    Review l2s-wp3-r1: when a thread (worker or sink) is still busy after timeout_s, the stop is incomplete:
    status() shows `running: True` and `stop: "incomplete: ..."`, an `acquisition` event (action "stop incomplete")
    is logged, the sink is NOT closed and the pipeline is kept; call stop() again to finish (the camera is already
    stopped and recording already off, so only the draining is resumed)."""
    _require()
    _finish(timeout_s)
    return status()


def _settings_snapshot(name, settings=None):
    """The camera settings read back now (roi, rate_Hz, exposure_ms, gain_dB) for a recording-on event. A failed
    read refuses the recording (U15 / 0006: settings are stored as read back, never missing): a `refused` event and
    NotReady; acquisition and display keep running. A read that lacks any of the four values (or gives None) is
    refused the same way, before the recording flag changes (review l2s-wp4-r1)."""
    if settings is None:
        try:
            settings = _svc.call(_svc.device.settings, what="read settings")
        except Exception as e:                    # any failed read refuses the recording
            reason = f"camera settings could not be read back ({type(e).__name__}: {e}); recording not started"
            events.log("refused", request={"recording": "on", "name": name}, reason=reason)
            raise NotReady(f"{reason}; acquisition keeps running, try again") from e
    missing = [k for k in SNAPSHOT_FIELDS if not isinstance(settings, dict) or settings.get(k) is None]
    if missing:
        reason = f"camera settings read back lack {missing}; recording not started"
        events.log("refused", request={"recording": "on", "name": name}, reason=reason)
        raise NotReady(f"{reason} (U15: roi, rate_Hz, exposure_ms, gain_dB are stored with every recording)")
    return {k: tuple(settings[k]) if k == "roi" else settings[k] for k in SNAPSHOT_FIELDS}


def set_recording(on, name=None, _settings=None):
    """Turn recording on or off while acquisition runs (exploration without recording, U17). Logs a `recording`
    event with the last frame received before the change (`buffer_number`): with on, frames after it are recorded;
    with off, frames up to it. The sink receives both events. Returns the flag.

    Every `on` event also carries `segment_info` (the current segment, `Segment.as_dict()`; the key `segment` stays
    the segment number, as in every event with a frame position) and `settings` (roi, rate_Hz,
    exposure_ms, gain_dB read back from the camera at that moment). The read comes first and the flag is set only
    after it succeeded; if it fails, recording stays off: NotReady with a `refused` event, acquisition and display
    keep running (review l2s-wp3-r1)."""
    pipe = _require()
    on = bool(on)
    if on == pipe.recording:
        return on
    if on and pipe.stop_state is not None:
        raise NotReady(f"acquisition is stopping ({pipe.stop_state}); recording cannot start; call api.acq.stop()")
    snap = _settings_snapshot(name, _settings) if on else None
    for svc in _services.values():
        svc.recording = on                    # 'guarded while recording' settings need confirm=True while on
    last, seg = pipe.set_recording(on)
    if on:
        events.log("recording", action="on", name=name, segment_info=seg, settings=snap, **last)
    else:
        pipe.forward(events.log("recording", action="off", name=name, **last))   # flag already cleared
    return on


def wait_frames(n, timeout_s):
    """Wait until the camera has produced n more frames (counted from buffer numbers: frames received plus camera
    gaps). Timeout after timeout_s. Returns n."""
    if not _require().wait_frames(n, timeout_s):
        raise Timeout(f"{n} camera frames not reached within {timeout_s:g} s; see api.acq.status()")
    return n


def mark(text):
    """A free-text `mark` event with the newest frame's segment and buffer number. Returns the event."""
    return events.log("mark", text=str(text), **_require().last_record())


def status():
    """running, recording, segment, frames received / tracked, fps measured (from the camera timestamps, source
    named), camera gaps, pipeline drops, unknown-loss segments, tracking time p50 / p99 (ms, per frame in the
    worker) and latency p50 / p99 (receive -> result), ring fill, errors, and every segment."""
    pipe = _pipe or _last
    if pipe is None:
        return {"running": False}
    return {"running": pipe is _pipe, **pipe.status()}


def sink():
    """The results sink of the running (or last) acquisition."""
    pipe = _pipe or _last
    return None if pipe is None else pipe.sink


def display():
    """The display tap's latest snapshot (`mtpy.acq.Snapshot`: seq, record, image, result; at most ~30 per second),
    or None. Reading it never slows acquisition (U2-U4)."""
    return None if _pipe is None else _pipe.display.snapshot()


# --- hooks for api.camera: the "needs a short pause" restart opens a new segment --------------------------------------
def _roi_refusal(roi, current_roi):
    """Why the ROI `roi` (x, y, w, h) cannot replace `current_roi` while the selected beads are tracked, or None.
    Bead positions are image (ROI) pixels and are not translated (review l2s-wp3-r1), so a moved ROI origin would
    point every bead at other sensor pixels, and a smaller ROI must still hold every bead's tracking window."""
    pipe = _pipe
    if pipe is None or pipe.beads is None or roi is None:
        return None
    x, y, w, h = roi
    if (x, y) != tuple(current_roi[:2]):
        return (f"ROI origin {tuple(current_roi[:2])} -> {(x, y)} while beads {list(pipe.bead_ids)} are tracked: "
                "bead positions are ROI pixels and are not translated; stop acquisition and select beads again")
    if not pipe.beads.fit((h, w)):
        return (f"ROI {w} x {h} does not hold the tracking windows of beads {list(pipe.bead_ids)}; stop acquisition "
                "and select beads again")
    return None


def _camera_paused():
    if _pipe is not None:
        _seg_event("end", _pipe.end_segment())


def _camera_restarting(settings):
    if _pipe is not None:
        _seg_event("begin", _pipe.begin_segment(settings, "settings change"))
