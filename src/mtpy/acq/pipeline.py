"""The acquisition pipeline: camera thread -> ring buffer -> tracking worker -> results sink (plan phase 5, WP3).

Threads (decision 0002: acquisition, tracking and saving never touch the GUI thread):
- **camera thread**: takes each frame from the camera's frame path (`source.next_frame`, never a device-service
  queue, never a serial / VISA call), stamps its `FrameRecord` (segment, original buffer number, camera-side gap) and
  pushes it into the ring. It never waits for the worker: a full ring drops its oldest frame (a pipeline drop).
- **tracking worker**: `BeadTracker` (track.Tracker's frame-to-frame logic on the numba `FastKernel`), then the
  latest result (`latest()`), the display tap and, for recorded frames, the sink queue.
- **sink thread**: the only caller of the `ResultSink`, fed by a lossless queue (frames and events are data).

Control between the loops is by LATEST VALUE, never by queue (V6 rule): `recording` is a flag the camera thread reads
per frame, the display tap and `latest()` hold one value each. Queues carry only lossless data (ring -> worker is a
bounded ring that drops by design and counts every drop; worker -> sink is lossless).
"""
import collections
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from .records import UNKNOWN, FrameRecord, FrameResult, Segment
from .ring import FrameRing
from .sink import MemorySink


@dataclass(frozen=True)
class Beads:
    """The selected beads: ids (1-based, as in the .cal and .tra), start positions (px, image coordinates), one
    calibration cluster per bead (`calib.clusters`), the cross size and the two windows (`calib.windows`)."""
    ids: tuple
    xy0: np.ndarray
    cals: list
    cross: int
    win_rs: np.ndarray
    win_h: np.ndarray
    source: str = ""
    roi: tuple = None        # camera ROI (x, y, w, h) when the beads were selected (U23, WP6); None = unknown

    @property
    def half_window(self):
        return int(np.rint(self.cross * 0.6))          # track.Params.k_half: the sub-image half-size h

    def fit(self, shape):
        """True when every bead's sub-image lies inside an image of `shape` (rows, cols)."""
        h, (rows, cols) = self.half_window, shape
        x, y = np.rint(self.xy0[:, 0]), np.rint(self.xy0[:, 1])
        return bool(((x - h >= 0) & (x + h <= cols) & (y - h >= 0) & (y + h <= rows)).all())


def make_kernel(beads, z_method="current", gpu=False):
    """The executor for the beads (imported here so `from mtpy import api` does not load numba): numba, or with the
    Z stage on the GPU; z_method is one of track.Z_METHODS (current / spline / phase_spline, owner 2026-10-29)."""
    if gpu:
        from mtpy.gpu import GpuKernel
        return GpuKernel(beads.cross, beads.win_rs, beads.win_h, beads.cals, z_method=z_method)
    from mtpy.fast import FastKernel
    return FastKernel(beads.cross, beads.win_rs, beads.win_h, beads.cals, z_method=z_method)


class BeadTracker:
    """track.Tracker's frame-to-frame state on any kernel with FastKernel's `track(image, xin, yin, good_in)`: each
    frame starts from the previous output (rounded half to even, as LabVIEW); a bead flagged bad is output as -1 on
    the next frame, and after any -1 every bead restarts from its calibration position."""

    def __init__(self, beads, kernel):
        self.beads, self.kernel = beads, kernel
        self.xy0 = np.asarray(beads.xy0, dtype=np.float64)[:, :2]
        self.xy = self.xy0.copy()
        self.good = np.ones(len(self.xy0), dtype=bool)
        self.lost = False
        self._shape = self._fits = None

    def step(self, image):
        """(xyz (n, 3), good (n,)); raises ValueError when the beads do not fit the image (e.g. after an ROI change)."""
        if image.shape != self._shape:
            self._shape, self._fits = image.shape, self.beads.fit(image.shape)
        if not self._fits:
            raise ValueError(f"beads do not fit a {image.shape[1]} x {image.shape[0]} image; select beads again")
        if self.lost:
            self.xy = self.xy0.copy()
            self.good = np.ones(len(self.xy0), dtype=bool)   # a new array: the last result keeps its own flags
        xyz, _, good = self.kernel.track(image, np.rint(self.xy[:, 0]).astype(np.int64),
                                         np.rint(self.xy[:, 1]).astype(np.int64), self.good)
        self.lost = bool((xyz == -1.0).any())
        self.xy = xyz[:, :2].copy()
        self.good = np.array(good, dtype=bool)
        return xyz, self.good


