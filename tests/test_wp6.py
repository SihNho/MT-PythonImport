"""WP6 carries (docs/design/api.md "Implemented in WP6"): the motor poller, storage errors in the file, a failed
camera stop, the ROI origin at start (U23), wait_arrival's generation check, a send applied after a reply timeout,
draft replacement, the e-stop gap at run(), the `zero` warning, one focus read, start failures, crashes inside a
flush, back-fill across blocks, the camera reconnect as a segment end, the import order. Simulators and files only."""
import subprocess
import sys
import threading
import time
from pathlib import Path

import h5py
import numpy as np
import pytest
from conftest import FIXTURE, need
from test_acq import _connect
from test_data import HDF5Writer, ev, frame, rec_on
from test_protocol import HEAD, _rig, _until

from mtpy import api
from mtpy.api import estop, events
from mtpy.api.errors import DeviceError, NotReady
from mtpy.data import legacy_matrix, read_run
from mtpy.protocol import parse

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def cam(tmp_path, monkeypatch):
    """Simulated rig (TEST profile) with the synthetic camera."""
    yield from _connect(tmp_path, monkeypatch)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Simulated rig on the TEST profile with the synthetic force table, no acquisition."""
    yield from _rig(tmp_path, monkeypatch, True)


def _since(n, kind=None):
    return [e for e in events.events()[n:] if kind is None or e.kind == kind]


# --- per-frame motor reading --------------------------------------------------------------------------------------------
def test_motor_poller_gives_every_frame_a_reading_off_the_frame_path(cam, tmp_path, monkeypatch):
    """Readings through the API on the poller thread (never the camera or tracking thread), one before the first
    frame, ~20 per second during a move; every recorded row has a magnet and rotor value, and the values follow the
    move (more distinct values than move read-backs)."""
    threads = []
    real = api.magnet.position

    def position():
        threads.append(threading.current_thread().name)
        return real()
    monkeypatch.setattr(api.magnet, "position", position)
    api.acq.start(record=True, name="poll", folder=tmp_path)
    api.acq.wait_frames(10, 5)
    api.magnet.move_to(5.0).wait(10)                             # 0.5 s at 10 mm/s
    api.acq.wait_frames(10, 5)
    st = api.acq.stop()
    assert st["stop"] == "complete" and st["sink_failures"] == 0, st["sink_error"]
    assert st["motor_poll"]["reads"] >= 10 and st["motor_poll"]["errors"] == {}
    assert set(threads) <= {"acq-motor-poll", threading.current_thread().name}
    assert "acq-motor-poll" in threads and not {"acq-camera", "acq-tracking", "acq-sink"} & set(threads)
    run = read_run(tmp_path / "poll.h5")
    mt = run["mt"]
    assert np.isfinite(mt["magnet_mm"]).all() and np.isfinite(mt["rotor_deg"]).all()
    assert mt["magnet_mm"][0] == pytest.approx(0.0, abs=0.01) and mt["magnet_mm"][-1] == pytest.approx(5.0, abs=0.01)
    assert len(np.unique(np.round(mt["magnet_mm"], 3))) > 4       # intermediate positions, not only read-backs
    rd = run["events"]["motor_reading"]
    assert len(rd["event_id"]) >= 10 and (rd["buffer_number"] >= -1).all()
    assert {d["device"] for d in rd["data"]} == {"magnet", "rotor"}
    assert (np.diff(mt["magnet_t"]) >= 0).all()                  # the last reading before each frame


def test_slow_or_failing_motor_never_blocks_acquisition(cam, monkeypatch):
    """A magnet that answers in 0.3 s and then stops answering delays only the poller: frames keep arriving at the
    camera rate; a failing device gives one `motor_reading_error` per new error, not one per poll."""
    dev = api.devices.service("magnet").device
    real = dev.position

    def slow():
        time.sleep(0.3)
        return real()
    monkeypatch.setattr(dev, "position", slow)
    n = len(events.events())
    api.acq.start(record=False)
    rate = api.acq.status()["segments"][-1]["rate_Hz"]
    t0, f0 = time.monotonic(), api.acq.status()["frames_received"]
    api.acq.wait_frames(int(rate), 5)                            # one second of frames
    dt = time.monotonic() - t0
    assert dt < 1.5, f"{rate:g} frames took {dt:.2f} s"
    assert api.acq.status()["frames_received"] - f0 >= int(rate)
    dev.fault = "no_reply"
    api.acq.wait_frames(int(rate), 5)
    st = api.acq.status()
    assert "magnet" in st["motor_poll"]["errors"]
    errs = _since(n, "motor_reading_error")
    assert len(errs) == 1 and errs[0].extra["device"] == "magnet"
    dev.fault = None
    api.acq.stop()


# --- storage errors in the file -------------------------------------------------------------------------------------
def test_sink_error_is_stored_in_the_file(cam, tmp_path, monkeypatch):
    api.acq.start(record=True, name="err", folder=tmp_path)
    api.acq.wait_frames(5, 5)
    w = api.acq.sink()
    real = w.write_event

    def write_event(e):
        if e.kind == "mark":
            raise OSError("disk full (test)")
        return real(e)
    monkeypatch.setattr(w, "write_event", write_event)
    api.acq.mark("lost mark")
    api.acq.wait_frames(5, 5)
    st = api.acq.stop()
    assert st["sink_failures"] == 1 and st["sink_error"] == "OSError: disk full (test)"
    run = read_run(tmp_path / "err.h5")
    assert run["attrs"]["sink_failures"] == 1 and "mark" not in run["events"]
    rows = run["events"]["sink_error"]
    assert len(rows["event_id"]) == 1 and rows["caller"][0] == "writer"
    assert rows["data"][0] == {"item": "event", "error": "OSError: disk full (test)", "segment": None,
                               "buffer": None, "event_kind": "mark"}


def test_sink_error_before_the_file_exists_is_written_when_it_opens(tmp_path):
    w = HDF5Writer(tmp_path / "late.h5")
    w.note_error("frame", "RecordingRefused: test", segment=1, buffer=3)
    w.write_event(rec_on(0.0))
    w.write_frame(frame(1, 4, 0.1))
    w.close()
    run = read_run(tmp_path / "late.h5")
    assert run["attrs"]["sink_failures"] == 1
    assert run["events"]["sink_error"]["buffer_number"].tolist() == [3]


# --- a failed camera stop -------------------------------------------------------------------------------------------
def test_failed_stop_does_not_hide_a_running_camera(cam, monkeypatch):
    dev = api.devices.service("camera").device
    real_stop = dev.stop_acquisition
    api.acq.start(record=False)
    api.acq.wait_frames(3, 5)
    monkeypatch.setattr(dev, "stop_acquisition", lambda: (_ for _ in ()).throw(RuntimeError("stuck (test)")))
    n = len(events.events())
    with pytest.raises(DeviceError, match="stuck"):
        api.acq.stop()
    st = api.acq.status()
    assert st["camera_stop"]["camera_acquiring"] is True and st["camera_stop"]["stop_call"].startswith("failed")
    failed = [e for e in _since(n, "acquisition") if e.extra.get("action") == "stop failed"]
    assert len(failed) == 1 and failed[0].extra["camera_acquiring"] is True
    with pytest.raises(NotReady, match="already acquiring"):
        api.acq.start()
    monkeypatch.setattr(dev, "stop_acquisition", real_stop)
    real_stop()
    api.acq.start(record=False)
    st = api.acq.stop()
    assert st["camera_stop"] == {"stop_call": "ok", "camera_acquiring": False}


# --- U23: ROI origin at bead selection vs start ------------------------------------------------------------------------
def test_roi_origin_moved_while_stopped_is_refused_at_start(cam):
    need(FIXTURE / "cal002")
    api.beads.select([1, 2], cal_path=FIXTURE / "cal002")
    assert api.beads.selected().roi == (0, 0, 1280, 1024)
    api.camera.set_roi(16, 0, 1264, 1024)                       # moved while acquisition is stopped
    n = len(events.events())
    with pytest.raises(NotReady, match=r"ROI origin \(16, 0\) is not the origin \(0, 0\)"):
        api.acq.start()
    assert not api.acq.running() and [e.kind for e in _since(n)] == ["refused"]
    api.camera.set_roi(0, 0, 1280, 1024)
    api.acq.start()
    api.acq.wait_frames(3, 5)
    api.acq.stop()


# --- Motion.wait_arrival generation check -----------------------------------------------------------------------------
def test_estop_engaged_and_released_during_a_move_ends_it_cancelled(rig, monkeypatch):
    """Engage + release while the move is waited for: the axis is halted and the flag is clear again; the generation
    check makes it NotReady + `cancelled` (without it the halt looks like an arrival -> read-back DeviceError)."""
    dev = api.devices.service("magnet").device
    real, polls = dev.moving, []

    def moving():
        polls.append(1)
        if len(polls) == 2:
            estop.engage("test: during the move")
            with events.as_caller("gui"):
                estop.clear()
        return real()
    monkeypatch.setattr(dev, "moving", moving)
    n = len(events.events())
    m = api.magnet.move_to(10.0)
    with pytest.raises(NotReady, match="emergency stop"):
        m.wait(10)
    assert not estop.active() and [e.kind for e in _since(n) if e.kind in ("act", "cancelled", "device_error")] == \
        ["cancelled"]
    p = api.magnet.position()
    time.sleep(0.2)
    assert abs(api.magnet.position() - p) < 0.005 and p < 9.0


# --- a send applied after the caller's reply timeout ------------------------------------------------------------------
def test_send_applied_after_reply_timeout_is_stopped_again(rig, monkeypatch):
    svc = api.devices.service("magnet")
    dev = svc.device
    real = dev.move_to

    def slow_move(*a):
        time.sleep(0.5)
        return real(*a)
    monkeypatch.setattr(dev, "move_to", slow_move)
    monkeypatch.setattr(svc, "reply_timeout_s", 0.2)
    p0 = api.magnet.position()
    n = len(events.events())
    with pytest.raises(DeviceError, match="no reply for 0.2 s"):
        api.magnet.move_to(10.0, speed_mm_s=5.0).wait(5)
    _until(lambda: any(e.extra.get("applied_after_timeout") for e in _since(n, "device_fault")))
    time.sleep(0.2)
    assert abs(api.magnet.position() - p0) < 0.05                # stopped at once, never ran on to 10 mm
    assert not [e for e in _since(n, "act")]


# --- protocol carries -------------------------------------------------------------------------------------------------
def test_offer_edit_replacing_a_pending_draft_logs_an_event():
    from mtpy.protocol.engine import Engine
    eng = Engine(parse(HEAD + "wait t=1\n"))
    d1, d2 = parse(HEAD + "wait t=2\n"), parse(HEAD + "wait t=3\n")
    n = len(events.events())
    eng.offer_edit(d1)
    assert _since(n, "protocol_edit") == []
    eng.offer_edit(d2)
    ed = _since(n, "protocol_edit")
    assert len(ed) == 1 and ed[0].extra["action"] == "replaced"
    assert ed[0].extra["old_sha256"] == d1.sha256 and ed[0].extra["new_sha256"] == d2.sha256
    assert eng.status()["edit_pending"]


def test_estop_engaged_and_released_during_the_run_check_refuses_the_run(rig, monkeypatch):
    import mtpy.protocol.check as chk
    real = chk.check

    def check(*a, **k):
        estop.engage("test: during run()'s check")
        with events.as_caller("gui"):
            estop.clear()
        return real(*a, **k)
    monkeypatch.setattr(chk, "check", check)
    sent = []
    dev = api.devices.service("magnet").device
    real_move = dev.move_to
    monkeypatch.setattr(dev, "move_to", lambda *a: (sent.append(a), real_move(*a))[1])
    n = len(events.events())
    with pytest.raises(NotReady, match="engaged \\(and released\\) while the protocol was checked"):
        api.protocol.run(parse(HEAD + "hold f=1 t=0.2\n"))
    assert not api.protocol.running() and sent == []
    assert [e.kind for e in _since(n) if e.kind in ("refused", "protocol")] == ["refused"]


def test_estop_between_the_check_and_the_engine_start_aborts_with_nothing_sent(rig, monkeypatch):
    from mtpy.protocol.engine import Engine
    real_start = Engine.start

    def start(self):
        estop.engage("test: between check and engine start")
        with events.as_caller("gui"):
            estop.clear()
        return real_start(self)
    monkeypatch.setattr(Engine, "start", start)
    sent = []
    dev = api.devices.service("magnet").device
    real_move = dev.move_to
    monkeypatch.setattr(dev, "move_to", lambda *a: (sent.append(a), real_move(*a))[1])
    api.protocol.run(parse(HEAD + "hold f=1 t=0.2\n"))
    st = api.protocol.wait(10)
    assert st["state"] == "aborted" and sent == []


def test_zero_logs_a_warning_before_the_magnet_moves(rig):
    n = len(events.events())
    api.protocol.run(parse(HEAD + "move mm=1\nzero t=0.1\n"))
    assert api.protocol.wait(10)["state"] == "completed"
    new = _since(n)
    warn = [i for i, e in enumerate(new) if e.kind == "protocol" and e.extra.get("action") == "warning"]
    acts = [i for i, e in enumerate(new) if e.kind == "act" and e.request["quantity"] == "magnet_position_mm"]
    assert len(warn) == 1 and len(acts) == 2 and acts[0] < warn[0] < acts[1]
    assert new[warn[0]].extra["line"] == 4 and "tracking zero (U12) is NOT set" in new[warn[0]].extra["reason"]


def test_focus_reference_is_read_once_for_check_and_engine(rig, monkeypatch):
    reads = []
    real = api.focus.position

    def position():
        reads.append(threading.current_thread().name)
        return real()
    monkeypatch.setattr(api.focus, "position", position)
    z0 = real()
    n = len(events.events())
    api.protocol.run(parse(HEAD + "focus um=5\n"))
    assert len(reads) == 1                                       # check and engine share this one read
    eng = api.protocol._engine
    assert eng.focus_z0 == pytest.approx(z0, abs=0.2)
    assert api.protocol.wait(10)["state"] == "completed" and len(reads) == 1
    start = [e for e in _since(n, "protocol") if e.extra["action"] == "start"]
    assert start[0].extra["focus_z0"] == eng.focus_z0


def test_engine_start_failure_logs_an_event(rig, monkeypatch):
    from mtpy.protocol.engine import Engine
    monkeypatch.setattr(Engine, "start", lambda self: (_ for _ in ()).throw(RuntimeError("no thread (test)")))
    n = len(events.events())
    with pytest.raises(RuntimeError, match="no thread"):
        api.protocol.run(parse(HEAD + "wait t=0.1\n"))
    ev_ = [e for e in _since(n, "protocol") if e.extra["action"] == "start_failed"]
    assert len(ev_) == 1 and "no thread (test)" in ev_[0].extra["reason"] and not api.protocol.running()


def test_focus_read_failure_at_start_logs_an_event(rig, monkeypatch):
    def broken():
        raise DeviceError("focus", "position", "unplugged (test)")
    monkeypatch.setattr(api.focus, "position", broken)
    n = len(events.events())
    with pytest.raises(DeviceError):
        api.protocol.run(parse(HEAD + "focus um=5\n"))
    ev_ = [e for e in _since(n, "protocol") if e.extra["action"] == "start_failed"]
    assert len(ev_) == 1 and ev_[0].extra["reason"].startswith("focus read") and not api.protocol.running()


# --- crashes inside a flush; back-fill across blocks -------------------------------------------------------------------
_CRASH_IN_FLUSH = r"""
import os, sys
sys.path.insert(0, sys.argv[2])
import numpy as np
import mtpy.data.hdf5 as h
from test_data import HDF5Writer, ev, frame, rec_on
w = HDF5Writer(sys.argv[1], flush_frames=10**6, flush_s=10**6)
w.write_event(rec_on(0.0))
for b in range(100):
    w.write_frame(frame(1, b, 0.1 + b / 90))
