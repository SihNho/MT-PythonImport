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


def start(record=False, name=None, sink=None, ring_capacity=64):
    """Start acquisition (and tracking of the selected beads, if any). record=True also starts recording.

    name: the run name (used by the WP4 writer). sink: a `mtpy.acq.ResultSink`; None -> an in-memory sink until the
    WP4 writer exists (read it with `api.acq.sink()`). NotReady if acquisition already runs, the camera is not
    connected or the selected beads do not fit the camera ROI. Returns status()."""
    global _pipe, _svc
    if _pipe is not None:
        raise NotReady("acquisition is already running")
    svc = service("camera")
    dev = svc.require()
    if svc.call(dev.acquiring, what="acquiring?"):
        raise NotReady("the camera is already acquiring outside api.acq")
    beads = _beads.selected()
    s = svc.call(dev.settings, what="read settings")
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
            set_recording(True, name)
        events.log("acquisition", action="start", name=name, record=bool(record),
                   beads=list(pipe.bead_ids), cal=beads.source if beads is not None else None)
        _seg_event("begin", seg)
        svc.call(dev.start_acquisition, what="start acquisition")
    except BaseException:
        _finish()
        raise
    return status()


def _finish():
    global _pipe, _last, _svc
    pipe = _pipe
    try:
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
        pipe.stop()
        _pipe, _last, _svc = None, pipe, None


def stop():
    """Stop acquisition (and recording); the worker finishes the frames already received, the sink is flushed and
    closed. Returns the final status()."""
    _require()
    _finish()
    return status()


def set_recording(on, name=None):
    """Turn recording on or off while acquisition runs (exploration without recording, U17). Logs a `recording`
    event with the last frame received before the change (`buffer_number`): with on, frames after it are recorded;
    with off, frames up to it. The sink receives both events. Returns the flag."""
    pipe = _require()
    on = bool(on)
    if on == pipe.recording:
        return on
    for svc in _services.values():
        svc.recording = on                    # 'guarded while recording' settings need confirm=True while on
    last = pipe.set_recording(on)
    ev = events.log("recording", action="on" if on else "off", name=name, **last)
    if not on:
        pipe.forward(ev)                      # logged after the flag was cleared, so not forwarded by itself
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
def _camera_paused():
    if _pipe is not None:
        _seg_event("end", _pipe.end_segment())


def _camera_restarting(settings):
    if _pipe is not None:
        _seg_event("begin", _pipe.begin_segment(settings, "settings change"))