@dataclass(frozen=True)
class Snapshot:
    """What the GUI reads (U2-U4): the newest tracked frame, its image and result, at most `hz` times a second."""
    seq: int
    record: FrameRecord
    image: np.ndarray
    result: FrameResult


class DisplayTap:
    """A latest-value snapshot, not a queue: the worker offers every frame, one in each 1/hz is kept; the GUI reads
    `snapshot()` whenever it likes and can never slow acquisition."""

    def __init__(self, hz=30.0):
        self.period, self._t_next, self._snap, self.updates = 1.0 / hz, 0.0, None, 0

    def offer(self, record, image, result):
        now = time.perf_counter()
        if now < self._t_next:
            return
        late = now - self._t_next >= self.period
        self._t_next = now + self.period if late else self._t_next + self.period
        self.updates += 1
        self._snap = Snapshot(self.updates, record, image, result)

    def snapshot(self):
        return self._snap


def _pct(values, q):
    return float(np.percentile(values, q)) if len(values) else None


class Pipeline:
    """One acquisition run. `source` has the camera's frame path `next_frame(timeout_s)` -> Frame or None.
    The API opens / closes segments around every camera start / stop (`begin_segment`, `end_segment`)."""

    def __init__(self, source, beads=None, kernel=None, sink=None, ring_capacity=64, display_hz=30.0,
                 t_source="unknown", stats_len=2000):
        self.source, self.beads = source, beads
        self.tracker = BeadTracker(beads, kernel) if beads is not None else None
        self.bead_ids = tuple(beads.ids) if beads is not None else ()
        self.sink = sink if sink is not None else MemorySink()
        self.ring, self.display, self.t_source = FrameRing(ring_capacity), DisplayTap(display_hz), t_source
        self.recording = False                       # latest-value flag: set by the API, read per frame
        self.segments = []
        self._seg_lock = threading.Lock()            # camera thread vs segment open / close
        self._stats_lock = threading.Lock()
        self._count = threading.Condition()
        self._out = queue.Queue()                    # lossless: results and events for the sink thread
        self._recent = collections.deque(maxlen=300)          # (buffer, t_camera_s) of the current segment
        self._track_ms = collections.deque(maxlen=stats_len)
        self._latency_ms = collections.deque(maxlen=stats_len)
        self.frames_received = self.frames_produced = self.frames_tracked = 0
        self.tracking_errors, self.last_tracking_error = 0, None
        self.sink_failures, self.sink_error = 0, None
        self._avg = None  # [acc, frames left, Event] while average() collects
        self._latest = None
        self._cam_on, self._worker_on = threading.Event(), threading.Event()
        self._threads, self._unsubscribe = [], None
        self.stop_state, self._out_closed = None, False   # None while running; "complete" / "incomplete: ..."
        self.camera_stop = self.motor_poll = None         # set by api.acq (WP6): stop check, motor poller

    # --- lifecycle ------------------------------------------------------------------------------------------------
    def start(self, subscribe=None):
        """Start the sink, worker and camera threads. subscribe(fn) -> unsubscribe: the event source (api.events)."""
        self._cam_on.set()
        self._worker_on.set()
        for target, name in ((self._sink_loop, "acq-sink"), (self._worker_loop, "acq-tracking"),
                             (self._camera_loop, "acq-camera")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        if subscribe is not None:
            self._unsubscribe = subscribe(self._on_event)

    def stop(self, timeout_s=10.0):
        """Stop the camera thread, let the worker finish the ring, flush and close the sink. Returns True when all
        three threads ended (a completed stop = everything drained into the sink and the sink closed).

        Review l2s-wp3-r1: each join is followed by an is_alive check. On a timeout the stop is **incomplete**
        (`stop_state`, returns False): the sink's end marker is NOT queued while the worker may still produce results,
        nothing is dropped, and the caller keeps the pipeline to inspect it or call stop() again, which resumes where
        this one stopped (each step runs once)."""
        cam, worker, sink = self._threads[2], self._threads[1], self._threads[0]
        self._cam_on.clear()
        for t, after in ((cam, self._worker_on.clear), (worker, self._close_out), (sink, None)):
            t.join(timeout_s)
            if t.is_alive():
                self.stop_state = f"incomplete: {t.name} still running after {timeout_s:g} s"
                return False
            if after is not None:
                after()
        self.stop_state = "complete"
        return True

    def _close_out(self):
        """After the worker ended: no more results can come, so the sink may get its end marker (queued once)."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if not self._out_closed:
            self._out_closed = True
            self._out.put(None)

    # --- segments (called by the API around camera start / stop) ----------------------------------------------------
    def begin_segment(self, settings, reason="start"):
        """Open the next segment with the settings read back from the camera (rate_Hz, roi, exposure_ms)."""
        with self._seg_lock:
            return self._open(settings, reason)

    def end_segment(self):
        """After the camera stopped: take the frames still in the camera's buffer, then close the segment. Its
        end loss stays UNKNOWN (how many frames the camera produced after the last one received is not known)."""
        with self._seg_lock:
            while (f := self.source.next_frame(0)) is not None:
                self._receive(f)
            seg = self.segments[-1] if self.segments else None
            if seg is not None and seg.end_pc_s is None:
                seg.end_pc_s = time.time()
            return seg

    def _open(self, settings, reason):
        prev = self.segments[-1] if self.segments else None
        now = time.time()
        if prev is not None and prev.end_pc_s is None:
            prev.end_pc_s = now
        seg = Segment(len(self.segments) + 1, now, settings.get("rate_Hz"), tuple(settings.get("roi") or ()),
                      settings.get("exposure_ms"), self.t_source,
                      pc_gap_s=None if prev is None else now - prev.end_pc_s, reason=reason)
        self.segments.append(seg)
        with self._stats_lock:
            self._recent.clear()
        return seg

    # --- camera thread ----------------------------------------------------------------------------------------------
    def _camera_loop(self):
        while self._cam_on.is_set():
            with self._seg_lock:
                f = self.source.next_frame(0.02)
                if f is not None:
                    self._receive(f)

    def _receive(self, f):
        """Stamp one frame and push it (seg_lock held). Never waits for the worker."""
        seg = self.segments[-1] if self.segments else None
        b = f.buffer_number
        if seg is None or seg.end_pc_s is not None or (seg.last_buffer is not None and b <= seg.last_buffer):
            # a camera restart that did not come through the API: new segment, settings of the last one (not read
            # back), the old segment's end loss unknown
            seg = self._open({"rate_Hz": seg.rate_Hz, "roi": seg.roi, "exposure_ms": seg.exposure_ms} if seg else {},
                             "unannounced restart (settings not read back)")
        gap = b - (0 if seg.last_buffer is None else seg.last_buffer + 1)
        if seg.first_buffer is None:
            seg.first_buffer = b
        seg.last_buffer = b
        seg.frames_received += 1
        seg.camera_gaps += gap
        rec = FrameRecord(seg.number, b, f.t_camera_s, self.t_source, time.time(), seg.rate_Hz, seg.roi, gap,
                          self.recording)
        with self._stats_lock:
            self._recent.append((b, f.t_camera_s))
        dropped = self.ring.push((rec, f.image, time.perf_counter()), rec)
        if dropped is not None:
            self.segments[dropped.segment - 1].pipeline_drops += 1
        with self._count:
            self.frames_received += 1
            self.frames_produced += 1 + gap
            self._count.notify_all()

    # --- tracking worker --------------------------------------------------------------------------------------------
    def _worker_loop(self):
        empty = np.empty((0, 3)), np.empty(0, dtype=bool)
        while True:
            item, dropped = self.ring.pop(0.05)
            for rec in dropped:
                if rec.recording:
                    self._out.put(("frame", FrameResult(rec, self.bead_ids, None, None, dropped=True)))
            if item is None:
                if not self._worker_on.is_set() and not len(self.ring):
                    return
                continue
            rec, image, t_in = item
            t0 = time.perf_counter()
            extra = {}
            try:
                xyz, good = self.tracker.step(image) if self.tracker is not None else empty
            except Exception as e:  # noqa: BLE001 - recorded per frame and in status(); the pipeline keeps running
                xyz = good = None
                extra = {"error": f"{type(e).__name__}: {e}"}
                self.tracking_errors, self.last_tracking_error = self.tracking_errors + 1, extra["error"]
            t1 = time.perf_counter()
            res = FrameResult(rec, self.bead_ids, xyz, good, (t1 - t0) * 1e3, extra=extra)
            self._latest = res
            self.frames_tracked += 1
            with self._stats_lock:
                self._track_ms.append((t1 - t0) * 1e3)
                self._latency_ms.append((t1 - t_in) * 1e3)
            if rec.recording:
                self._out.put(("frame", res))
            self.display.offer(rec, image, res)
            req = self._avg
            if req is not None:
                img = image.astype(np.float64)
                req[0] = img if req[0] is None else req[0] + img
                req[1] -= 1
                if req[1] == 0:
                    self._avg = None
                    req[2].set()

    def average(self, n, timeout_s):
        """The mean (float64) of the next n frames the worker sees, at the camera rate: the z scan averages this way,
        not from the 30 Hz display tap (owner 2026-10-30: the GUI is an output)."""
        req = [None, n, threading.Event()]
        self._avg = req
        if not req[2].wait(timeout_s):
            self._avg = None
            raise TimeoutError(f"only {n - req[1]} of {n} frames in {timeout_s:g} s")
        return req[0] / n

    # --- sink thread ------------------------------------------------------------------------------------------------
    def _on_event(self, ev):
        if self.recording:
            self._out.put(("event", ev))

    def _sink_loop(self):
        while (item := self._out.get()) is not None:
            kind, x = item
            try:
                self.sink.write_frame(x) if kind == "frame" else self.sink.write_event(x)
            except Exception as e:  # noqa: BLE001 - shown in status(); never an event (it would come back here)
                self.sink_failures, self.sink_error = self.sink_failures + 1, f"{type(e).__name__}: {e}"
                self._note_sink_error(kind, x, e)
        try:
            self.sink.close()
        except Exception as e:  # noqa: BLE001
            self.sink_failures, self.sink_error = self.sink_failures + 1, f"close: {type(e).__name__}: {e}"

    def _note_sink_error(self, kind, x, e):
        """WP6 carry: a sink that can store its own failures (`note_error`, the HDF5 writer) gets each one, so the
        file says what it is missing; a failure to note it is only counted (the storage may be what failed)."""
        note = getattr(self.sink, "note_error", None)
        if note is None:
            return
        rec = getattr(x, "record", None)
        try:
            note(kind, f"{type(e).__name__}: {e}", segment=getattr(rec, "segment", None),
                 buffer=getattr(rec, "buffer_number", None), event_kind=getattr(x, "kind", None))
        except Exception:  # noqa: BLE001
            self.sink_note_failures = getattr(self, "sink_note_failures", 0) + 1

    # --- reads ------------------------------------------------------------------------------------------------------
    def latest(self):
        """The newest FrameResult (latest value), or None before the first tracked frame."""
        return self._latest

    def last_record(self):
        seg = self.segments[-1] if self.segments else None
        return {} if seg is None else {"segment": seg.number, "buffer_number": seg.last_buffer}

    def set_recording(self, on):
        """Set the recording flag between two frames. Returns (last, segment): the last frame received before the
        change (frames after it, and only those, carry the new flag) and a copy of the current segment
        (`Segment.as_dict()`, None before the first segment), both taken under the segment lock."""
        with self._seg_lock:
            self.recording = bool(on)
            seg = self.segments[-1].as_dict() if self.segments else None
            return self.last_record(), seg

    def forward(self, ev):
        """Hand one event to the sink regardless of the flag (the `recording off` event)."""
        self._out.put(("event", ev))

    def wait_frames(self, n, timeout_s):
        """Wait until the camera has produced n more frames (received + camera gaps, from the buffer numbers).
        Returns True, or False after timeout_s."""
        with self._count:
            target = self.frames_produced + n
            return self._count.wait_for(lambda: self.frames_produced >= target, timeout_s)

    def status(self):
        with self._stats_lock:
            recent, tm, lat = list(self._recent), list(self._track_ms), list(self._latency_ms)
        fps = None
        if len(recent) >= 2 and recent[-1][1] > recent[0][1]:
            fps = (recent[-1][0] - recent[0][0]) / (recent[-1][1] - recent[0][1])
        segs = [s.as_dict() for s in self.segments]
        return {"recording": self.recording, "stop": self.stop_state,
                "segment": segs[-1]["number"] if segs else None,
                "frames_received": self.frames_received, "frames_tracked": self.frames_tracked,
                "fps_measured": fps, "fps_source": self.t_source,
                "camera_gaps": sum(s["camera_gaps"] for s in segs),
                "pipeline_drops": sum(s["pipeline_drops"] for s in segs),
                "unknown_loss_segments": sum(s["end_pc_s"] is not None and s["end_loss"] is UNKNOWN for s in segs),
                "track_ms_p50": _pct(tm, 50), "track_ms_p99": _pct(tm, 99),
                "latency_ms_p50": _pct(lat, 50), "latency_ms_p99": _pct(lat, 99),
                "ring_fill": len(self.ring), "tracking_errors": self.tracking_errors,
                "last_tracking_error": self.last_tracking_error, "sink_failures": self.sink_failures,
                "sink_error": self.sink_error,
                # WP5 carry: frames the sink refused to hold (HDF5Writer max_pending overflow); None for a sink
                # without that count
                "frames_not_written": getattr(self.sink, "unwritten_frames", None),
                "display_updates": self.display.updates, "segments": segs}
