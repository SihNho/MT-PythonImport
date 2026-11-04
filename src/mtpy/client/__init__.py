"""The client of the engine process (decision 0029): `api` with the same module / function names as `mtpy.api`,
each a remote call; `events` replaying the engine's events to local subscribers; `api.acq.display()` read from the
shared-memory snapshot. Scripts keep importing `mtpy.api` in-process; the GUI uses this.

    from mtpy.client import connect
    c = connect()                       # the running engine named in the info file (or launch() one)
    c.api.devices.connect({"backend": "sim"})
    m = c.api.focus.move_to(1.0); m.wait(5)
    snap = c.api.acq.display()
    c.events.subscribe(print)
"""
import contextlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from multiprocessing import shared_memory
from multiprocessing.connection import Client as _Connect
from types import SimpleNamespace

import numpy as np

from mtpy.api import errors
from mtpy.engine import GOOD_OFF, HEADER, HEADER_SIZE, IMG_OFF, INFO_FILE, XYZ_OFF

API_MODULES = ("acq", "beads", "camera", "data", "devices", "emccd", "estop", "focus", "light", "magnet", "protocol",
               "rig", "rotor", "safety", "stage", "sync", "tracking", "zscan")


class EngineError(errors.MtpyError):
    """An error class the client does not know, or the engine gone."""


class _Events:
    """The client's event log: the engine's events as they arrive, local subscribers, the caller context sent with
    every call (events.caller() of the GUI is 'gui')."""

    def __init__(self, client):
        self._c, self._events, self._subs, self._lock = client, [], [], threading.Lock()
        self._caller = "unknown"

    def caller(self):
        return self._caller

    @contextmanager
    def as_caller(self, name):
        old, self._caller = self._caller, name
        try:
            yield
        finally:
            self._caller = old

    def subscribe(self, fn):
        with self._lock:
            self._subs.append(fn)

        def unsubscribe():
            with self._lock:
                if fn in self._subs:
                    self._subs.remove(fn)
        return unsubscribe

    def events(self, since=None):
        with self._lock:
            return [e for e in self._events if since is None or e.t > since]

    def history(self):
        """The engine's whole event list (from before this client connected)."""
        return self._c.call("events.events")

    def _arrived(self, ev):
        with self._lock:
            self._events.append(ev)
            subs = list(self._subs)
        for fn in subs:
            with contextlib.suppress(Exception):      # a subscriber's failure is its own
                fn(ev)


class _Motion:
    def __init__(self, client, mid, attrs):
        self._c, self._id = client, mid
        self.__dict__.update(attrs)

    def wait(self, timeout_s):
        return self._c.call(f"motion.{self._id}.wait", timeout_s)

    def cancel(self):
        return self._c.call(f"motion.{self._id}.cancel")

    @property
    def done(self):
        return self._c.call(f"motion.{self._id}.done")


class _Module:
    def __init__(self, client, name):
        self._c, self._name = client, name

    def __getattr__(self, fn):
        if fn.startswith("_"):
            raise AttributeError(fn)
        return lambda *a, **k: self._c.call(f"{self._name}.{fn}", *a, **k)


class _Acq(_Module):
    def display(self):
        return self._c.snapshot()


class _Api:
    def __init__(self, client):
        for name in API_MODULES:
            setattr(self, name, _Acq(client, name) if name == "acq" else _Module(client, name))
        for cls in ("DeviceError", "MagnetStall", "MtpyError", "NotReady", "SafetyRefused", "ScriptError", "Timeout"):
            setattr(self, cls, getattr(errors, cls))
        self.errors = errors


_BUILTIN = {"ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError, "AttributeError": AttributeError,
            "IndexError": IndexError, "RuntimeError": RuntimeError, "TimeoutError": TimeoutError,
            "FileNotFoundError": FileNotFoundError}


def _rebuild(cls_name, text):
    """The engine's exception as its class with the text it had. An mtpy class is built without its __init__: the
    wire carries the text only, and DeviceError(text) raised TypeError (rig 2026-11-05, "Cal+") while
    ScriptError(text) listed every character as an error ("355 errors")."""
    cls = getattr(errors, cls_name, None)
    if cls is None:
        return _BUILTIN.get(cls_name, EngineError)(text)
    e = cls.__new__(cls)
    Exception.__init__(e, text)
    return e


