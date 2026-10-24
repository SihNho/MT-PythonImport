"""HDF5 run file, schema v1 (plan phase 5, WP4): the writer (a `ResultSink`) and a plain Python reader.

Layout: docs/format/hdf5-v1.md, "Implemented in WP4" in docs/design/api.md (what is written now and how it differs
from the draft). Decisions 0005 (JAI buffer numbers are the time axis), 0006 (data format, crash tolerance), 0010
(magnet position raw, never force), 0011 (MATLAB reads the file with h5read).

Rules the writer keeps (review l2s-wp3-r1 / r2 carries):
- **No arrival order is assumed.** Frames come through the tracking worker, events straight from the thread that
  logged them, so a `recording on` event may arrive before or after the acquisition-start event, the segment events
  and the first recorded frames. Every item is kept with its own time and identity (segment, buffer number, event
  time); segment rows, recording rows and motor positions are rebuilt from everything received at every flush.
- **A recording-on event without the four settings read back (roi, rate_Hz, exposure_ms, gain_dB) is refused**:
  `RecordingRefused` is raised (the pipeline shows it as `sink_error` in `api.acq.status()`), nothing is opened and no
  recording or segment is started from it. A frame is written only inside an accepted recording interval, by
  (segment, buffer number): after the on event's position up to and including the off event's (review l2s-wp4-r1).
  Frames not yet placed are held in memory (bounded) until an on / off event places them; frames still outside every
  interval at close are counted (root attribute `frames_not_written`) and reported (RecordingRefused), never dropped
  or kept silently.
- **Dropped frames and camera gaps are rows / counts, never absent**: a pipeline drop is a row with `dropped = 1`
  and NaN positions; a camera gap is `lost_before` on the next row and a count per segment; an unconfirmed loss at a
  segment end is -1 (unknown), never 0.
- **Crash behaviour (tested points only)**: rows are buffered in memory and written at a flush (when
  `flush_frames` rows wait or `flush_s` seconds passed, checked at every write, and at close). Two crash points are
  tested (a subprocess ended with `os._exit`): after a flush with rows still waiting in memory, and right after a new
  event-kind group was created; in both the file opened and held exactly the rows of the last flush, with
  `closed_cleanly = 0`. For those points the loss is the rows since the last flush (at most `flush_frames`, default
  150). A crash during a flush (including the motor back-fill rewrite) is NOT tested (WP6); nothing is promised for
  it.
- **Late information is applied at the next flush**: a motor reading that arrives after rows with later PC times
  were flushed rewrites those rows' magnet / rotor columns; a .cal path that arrives late is stored and /beads is
  rebuilt from it (user roles kept).
- The file is opened with `libver=("earliest", "v108")`: HDF5 1.8 object formats at most, for older MATLAB builds.
"""
import datetime
import hashlib
import json
import math
import time
import uuid
from bisect import bisect_right
from pathlib import Path

import h5py
import numpy as np

from mtpy.acq.sink import ResultSink
from mtpy.api.errors import NotReady

SCHEMA_VERSION = "1.0"
FILE_KIND = "mtpy-run"
SETTINGS = ("roi", "rate_Hz", "exposure_ms", "gain_dB")
STR = h5py.string_dtype("utf-8")
CHUNK = 256
_CAMERA_QUANTITIES = {"camera_roi": "roi", "camera_rate_Hz": "rate_Hz", "camera_exposure_ms": "exposure_ms",
                      "camera_gain_dB": "gain_dB"}


class RecordingRefused(NotReady):
    """A recording-on event the writer cannot accept (a setting missing), or recorded frames that no accepted
    recording-on covers."""


def _plain(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=repr)
    if isinstance(o, Path):
        return str(o)
    return repr(o)


def to_json(x):
    return json.dumps(x, default=_plain, ensure_ascii=False)


def _num(x, default=math.nan):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v


def _int(x, default=-1):
    return default if x is None else int(x)