w.flush()
if sys.argv[3] == "mt columns":       # a crash after 3 of the /mt columns of the next flush were extended and written
    for b in range(100, 140):
        w.write_frame(frame(1, b, 0.1 + b / 90))
    real = h._Table._write
    def write(self, start, cols):
        if self.g.name != "/mt":
            return real(self, start, cols)
        m = len(next(iter(cols.values())))
        for i, (name, (dt, _, _, _)) in enumerate(self.cols.items()):
            if i == 3:
                os._exit(1)
            self.g[name].resize(start + m, axis=0)
            self.g[name][start:start + m] = np.asarray(cols[name], dtype=object if dt is h.STR else dt)
    h._Table._write = write
else:                                 # a crash inside the back-fill: magnet rewritten, rotor not yet
    w.write_event(ev(0.3, "act", {"quantity": "magnet_position_mm", "value": 7.0}, 7.0))
    real = h.HDF5Writer._motor_at
    def motor_at(self, name, t):
        if name == "rotor":
            os._exit(1)
        return real(self, name, t)
    h.HDF5Writer._motor_at = motor_at
w.flush()
"""


@pytest.mark.parametrize("mode", ["mt columns", "back-fill"])
def test_crash_inside_a_flush(tmp_path, mode):
    """Tested crash points inside a flush (documented in mtpy.data.hdf5): the file opens, closed_cleanly = 0, the
    readers give exactly the rows of the last complete flush; in the back-fill case the magnet column is already
    back-filled (the late reading), the rotor column not."""
    script = tmp_path / "crash.py"
    script.write_text(_CRASH_IN_FLUSH, encoding="utf-8")
    p = subprocess.run([sys.executable, str(script), str(tmp_path / "c.h5"), str(Path(__file__).parent), mode],
                       check=False, capture_output=True, text=True, timeout=60, cwd=str(REPO))
    assert p.returncode == 1, p.stderr
    with h5py.File(tmp_path / "c.h5", "r") as f:
        assert f.attrs["closed_cleanly"] == 0 and f.attrs["frames_written"] == 100
        lengths = {f["mt"][k].shape[0] for k in f["mt"]}
    assert lengths == ({100, 140} if mode == "mt columns" else {100})
    run = read_run(tmp_path / "c.h5")
    assert all(len(v) == 100 for v in run["mt"].values())
    assert run["mt"]["buffer_number"].tolist() == list(range(100))
    if mode == "mt columns":
        assert run["recovered"] == {"mt_rows": 100, "rows_of_unfinished_flush_left_out": 40}
    else:
        fin = np.isfinite(run["mt"]["magnet_mm"])                 # back-filled: the rows after the reading (0.3 s)
        assert not fin[0] and fin[-1] and (np.diff(fin.astype(int)) >= 0).all()
        assert set(run["mt"]["magnet_mm"][fin].tolist()) == {7.0}
        assert np.isnan(run["mt"]["rotor_deg"]).all()             # the rotor columns were not reached
    m = legacy_matrix(tmp_path / "c.h5")
    assert m[1][:, 0].tolist() == list(range(100))


def test_late_motor_reading_backfills_across_several_flushed_blocks(tmp_path):
    """WP4-r2 carry: 9000 flushed rows (three 4096-row scan blocks), then a reading timed before row 100: rows
    100..8999 are rewritten, rows 0..99 keep NaN."""
    w = HDF5Writer(tmp_path / "b.h5", flush_frames=3000, flush_s=10**6)
    w.write_event(rec_on(-1.0))
    for b in range(9000):
        w.write_frame(frame(1, b, 0.001 * b))
    assert w._mt.n == 9000
    w.write_event(ev(0.0995, "act", {"quantity": "magnet_position_mm", "value": 7.0}, 7.0))
    w.close()
    run = read_run(tmp_path / "b.h5")
    mag = run["mt"]["magnet_mm"]
    assert np.isnan(mag[:100]).all() and (mag[100:] == 7.0).all()
    t = run["mt"]["magnet_t"][100:] + run["attrs"]["t0_unix"]
    assert np.allclose(t, t[0]) and np.isnan(run["mt"]["magnet_t"][:100]).all()


# --- the camera reconnect as a segment end ----------------------------------------------------------------------------
def test_camera_reconnect_while_recording_is_a_segment_end(cam, tmp_path):
    api.camera.apply_preset({"name": "test 90 Hz", "rate_Hz": 90.0, "exposure_ms": 2.0, "gain_dB": 0.0})
    api.acq.start(record=True, name="recon", folder=tmp_path)
    api.acq.wait_frames(10, 5)
    api.devices.reconnect("camera")
    api.acq.wait_frames(10, 5)
    st = api.acq.stop()
    assert [s["reason"] for s in st["segments"]] == ["start", "camera reconnect"]
    run = read_run(tmp_path / "recon.h5")
    seg = run["segments"]
    assert seg["reason"].tolist() == ["start", "camera reconnect"] and (seg["frames_recorded"] >= 10).all()
    assert seg["rate_Hz"][1] == pytest.approx(90.0, rel=1e-4)             # the preset was re-applied (U15)
    assert run["metadata"]["presets"]["camera"]["name"] == "test 90 Hz"
    assert np.isfinite(run["metadata"]["run"]["frame_rate_hz"]).all()      # preset / read back / measured


def test_import_order_devices_first_works():
    """The mtpy.api <-> mtpy.devices import cycle (WP3 carry): both orders import in a fresh interpreter."""
    for first in ("mtpy.devices", "mtpy.devices.sim", "mtpy.api", "mtpy.acq", "mtpy.data", "mtpy.protocol"):
        p = subprocess.run([sys.executable, "-c", f"import {first}; from mtpy import api; print(api.VERSION)"],
                           check=False, capture_output=True, text=True, timeout=60, cwd=str(REPO))
        assert p.returncode == 0 and p.stdout.strip() == api.VERSION, (first, p.stderr)