class Client:
    def __init__(self, address, authkey, snapshot_name=None):
        self._conn = _Connect(tuple(address), authkey=bytes.fromhex(authkey) if isinstance(authkey, str) else authkey)
        self._lock, self._seq, self._pending = threading.Lock(), 0, {}
        self.events = _Events(self)
        self.api = _Api(self)
        self.alive = True
        self._shm = shared_memory.SharedMemory(name=snapshot_name) if snapshot_name else None
        self._last_seq, self._last_snap = 0, None
        threading.Thread(target=self._receive, name="client-receive", daemon=True).start()

    def _receive(self):
        while True:
            try:
                msg = self._conn.recv()
            except (EOFError, OSError):
                self.alive = False
                with self._lock:
                    for ev in self._pending.values():
                        ev["reply"] = ("err", None, "EngineError", "engine gone")
                        ev["event"].set()
                return
            if msg[0] == "event":
                self.events._arrived(msg[1])
            else:
                with self._lock:
                    slot = self._pending.pop(msg[1], None)
                if slot is not None:
                    slot["reply"] = msg
                    slot["event"].set()

    def call(self, _name, *args, **kwargs):
        if not self.alive:
            raise EngineError("engine gone")
        slot = {"event": threading.Event(), "reply": None}
        with self._lock:
            self._seq += 1
            seq = self._seq
            self._pending[seq] = slot
            self._conn.send(("call", seq, self.events.caller(), _name, args, kwargs))
        slot["event"].wait()
        kind, _, *rest = slot["reply"]
        if kind == "ok":
            r = rest[0]
            if isinstance(r, tuple) and len(r) == 3 and r[0] == "motion":
                return _Motion(self, r[1], r[2])
            return r
        raise _rebuild(*rest)

    def ping(self, timeout_s=2.0):
        """True when the engine answered within timeout_s (the GUI's watchdog)."""
        done = threading.Event()
        out = {}

        def go():
            try:
                out["r"] = self.call("engine.ping")
            except Exception as e:  # noqa: BLE001
                out["e"] = e
            done.set()
        threading.Thread(target=go, daemon=True).start()
        return done.wait(timeout_s) and "r" in out

    def snapshot(self):
        """The latest display snapshot from shared memory (None before the first frame): seq, image, record, result
        as the GUI reads them; the same object again while seq has not moved."""
        if self._shm is None:
            return None
        buf = self._shm.buf
        for _ in range(3):
            seq, h, w, n, seg, bn, t_cam, rate, t_pc, rec = HEADER.unpack(bytes(buf[:HEADER_SIZE]))
            if seq == 0:
                return None
            if seq == self._last_seq:
                return self._last_snap
            image = np.frombuffer(bytes(buf[IMG_OFF:IMG_OFF + h * w]), dtype=np.uint8).reshape(h, w)
            xyz = np.frombuffer(bytes(buf[XYZ_OFF:XYZ_OFF + n * 24]), dtype=np.float64).reshape(n, 3) if n else None
            good = np.frombuffer(bytes(buf[GOOD_OFF:GOOD_OFF + n]), dtype=np.uint8).astype(bool) if n else None
            seq2 = struct.unpack_from("<Q", buf, 0)[0]
            if seq2 == seq:
                self._last_seq = seq
                self._last_snap = SimpleNamespace(
                    seq=seq, image=image, result=SimpleNamespace(xyz=xyz, good=good),
                    record=SimpleNamespace(segment=seg, buffer_number=bn, t_camera_s=t_cam, rate_Hz=rate, t_pc_s=t_pc,
                                           recording=bool(rec)))
                return self._last_snap
        return self._last_snap

    def exit_engine(self):
        try:
            return self.call("engine.exit")
        finally:
            self.close()

    def close(self):
        self.alive = False
        try:
            self._conn.close()
        finally:
            if self._shm is not None:
                self._shm.close()


def info(path=INFO_FILE):
    """The running engine's address, authkey, pid, snapshot name - or None when no engine wrote the file."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def connect(path=INFO_FILE):
    i = info(path)
    if i is None:
        raise EngineError(f"no engine info at {path}; launch() one first")
    return Client(i["address"], i["authkey"], i.get("snapshot"))


def attach(path=INFO_FILE, timeout_s=2.0):
    """The Client of an engine that is already running and answers - the window that launched it died and the engine
    kept the rig (docs/design/engine-process.md 5; the 2026-11-04 22:28 case) - or None."""
    i = info(path)
    if i is None:
        return None
    try:
        c = Client(i["address"], i["authkey"], i.get("snapshot"))
    except Exception:  # noqa: BLE001 - nobody listens, a stale info file, the snapshot gone: no engine
        return None
    if c.ping(timeout_s):
        return c
    c.close()
    return None


def launch(config=None, timeout_s=60.0, path=INFO_FILE, extra_env=None, log=None):
    """Start `python -m mtpy.engine` (same interpreter) and connect to it. Returns (Client, Popen).
    log: a file the engine's stderr goes to (tracebacks, faulthandler). On Windows the engine gets no console window,
    so closing the terminal the GUI was started from does not take the engine, and the rig, with it."""
    if os.path.exists(path):
        os.remove(path)
    env = dict(os.environ, MTPY_ENGINE_INFO=path, **(extra_env or {}))
    cmd = [sys.executable, "-m", "mtpy.engine"] + (["--config", str(config)] if config else [])
    t_launch = time.time()
    err = open(log, "a", encoding="utf-8") if log else None  # noqa: SIM115 - the child owns it from here
    proc = subprocess.Popen(cmd, env=env, stdout=err, stderr=err, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        i = info(path)
        # the file was removed above, so a fresh one is ours; the pid is not compared: a venv's python.exe on
        # Windows is a launcher whose child is the interpreter
        if i is not None and i.get("started", 0) >= t_launch - 1:
            return Client(i["address"], i["authkey"], i.get("snapshot")), proc
        if proc.poll() is not None:
            raise EngineError(f"engine exited with {proc.returncode} before it listened")
        time.sleep(0.1)
    proc.kill()
    raise EngineError(f"engine did not listen within {timeout_s:g} s")