def _utc(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()


class _Table:
    """A group of equal-length column datasets, chunked and extendible along the first axis (hdf5-v1.md
    conventions). Rows wait in memory until flush(); `rewrite(rows)` replaces the whole table (small tables that are
    rebuilt at every flush: segments, recordings)."""

    def __init__(self, group, columns):
        self.g, self.cols, self.n = group, columns, 0
        self.buf = {k: [] for k in columns}
        for name, (dt, width, unit, desc) in columns.items():
            shape = (0,) if width is None else (0, width)
            ds = group.create_dataset(name, shape=shape, maxshape=(None, *shape[1:]), dtype=dt,
                                      chunks=(CHUNK, *shape[1:]))
            ds.attrs["unit"], ds.attrs["description"] = unit, desc
            if name in ("request", "readback", "data", "settings") or name.endswith("_json"):
                ds.attrs["content"] = "json"

    def append(self, row):
        for k in self.cols:
            self.buf[k].append(row[k])

    def waiting(self):
        return len(self.buf[next(iter(self.cols))])

    def _write(self, start, cols):
        m = len(next(iter(cols.values())))
        for k, (dt, _, _, _) in self.cols.items():
            ds = self.g[k]
            ds.resize(start + m, axis=0)
            if m:
                ds[start:start + m] = np.asarray(cols[k], dtype=object if dt is STR else dt)
        return m

    def flush(self):
        if self.waiting():
            self.n += self._write(self.n, self.buf)
            self.buf = {k: [] for k in self.cols}

    def rewrite(self, rows):
        self.n = self._write(0, {k: [r[k] for r in rows] for k in self.cols})


def _event_columns():
    return {
        "event_id": (np.int64, None, "1", "unique within the run (order of arrival at the writer, not event order)"),
        "buffer_number": (np.int64, None, "1", ("camera buffer number carried by the event (the last frame received "
                                                "before it), -1 when the event carries none")),
        "segment": (np.int32, None, "1", "segment of that buffer number, -1 when none"),
        "t_host": (np.float64, None, "s", "host time the event was logged, from the run start (root t0_unix)"),
        "caller": (STR, None, "1", "who caused it (api.events caller)"),
        "supersedes": (np.int64, None, "1", "event replaced by this one, -1 if none"),
        "note": (STR, None, "1", "free text"),
        "request": (STR, None, "1", "what was asked (JSON)"),
        "readback": (STR, None, "1", "what the device read back (JSON)"),
        "data": (STR, None, "1", "the event's own fields (JSON)"),
    }


def _mt_columns(n_beads):
    cols = {
        "buffer_number": (np.uint64, None, "1", ("original camera buffer number (restarts at 0 in each segment, WP3 "
                                                 "frame contract); .tra frame = buffer_number - /segments first_buffer")),
        "segment": (np.int32, None, "1", "acquisition segment number (row of /segments)"),
        "lost_before": (np.uint32, None, "1", "camera-side frames missing right before this one (buffer numbers)"),
        "dropped": (np.uint8, None, "1", ("1 = pipeline drop: received but dropped from the full ring, never "
                                          "tracked (positions NaN)")),
        "track_error": (np.uint8, None, "1", ("1 = tracking raised on this frame (positions NaN; message in "
                                              "/events/writer_tracking_error)")),
        "t_host": (np.float64, None, "s", "PC receive time from the run start (root t0_unix)"),
        "t_camera": (np.float64, None, "s", "camera-side frame time; attribute source says which clock"),
        "magnet_mm": (np.float64, None, "mm", ("last magnet position read back before this frame (PC time), NaN "
                                               "before the first reading; raw record, never force (0010)")),
        "magnet_t": (np.float64, None, "s", "host time of that magnet reading from the run start"),
        "rotor_deg": (np.float64, None, "deg", "last rotor position read back before this frame, turns x 360"),
        "rotor_t": (np.float64, None, "s", "host time of that rotor reading from the run start"),
        "track_ms": (np.float64, None, "ms", "tracking time of this frame in the worker, NaN if not tracked"),
    }
    if n_beads:
        cols.update({
            "x_px": (np.float64, n_beads, "px", "bead x (.tra column 3 + 3i); -1 = lost (LabVIEW marker)"),
            "y_px": (np.float64, n_beads, "px", "bead y (.tra column 4 + 3i); -1 = lost"),
            "z_um": (np.float64, n_beads, "um", ("bead height (.tra column 5 + 3i; the .tra header's 'nm' is wrong, "
                                                 "0008); -1 = lost")),
            "bead_good": (np.uint8, n_beads, "1", "the kernel's good flag"),
            "bead_lost": (np.uint8, n_beads, "1", "1 when the kernel returned the lost marker (-1)"),
        })
    return cols


_SEGMENT_COLUMNS = {
    "number": (np.int32, None, "1", "segment number (every acquisition start begins one)"),
    "reason": (STR, None, "1", "start | settings change | unannounced restart"),
    "t_start": (np.float64, None, "s", "PC time the segment was opened, from the run start (NaN unknown)"),
    "t_end": (np.float64, None, "s", "PC time the segment was closed, from the run start (NaN unknown)"),
    "pc_gap_s": (np.float64, None, "s", "PC time since the previous segment ended (NaN for the first / unknown)"),
    "rate_Hz": (np.float64, None, "Hz", "frame rate read back from the camera for this segment (U15)"),
    "rate_Hz_measured": (np.float64, None, "Hz", "from the recorded frames' t_camera and buffer numbers"),
    "roi": (np.int32, 4, "px", "x, y, w, h read back"),
    "exposure_ms": (np.float64, None, "ms", "exposure in force at the segment's first recorded frame"),
    "gain_dB": (np.float64, None, "dB", "gain in force at the segment's first recorded frame"),
    "settings": (STR, None, "1", ("JSON: every setting value known for this segment with its time and source "
                                  "(segment start, recording on, act events); changes during the segment are listed")),
    "settings_source": (STR, None, "1", ("where rate_Hz / roi came from: segment read-back (event or recording-on "
                                         "snapshot) or the frame records (same read-back, copied per frame)")),
    "t_source": (STR, None, "1", "what t_camera is for this segment"),
    "first_buffer": (np.int64, None, "1", "first buffer number received in the segment (pipeline), -1 unknown"),
    "last_buffer": (np.int64, None, "1", "last buffer number received (pipeline), -1 unknown"),
    "frames_received": (np.int64, None, "1", ("frames the pipeline received in the segment (recorded or not), -1 "
                                              "until the segment end event")),
    "frames_recorded": (np.int64, None, "1", "rows of /mt in this segment"),
    "frames_dropped": (np.int64, None, "1", "recorded rows that are pipeline drops (dropped = 1)"),
    "camera_gaps": (np.int64, None, "1", "sum of lost_before over the recorded rows"),
    "camera_gaps_segment": (np.int64, None, "1", "camera gaps of the whole segment (pipeline), -1 until its end"),
    "pipeline_drops_segment": (np.int64, None, "1", "pipeline drops of the whole segment, -1 until its end"),
    "tracking_errors": (np.int64, None, "1", "recorded rows with track_error = 1"),
    "end_loss": (np.int64, None, "1", "frames produced after the last one received: -1 = unknown (never 0)"),
}

_RECORDING_COLUMNS = {
    "name": (STR, None, "1", "recording name"),
    "event_id_on": (np.int64, None, "1", "event_id of the recording-on event"),
    "t_on": (np.float64, None, "s", "host time of recording on, from the run start"),
    "t_off": (np.float64, None, "s", "host time of recording off (NaN: not received)"),
    "on_segment": (np.int32, None, "1", "segment of the last frame received before recording on (-1 none)"),
    "on_buffer": (np.int64, None, "1", "that frame's buffer number; recorded frames come after it (-1 none)"),
    "off_segment": (np.int32, None, "1", "segment of the last recorded frame (-1 none / not received)"),
    "off_buffer": (np.int64, None, "1", "buffer number of the last recorded frame (-1 none / not received)"),
    "settings": (STR, None, "1", "JSON: roi, rate_Hz, exposure_ms, gain_dB read back at recording on"),
}

_BEAD_COLUMNS = {
    "bead_id": (np.int32, None, "1", "bead id = its 1-based number in the .cal file"),
    "tra_column": (np.int32, None, "1", "position in the .tra / per-bead column order (0-based)"),
    "role": (STR, None, "1", "reference | tethered | candidate"),
    "role_source": (STR, None, "1", "how the role was set"),
    "pick_xy_px": (np.float64, 2, "px", "where the bead was picked (.cal x, y)"),
}


class HDF5Writer(ResultSink):
    """Writes one acquisition's recorded frames and events to an HDF5 v1 file (see the module docstring).

    path: the .h5 file (refused if it exists). beads: the `mtpy.acq.Beads` tracked (ids, pick positions, .cal path);
    None -> bead ids from the frames and the .cal path from the acquisition-start event. roles: {bead_id: role} set
    by the user; else the .cal exp/ref flags (0 -> reference, 1 -> tethered; meaning inferred) or `candidate`.
    metadata: {"devices": {name: {item: value}}, "presets": {kind: value}, "run": {item: value}} stored as JSON
    strings under /metadata. All methods are called from the pipeline's single sink thread."""

    def __init__(self, path, beads=None, roles=None, metadata=None, flush_frames=150, flush_s=1.0,
                 max_pending=20000, json_copy=True):
        self.path = Path(path)
        if self.path.exists():
            raise FileExistsError(f"{self.path} exists; the writer never overwrites a data file")
        self.t0 = time.time()
        self.run_id = str(uuid.uuid4())
        self.beads, self.roles, self.metadata = beads, dict(roles or {}), dict(metadata or {})
        self.cal_path = getattr(beads, "source", None) or None
        self.flush_frames, self.flush_s, self.max_pending, self.json_copy = flush_frames, flush_s, max_pending, json_copy
        self.f = None
        self.closed = False
        self.accepted = []            # accepted recording-on events
        self.offs = []                # recording-off events
        self.refused = []             # (event, missing settings) of refused recording-on events
        self.unwritten_frames = 0     # recorded frames no accepted recording-on covered (reported at close)
        self.errors = []
        self._pending_frames, self._pending_events = [], []
        self._event_id = 0
        self._ev_tables = {}
        self._mt = self._segs = self._recs = None
        self._bead_ids = tuple(beads.ids) if beads is not None else None
        self._seg_info = {}           # number -> dict of what is known about the segment (merged from all sources)
        self._seg_rows = {}           # number -> stats from the recorded frames
        self._hist = []               # (t, key, value, source): camera settings history from events
        self._motor = {"magnet": [], "rotor": []}    # sorted (t, value)
        self._mt_rows = []            # waiting /mt rows (filled with motor positions at flush)
        self._ids = {}                # id(event) -> event_id
        self._cal = None
        self._beads_tab = None
        self._iv = None               # cached recording intervals (rebuilt when an on / off event arrives)
        self._motor_dirty = None      # earliest PC time of a motor reading that arrived after rows were flushed
        self._last_flush = time.monotonic()

    # --- ResultSink -------------------------------------------------------------------------------------------------
    def write_event(self, ev):
        x = ev.extra or {}
        if ev.kind == "recording" and x.get("action") == "on":
            s = x.get("settings") or {}
            missing = [k for k in SETTINGS if s.get(k) is None]
            if missing:
                self.refused.append((ev, missing))
                if self.f is not None:
                    self._write_event_row("writer_refused", ev, data={"refused": "recording on", "missing": missing,
                                                                     "event": {"kind": ev.kind, "extra": x}})
                    self._maybe_flush()
                raise RecordingRefused(f"recording-on event {x.get('name')!r} lacks the settings read back {missing} "
                                       "(roi, rate_Hz, exposure_ms, gain_dB are required, U15); recording not started")
            self.accepted.append(ev)
            self._iv = None
            for k in SETTINGS:
                self._hist.append((ev.t, k, s[k], "recording on"))
            info = x.get("segment_info")
            if info:
                self._merge_segment(info.get("number"), info, "recording-on snapshot")
        elif ev.kind == "recording" and x.get("action") == "off":
            self.offs.append(ev)
            self._iv = None
        self._absorb(ev)
        if self.f is None:
            if self.accepted:
                self._open()
            else:
                self._pending_events.append(ev)
                return
        self._write_event(ev)
        if self._iv is None:
            self._release_pending()
        self._maybe_flush()

    def write_frame(self, result):
        """A frame is written only when it lies inside an accepted recording interval (by segment and buffer number,
        see `_intervals`); otherwise it is held (bounded by max_pending) until an on / off event places it, and
        frames still outside every interval at close are reported there (RecordingRefused), never kept silently."""
        rec = result.record
        if self.accepted and self._covered((rec.segment, rec.buffer_number)):
            if self.f is None:
                self._open()
            self._add_frame(result)
            self._maybe_flush()
            return
        if len(self._pending_frames) >= self.max_pending:
            self.unwritten_frames += 1
            raise RecordingRefused(f"{self.max_pending} recorded frames wait for an accepted recording-on interval; "
                                   f"frame (segment {rec.segment}, buffer {rec.buffer_number}) not written")
        self._pending_frames.append(result)

    def close(self):
        """Flush everything, write the end time and the frame-rate triple, set closed_cleanly = 1 and close. Then
        raise RecordingRefused if any recorded frame was not written (no accepted recording-on interval covers it)
        or a written row lies outside the final intervals (an off event that arrived after its frames); the counts
        are also stored as root attributes `frames_not_written` / `frames_outside_recordings`. Without an accepted
        recording-on no file exists."""
        if self.closed:
            return
        self.closed = True
        if self.f is None:
            n = len(self._pending_frames) + self.unwritten_frames
            if n:
                self.unwritten_frames = n
                raise RecordingRefused(f"{n} recorded frames not written: no recording-on event with the four settings "
                                       f"arrived ({len(self.refused)} refused); no file created")
            return
        not_written = outside = 0
        try:
            self._release_pending()
            self.flush()
            not_written = self.unwritten_frames = self.unwritten_frames + len(self._pending_frames)
            outside = self._rows_outside()
            run = self.f["metadata/run"]
            _put_str(run, "end_utc", _utc(time.time()))
            self._frame_rate_triple(run)
            self.f.attrs["frames_written"] = self._mt.n if self._mt is not None else 0
            self.f.attrs["frames_not_written"] = not_written
            self.f.attrs["frames_outside_recordings"] = outside
            self.f.attrs["closed_cleanly"] = np.uint8(1)
            self.f.flush()
            if self.json_copy:
                self.path.with_suffix(".meta.json").write_text(
                    to_json(_read_group(self.f["metadata"])), encoding="utf-8")
        finally:
            self.f.close()
        if not_written or outside:
            raise RecordingRefused(f"{not_written} recorded frames not written (outside every accepted recording-on "
                                   f"interval) and {outside} written rows outside the final intervals; see the root "
                                   f"attributes of {self.path.name}")

    # --- recording intervals (segment, buffer number), never arrival order -------------------------------------------
    @staticmethod
    def _pos(x):
        """(segment, buffer) of an on / off event: the last frame received before the flag changed; no segment ->
        before everything, no buffer -> before the segment's first frame."""
        seg, buf = x.get("segment"), x.get("buffer_number")
        return (-1, -1) if seg is None else (int(seg), -1 if buf is None else int(buf))

    def _intervals(self):
        """Accepted recording intervals: after the on event's position up to and including the off event's
        position (the first off after that on and before the next on, by event time); with no off, up to the next
        on's position, or open-ended (api.acq contract: on -> frames after its buffer, off -> frames up to it)."""
        if self._iv is None:
            ons, offs = sorted(self.accepted, key=lambda e: e.t), sorted(self.offs, key=lambda e: e.t)
            iv = []
            for i, on in enumerate(ons):
                nxt = ons[i + 1] if i + 1 < len(ons) else None
                off = next((o for o in offs if on.t <= o.t and (nxt is None or o.t < nxt.t)), None)
                end = self._pos(off.extra) if off is not None else (self._pos(nxt.extra) if nxt is not None else None)
                iv.append((self._pos(on.extra), end))
            self._iv = iv
        return self._iv

    def _covered(self, pos):
        return any(start < pos and (end is None or pos <= end) for start, end in self._intervals())

    def _release_pending(self):
        """Write the held frames that an accepted interval now covers (file open)."""
        if self.f is None or not self._pending_frames:
            return
        keep = []
        for r in self._pending_frames:
            if self._covered((r.record.segment, r.record.buffer_number)):
                self._add_frame(r)
            else:
                keep.append(r)
        self._pending_frames = keep

    def _rows_outside(self):
        if self._mt is None or not self._mt.n:
            return 0
        seg, buf = self._mt.g["segment"][()], self._mt.g["buffer_number"][()].astype(np.int64)
        inside = np.zeros(len(seg), dtype=bool)
        for start, end in self._intervals():
            after = (seg > start[0]) | ((seg == start[0]) & (buf > start[1]))
            before = True if end is None else (seg < end[0]) | ((seg == end[0]) & (buf <= end[1]))
            inside |= after & before
        return int((~inside).sum())

    # --- state from events and frames (independent of arrival order) ------------------------------------------------
    def _absorb(self, ev):
        x = ev.extra or {}
        if ev.kind == "segment":
            n = x.get("segment")
            info = {k: x.get(k) for k in ("reason", "rate_Hz", "roi", "exposure_ms", "t_source", "pc_gap_s",
                                          "first_buffer", "last_buffer", "frames_received", "camera_gaps",
                                          "pipeline_drops")}
            if x.get("action") == "begin":
                info["begin_event_t"] = ev.t           # logged just after the segment opened; its own start_pc_s
                #                                         (recording-on snapshot) is preferred when it arrives
                for k in self._COUNTERS:                   # all empty at a segment's begin
                    info.pop(k, None)
            else:
                info["end_pc_s"] = ev.t
                el = x.get("end_loss")
                info["end_loss"] = None if el in (None, "unknown") else el
                info["ended"] = True
            self._merge_segment(n, info, f"segment {x.get('action')} event")
        elif ev.kind == "acquisition" and x.get("action") == "start" and not self.cal_path and x.get("cal"):
            self.cal_path = x.get("cal")            # applied at the next flush, whenever it arrives
        elif ev.kind == "act" and isinstance(ev.request, dict):
            q = ev.request.get("quantity")
            motor = {"magnet_position_mm": ("magnet", 1.0), "rotor_turns": ("rotor", 360.0)}.get(q)
            if motor is not None and _num(ev.readback) == _num(ev.readback):
                self._insert(self._motor[motor[0]], ev.t, float(ev.readback) * motor[1])
                if self._mt is not None and self._mt.n:      # rows already on disk may need it: back-fill at flush
                    self._motor_dirty = ev.t if self._motor_dirty is None else min(self._motor_dirty, ev.t)
            elif q in _CAMERA_QUANTITIES:
                self._hist.append((ev.t, _CAMERA_QUANTITIES[q], ev.readback, "act read-back"))
            elif q == "camera_preset" and isinstance(ev.readback, dict):
                for k, v in ev.readback.items():
                    if k in SETTINGS:
                        self._hist.append((ev.t, k, v, "preset read-back"))

    @staticmethod
    def _insert(lst, t, v):
        lst.insert(bisect_right([a for a, _ in lst], t), (t, v))

    _COUNTERS = ("first_buffer", "last_buffer", "frames_received", "camera_gaps", "pipeline_drops", "end_pc_s",
                 "end_loss", "ended")

    def _merge_segment(self, n, info, source):
        """Merge what one source says about segment n. Start settings (rate, ROI, exposure, start time, reason):
        the first value received stays (all sources carry the same read-back). Counters: the segment-end event is
        final; a recording-on snapshot (partial counts) fills them only while no end event arrived."""
        if n is None:
            return
        d = self._seg_info.setdefault(int(n), {"sources": []})
        final = bool(info.get("ended"))
        for k, v in info.items():
            if v is None or k == "sources":
                continue
            if k in self._COUNTERS:
                if final or not d.get("ended"):
                    d[k] = v
            elif k not in d:
                d[k] = v
        if info.get("rate_Hz") is not None:
            d.setdefault("rate_source", f"segment read-back ({source})")
        t_start = info.get("start_pc_s", info.get("begin_event_t"))
        if t_start is not None:
            for k in ("rate_Hz", "roi", "exposure_ms"):
                if info.get(k) is not None:
                    self._hist.append((t_start, k, info[k], f"segment {n} start ({source})"))
        d["sources"].append(source)

    def _frame_stats(self, res):
        rec = res.record
        s = self._seg_rows.setdefault(rec.segment, {"n": 0, "dropped": 0, "gaps": 0, "errors": 0, "first": None,
                                                     "last": None, "rate": rec.rate_Hz, "roi": rec.roi,
                                                     "t_source": rec.t_source, "t_first_pc": rec.t_pc_s})
        s["n"] += 1
        s["dropped"] += int(res.dropped)
        s["gaps"] += int(rec.gap_before)
        s["errors"] += int(bool(res.extra.get("error"))) if res.extra else 0
        s["t_first_pc"] = min(s["t_first_pc"], rec.t_pc_s)
        pt = (rec.buffer_number, rec.t_camera_s)
        if s["first"] is None or pt[0] < s["first"][0]:
            s["first"] = pt
        if s["last"] is None or pt[0] > s["last"][0]:
            s["last"] = pt

    # --- file ------------------------------------------------------------------------------------------------------
    def _open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # upper bound v108 (HDF5 1.8 object formats): a feature older MATLAB HDF5 builds cannot read raises here
        # instead of silently producing an unreadable file (review l2s-wp4-r1; real MATLAB check is WP6)
        f = self.f = h5py.File(self.path, "w-", libver=("earliest", "v108"))
        f.attrs.update({"schema_version": SCHEMA_VERSION, "file_kind": FILE_KIND, "created_utc": _utc(self.t0),
                        "closed_cleanly": np.uint8(0), "run_id": self.run_id, "t0_unix": self.t0,
                        "legacy_cal_file": self.cal_path or "", "flush_frames": self.flush_frames,
                        "flush_s": self.flush_s})
        f.attrs.create("legacy_tra_files", [], dtype=STR)
        meta = f.create_group("metadata")
        run = meta.create_group("run")
        from mtpy import api
        _put_str(run, "start_utc", _utc(self.t0))
        _put_str(run, "software_name", "mtpy")
        _put_str(run, "software_version", f"api {api.VERSION}")
        _put_str(run, "tracking_stages", to_json({"pipeline": "mtpy.acq.BeadTracker", "kernel": "mtpy.fast.FastKernel"
                                                  " (LabVIEW cross-correlation xy, radial-profile z)"}), json_=True)
        first = self.accepted[0].extra
        jai = meta.create_group("devices").create_group("jai")
        _put_str(jai, "readback", to_json(first.get("settings")), json_=True)
        for name, items in (self.metadata.get("devices") or {}).items():
            g = meta["devices"].require_group(name)
            for k, v in items.items():
                if k not in g:
                    _put_str(g, k, v if isinstance(v, str) else to_json(v), json_=not isinstance(v, str))
        pre = meta.create_group("presets")
        for k, v in (self.metadata.get("presets") or {}).items():
            _put_str(pre, k, v if isinstance(v, str) else to_json(v), json_=not isinstance(v, str))
        for k, v in (self.metadata.get("run") or {}).items():
            if k not in run:
                _put_str(run, k, v if isinstance(v, str) else to_json(v), json_=not isinstance(v, str))
        meta.create_group("calibration")
        self._fill_calibration()
        ev = f.create_group("events")
        ev.attrs["description"] = ("one table per event kind; own columns are in `data` (JSON); arrival order is not "
                                   "event order: use t_host / buffer_number")
        self._segs = _Table(f.create_group("segments"), _SEGMENT_COLUMNS)
        self._recs = _Table(f.create_group("recordings"), _RECORDING_COLUMNS)
        pending_e, pending_f = self._pending_events, self._pending_frames
        self._pending_events, self._pending_frames = [], []
        for e, missing in self.refused:                    # refused before the file existed: recorded now
            self._write_event_row("writer_refused", e, data={"refused": "recording on", "missing": missing,
                                                             "event": {"kind": e.kind, "extra": e.extra}})
        for e in pending_e:
            self._write_event(e)
        self._pending_frames = pending_f
        self._release_pending()
        self.flush()

    def _fill_calibration(self):
        """Store the .cal content once its path is known (at open, or at a later flush when the acquisition-start
        event carrying it arrives late); /beads is rebuilt from it at every flush."""
        g = self.f["metadata/calibration"]
        p = Path(self.cal_path) if self.cal_path else None
        if self._cal is not None:
            return
        if p is None or not p.is_file():
            g.attrs["note"] = f"no .cal file read ({self.cal_path!r})"
            return
        from mtpy.lvfiles import read_cal
        raw = p.read_bytes()
        cal = read_cal(p)
        self._cal = cal
        if "note" in g.attrs:
            del g.attrs["note"]
        self.f.attrs["legacy_cal_file"] = str(p)
        for name, val, unit, desc in (
                ("xy_px", cal["xy"], "px", ".cal x,y pos array"),
                ("stack", cal["stack"], "a.u.", ".cal cal image array (radial-profile stack)"),
                ("z_step_um", cal["z_step"], "um", "slice step as stored (single precision widened)"),
                ("n_avg", np.int32(cal["n_avg"]), "1", "frames averaged per slice (inferred)"),
                ("n_slices", np.int32(cal["n_slices"]), "1", "# slices in stack"),
                ("bandpass_forget", cal["bead_i32"].astype(np.int32), "1", "per-bead bandpass / forget (inferred)"),
                ("exp_ref", cal["bead_flags"].astype(np.int32), "1",
                 "0 = reference, 1 = experiment (inferred); /beads/role is the authority"),
                ("nm_per_px", cal["nm_per_px"], "nm/px",
                 "Pixel distance as stored; not used by tracking, possibly stale (rig-facts.md)"),
                ("cal_bytes", np.frombuffer(raw, dtype=np.uint8), "1",
                 "the .cal file byte for byte (for the byte-identical .cal export)")):
            ds = g.create_dataset(name, data=val)
            ds.attrs["unit"], ds.attrs["description"] = unit, desc
        _put_str(g, "date", cal["date"])
        _put_str(g, "sha256", hashlib.sha256(raw).hexdigest())
        _put_str(g, "path", str(p))

    def _create_beads_and_mt(self, ids):
        self._bead_ids = tuple(ids)
        f, n = self.f, len(ids)
        self._beads_tab = _Table(f.create_group("beads"), _BEAD_COLUMNS)
        self._beads_tab.rewrite(self._bead_rows())
        mt = f.create_group("mt")
        mt.attrs["n_beads"] = n
        self._mt = _Table(mt, _mt_columns(n))

    def _bead_rows(self):
        """/beads from the user roles, the .cal (exp/ref flags, pick positions) and the tracked beads; rebuilt at
        every flush so a .cal that arrives late is reflected (user roles always win)."""
        cal, rows = self._cal, []
        for col, b in enumerate(self._bead_ids):
            in_cal = cal is not None and 1 <= b <= len(cal["bead_flags"])
            if b in self.roles:
                role, src = self.roles[b], "user"
            elif in_cal:
                role = "reference" if cal["bead_flags"][b - 1] == 0 else "tethered"
                src = "cal exp/ref flag (inferred meaning: 0 reference, 1 experiment)"
            else:
                role, src = "candidate", "not set"
            if self.beads is not None and col < len(self.beads.xy0):
                xy = self.beads.xy0[col, :2]
            elif in_cal:
                xy = cal["xy"][b - 1, :2]
            else:
                xy = (math.nan, math.nan)
            rows.append({"bead_id": int(b), "tra_column": col, "role": role, "role_source": src,
                         "pick_xy_px": np.asarray(xy, dtype=float)})
        return rows

    def _add_frame(self, res):
        if self._mt is None:
            self._create_beads_and_mt(self._bead_ids if self._bead_ids is not None else res.bead_ids)
        self._frame_stats(res)
        rec, n = res.record, len(self._bead_ids)
        err = bool(res.extra.get("error")) if res.extra else False
        if res.xyz is None or res.dropped or err or n == 0:
            xyz, good = np.full((n, 3), np.nan), np.zeros(n, dtype=np.uint8)
        else:
            xyz, good = np.asarray(res.xyz, dtype=np.float64), np.asarray(res.good, dtype=np.uint8)
        if err:
            self._write_event_row("writer_tracking_error", None, data={"error": res.extra["error"]},
                                  buffer=rec.buffer_number, segment=rec.segment, t=rec.t_pc_s)
        row = {"buffer_number": rec.buffer_number, "segment": rec.segment, "lost_before": rec.gap_before,
               "dropped": int(res.dropped), "track_error": int(err), "t_host": rec.t_pc_s - self.t0,
               "t_camera": rec.t_camera_s, "track_ms": _num(res.track_ms), "_t_pc": rec.t_pc_s,
               "_t_source": rec.t_source}
        if n:
            row.update({"x_px": xyz[:, 0], "y_px": xyz[:, 1], "z_um": xyz[:, 2], "bead_good": good,
                        "bead_lost": (xyz == -1.0).all(axis=1).astype(np.uint8)})
        self._mt_rows.append(row)

    def _motor_at(self, name, t_pc):
        """(values, reading times from t0) of the last reading at or before each PC time in t_pc (array); NaN
        before the first reading."""
        t_pc = np.asarray(t_pc, dtype=np.float64)
        lst = self._motor[name]
        if not lst:
            return np.full(t_pc.shape, math.nan), np.full(t_pc.shape, math.nan)
        ts = np.array([a for a, _ in lst])
        vs = np.array([v for _, v in lst])
        i = np.searchsorted(ts, t_pc, side="right")
        ok = i > 0
        j = np.maximum(i - 1, 0)
        return np.where(ok, vs[j], math.nan), np.where(ok, ts[j] - self.t0, math.nan)

    def _backfill_motors(self):
        """A motor reading that arrived after rows with later PC times were flushed: rewrite magnet / rotor of
        those rows (review l2s-wp4-r1). Rows are in arrival order, roughly PC-time order, so the file is scanned
        back from the end until a whole block lies before the reading."""
        t_dirty, self._motor_dirty = self._motor_dirty, None
        if t_dirty is None or self._mt is None or not self._mt.n:
            return
        g, n, block = self._mt.g, self._mt.n, 4096
        first, hi = None, n
        while hi > 0:
            lo = max(0, hi - block)
            late = np.nonzero(g["t_host"][lo:hi] + self.t0 >= t_dirty)[0]
            if not len(late):
                break
            first, hi = lo + int(late[0]), lo
        if first is None:
            return
        t_pc = g["t_host"][first:n] + self.t0
        for name, col, tcol in (("magnet", "magnet_mm", "magnet_t"), ("rotor", "rotor_deg", "rotor_t")):
            v, t = self._motor_at(name, t_pc)
            g[col][first:n] = v
            g[tcol][first:n] = t

    def _write_event(self, ev):
        self._ids[id(ev)] = self._write_event_row(ev.kind, ev, data=dict(ev.extra or {}))

    def _write_event_row(self, kind, ev, data, buffer=None, segment=None, t=None):
        name = kind.replace("/", "_") or "unnamed"
        tab = self._ev_tables.get(name)
        if tab is None:
            tab = self._ev_tables[name] = _Table(self.f["events"].create_group(name), _event_columns())
        self._event_id += 1
        d = data or {}
        buf = buffer if buffer is not None else d.get("buffer_number")
        seg = segment if segment is not None else d.get("segment")
        tab.append({"event_id": self._event_id, "buffer_number": _int(buf), "segment": _int(seg),
                    "t_host": (ev.t if ev is not None else t) - self.t0,
                    "caller": ev.caller if ev is not None else "writer", "supersedes": _int(d.get("supersedes")),
                    "note": str(d.get("note", "")), "request": to_json(ev.request if ev is not None else None),
                    "readback": to_json(ev.readback if ev is not None else None), "data": to_json(d)})
        return self._event_id

    def _maybe_flush(self):
        if len(self._mt_rows) >= self.flush_frames or time.monotonic() - self._last_flush >= self.flush_s:
            self.flush()

    def flush(self):
        """Write every waiting row, rebuild /segments and /recordings, flush the file to disk."""
        if self.f is None:
            return
        self._release_pending()
        self._backfill_motors()
        if self._mt_rows:
            src = {r["_t_source"] for r in self._mt_rows}
            t_pc = [r["_t_pc"] for r in self._mt_rows]
            mag, mag_t = self._motor_at("magnet", t_pc)
            rot, rot_t = self._motor_at("rotor", t_pc)
            for i, r in enumerate(self._mt_rows):
                r["magnet_mm"], r["magnet_t"], r["rotor_deg"], r["rotor_t"] = mag[i], mag_t[i], rot[i], rot_t[i]
                self._mt.append(r)
            self._mt.g["t_camera"].attrs["source"] = "; ".join(sorted(src))
            self._mt_rows = []
            self._mt.flush()
        self._fill_calibration()
        if self._beads_tab is not None:
            self._beads_tab.rewrite(self._bead_rows())
        for tab in self._ev_tables.values():
            tab.flush()
        self._segs.rewrite(self._segment_rows())
        self._recs.rewrite(self._recording_rows())
        self.f.attrs["frames_written"] = self._mt.n if self._mt is not None else 0
        self.f.attrs["recordings_refused"] = len(self.refused)
        self.f.flush()
        self._last_flush = time.monotonic()

    # --- rebuilt tables --------------------------------------------------------------------------------------------
    def _value_at(self, key, t):
        best = None
        for th, k, v, src in self._hist:
            if k == key and th <= t and (best is None or th >= best[0]):
                best = (th, v, src)
        return best

    def _segment_rows(self):
        rows = []
        for n in sorted(set(self._seg_info) | set(self._seg_rows)):
            info, st = self._seg_info.get(n, {}), self._seg_rows.get(n)
            rate, roi, src = info.get("rate_Hz"), info.get("roi"), info.get("rate_source")
            if (rate is None or roi is None) and st is not None:
                rate = rate if rate is not None else st["rate"]
                roi = roi if roi is not None else st["roi"]
                src = "frame records (the pipeline's copy of the segment read-back)"
            start, end = info.get("start_pc_s", info.get("begin_event_t")), info.get("end_pc_s")
            t_ref = st["t_first_pc"] if st is not None else (math.inf if start is None else start)
            if st is not None:
                # a recording-on taken in this segment before its first recorded frame (by position, not arrival or
                # PC time: the settings were read before the flag changed) is in force at that frame
                for on in self.accepted:
                    x = on.extra
                    if x.get("segment") == n and (x.get("buffer_number") is None
                                                  or x["buffer_number"] < st["first"][0]):
                        t_ref = max(t_ref, on.t)
            exp, gain = self._value_at("exposure_ms", t_ref), self._value_at("gain_dB", t_ref)
            changes = [{"t_host": th - self.t0, "key": k, "value": v, "source": s} for th, k, v, s in sorted(
                self._hist, key=lambda h: h[0]) if (start is None or th >= start) and (end is None or th <= end)]
            measured = math.nan
            if st is not None and st["last"][0] > st["first"][0] and st["last"][1] > st["first"][1]:
                measured = (st["last"][0] - st["first"][0]) / (st["last"][1] - st["first"][1])
            ex = info.get("exposure_ms") if exp is None else exp[1]
            settings = {"rate_Hz": rate, "roi": roi, "exposure_ms_at_first_recorded_frame": ex,
                        "gain_dB_at_first_recorded_frame": None if gain is None else gain[1],
                        "exposure_source": None if exp is None else exp[2],
                        "gain_source": None if gain is None else gain[2],
                        "segment_start_exposure_ms": info.get("exposure_ms"), "history": changes}
            ended = info.get("ended", False)
            rows.append({
                "number": n, "reason": str(info.get("reason", "")),
                "t_start": math.nan if start is None else start - self.t0,
                "t_end": math.nan if end is None else end - self.t0, "pc_gap_s": _num(info.get("pc_gap_s")),
                "rate_Hz": _num(rate), "rate_Hz_measured": measured,
                "roi": np.asarray(roi if roi is not None and len(roi) == 4 else (-1, -1, -1, -1), dtype=np.int32),
                "exposure_ms": _num(ex), "gain_dB": math.nan if gain is None else _num(gain[1]),
                "settings": to_json(settings), "settings_source": src or "",
                "t_source": str(info.get("t_source") or (st or {}).get("t_source") or ""),
                "first_buffer": _int(info.get("first_buffer")), "last_buffer": _int(info.get("last_buffer")),
                "frames_received": _int(info.get("frames_received")) if ended else -1,
                "frames_recorded": st["n"] if st else 0, "frames_dropped": st["dropped"] if st else 0,
                "camera_gaps": st["gaps"] if st else 0,
                "camera_gaps_segment": _int(info.get("camera_gaps")) if ended else -1,
                "pipeline_drops_segment": _int(info.get("pipeline_drops")) if ended else -1,
                "tracking_errors": st["errors"] if st else 0, "end_loss": _int(info.get("end_loss"))})
        return rows

    def _recording_rows(self):
        ons = sorted(self.accepted, key=lambda e: e.t)
        offs = sorted(self.offs, key=lambda e: e.t)
        rows = []
        for i, on in enumerate(ons):
            nxt = ons[i + 1].t if i + 1 < len(ons) else math.inf
            off = next((o for o in offs if on.t <= o.t < nxt), None)
            x, ox = on.extra, (off.extra if off is not None else {})
            rows.append({"name": str(x.get("name") or ""), "event_id_on": self._ids.get(id(on), -1),
                         "t_on": on.t - self.t0,
                         "t_off": math.nan if off is None else off.t - self.t0, "on_segment": _int(x.get("segment")),
                         "on_buffer": _int(x.get("buffer_number")), "off_segment": _int(ox.get("segment")),
                         "off_buffer": _int(ox.get("buffer_number")), "settings": to_json(x.get("settings"))})
        return rows

    def _frame_rate_triple(self, run):
        rows = [r for r in self._segment_rows() if r["frames_recorded"]]
        r0 = rows[0] if rows else None
        cam = (self.metadata.get("presets") or {}).get("camera")
        preset = _num(cam.get("rate_Hz")) if isinstance(cam, dict) else math.nan
        triple = np.array([preset, r0["rate_Hz"] if r0 else math.nan, r0["rate_Hz_measured"] if r0 else math.nan])
        ds = run.create_dataset("frame_rate_hz", data=triple)
        ds.attrs["unit"] = "Hz"
        ds.attrs["description"] = ("preset / read back / measured for the first recorded segment (per segment: "
                                   "/segments rate_Hz, rate_Hz_measured)")
        rb, me = triple[1], triple[2]
        warn = [f"segment {r['number']}: read back {r['rate_Hz']:.6g} Hz, measured {r['rate_Hz_measured']:.6g} Hz"
                for r in rows if np.isfinite(r["rate_Hz_measured"])
                and abs(r["rate_Hz_measured"] - r["rate_Hz"]) > 1e-3 * r["rate_Hz"]]
        if len({r["rate_Hz"] for r in rows}) > 1:
            warn.append("the rate differs between segments; see /segments")
        if np.isfinite(rb) and np.isfinite(me) and not warn and abs(rb - me) > 1e-3 * rb:
            warn.append("read back and measured differ")
        if warn:
            ds.attrs["warning"] = "; ".join(warn)


def _put_str(group, name, value, json_=False):
    ds = group.create_dataset(name, data=value, dtype=STR)
    if json_:
        ds.attrs["content"] = "json"
    return ds


# --- reader ------------------------------------------------------------------------------------------------------------
def _value(ds):
    v = ds[()]
    if isinstance(v, bytes):
        v = v.decode("utf-8")
    elif isinstance(v, np.ndarray) and v.dtype == object:
        v = np.array([s.decode("utf-8") if isinstance(s, bytes) else s for s in v.ravel()], dtype=object
                     ).reshape(v.shape)
    if ds.attrs.get("content") == "json":
        if isinstance(v, str):
            return json.loads(v)
        return np.array([json.loads(s) for s in v.ravel()], dtype=object).reshape(v.shape) if v.size else v
    return v


def _read_group(g):
    out = {}
    for k, item in g.items():
        out[k] = _read_group(item) if isinstance(item, h5py.Group) else _value(item)
    return out


def read_run(path):
    """The whole file as nested dicts: {"attrs": root attributes, "mt", "beads", "segments", "recordings", "events":
    {kind: columns}, "metadata"}; strings decoded, JSON columns parsed. Datasets are numpy arrays."""
    with h5py.File(path, "r") as f:
        out = _read_group(f)
        out["attrs"] = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in f.attrs.items()}
        if "mt" in f:
            out["mt_attrs"] = {k: f["mt"][k].attrs.get("source") for k in ("t_camera",)}
    return out
