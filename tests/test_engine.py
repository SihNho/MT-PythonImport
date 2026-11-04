"""The engine process and its client (decision 0029) on the simulator: calls with the caller name, Motion handles,
errors re-raised by class, events streamed, the display snapshot through shared memory, exit with cleanup."""
import json
import os
import shutil
import time

import pytest
from test_devices import REPO_CONFIG, TEST_LIMITS

from mtpy.api.errors import NotReady, SafetyRefused
from mtpy.client import EngineError, attach, launch


def _until(cond, timeout_s, what):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError(f"timeout: {what}")


@pytest.fixture
def engine(tmp_path):
    shutil.copytree(REPO_CONFIG, tmp_path / "config")
    path = tmp_path / "config" / "safety_profile.json"
    p = json.loads(path.read_text(encoding="utf-8"))
    for q, (lo, hi) in TEST_LIMITS.items():
        p["limits"][q].update(min=lo, max=hi, verified=True, source="TEST ONLY")
        if q == "focus_z_um":
            p["limits"][q]["relative_to"] = "session_start"
    p["unverified"], p["by"] = [], "TEST ONLY"
    path.write_text(json.dumps(p), encoding="utf-8")
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env = {"PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    client, proc = launch(config=tmp_path / "config", path=str(tmp_path / "engine.json"), extra_env=env)
    yield client, proc
    if client.alive:
        with pytest.MonkeyPatch.context():
            try:
                client.exit_engine()
            except EngineError:
                pass
    try:
        proc.wait(30)
    except Exception:  # noqa: BLE001
        proc.kill()


def test_calls_motions_errors_events_and_snapshot_cross_the_process_boundary(engine, tmp_path):
    client, proc = engine
    api, events = client.api, client.events
    seen = []
    events.subscribe(seen.append)
    assert client.ping()
    with events.as_caller("gui"):
        st = api.devices.connect({"backend": "sim"})
    assert st["camera"]["state"] == "connected" and st["focus"]["state"] == "connected"
    _until(lambda: any(e.kind == "devices" and e.extra.get("action") == "connect" for e in seen), 5, "connect event")
    assert next(e for e in seen if e.kind == "devices").caller == "gui"      # the caller crossed with the call
    # a Motion: handle on the client, wait() reads back
    m = api.focus.move_to(1.0)
    assert m.wait(10) == pytest.approx(1.0, abs=0.01) and api.focus.position() == pytest.approx(1.0, abs=0.01)
    # errors come back as their own class
    with pytest.raises(SafetyRefused):
        api.magnet.set_touch_position(float("nan"))
    with pytest.raises(NotReady):
        api.acq.stop()
    # acquisition: status over the wire, the snapshot through shared memory
    api.acq.start(record=True, name="eng", folder=str(tmp_path / "runs"))
    assert api.acq.wait_frames(20, 10)
    _until(lambda: client.snapshot() is not None, 5, "snapshot")
    snap = api.acq.display()
    assert snap.image.shape == tuple(api.acq.status()["segments"][0]["roi"][2:][::-1]) and snap.image.dtype.name == "uint8"
    assert snap.record.recording and snap.record.rate_Hz > 0 and snap.seq >= 1
    seq = snap.seq
    _until(lambda: (client.snapshot() or snap).seq > seq, 5, "a newer snapshot")
    st = api.acq.stop()
    assert st["recording"] is False and st["frames_received"] >= 20 and (tmp_path / "runs" / "eng.h5").exists()
    assert any(e.kind == "recording" for e in seen)
    assert len(client.events.history()) >= len(seen) and client.events.history()[0].caller == "gui"
    # exit: devices closed by the engine's cleanup, the info file gone, the process ended
    assert api.devices.status()
    client.exit_engine()
    proc.wait(30)
    assert proc.returncode == 0 and not os.path.exists(tmp_path / "engine.json")
    with pytest.raises(EngineError):
        api.devices.status()


def test_attach_finds_the_running_engine_and_nothing_after_it_exits(engine, tmp_path):
    """A window that starts while an engine runs (its previous window died) attaches to it instead of launching a
    second one (2026-11-04 22:28); with no engine, attach() is None."""
    client, proc = engine
    path = str(tmp_path / "engine.json")
    c2 = attach(path)
    assert c2 is not None and c2.call("engine.ping")["pid"] == client.call("engine.ping")["pid"]
    c2.close()
    client.exit_engine()
    proc.wait(30)
    assert attach(path) is None
