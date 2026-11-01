"""The engine process (decision 0029, docs/design/engine-process.md): hosts the whole `mtpy.api` behind a local
listener. A client sends `("call", seq, caller, "module.function", args, kwargs)` and gets `("ok", seq, result)` or
`("err", seq, class_name, message)`; every event logged in the engine streams to every client as `("event", ev)`;
the display tap's latest snapshot is written to a shared-memory block the client reads at its own rate.

A `Motion` the API returns is kept in a table and handed over as `("motion", id, attrs)`; the client proxy calls
`motion.<id>.wait` / `cancel` / `done`. The engine opens no device by itself: `api.devices.connect` does, on the
first call, and holds the rig lock as in-process (0026). On exit with devices still open the engine runs
`api.devices.disconnect()` (cleanup rule).
"""
import contextlib
import json
import os
import pickle
import queue
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import shared_memory
from multiprocessing.connection import Listener
from types import MappingProxyType

import numpy as np

from mtpy import api
from mtpy.api import events
from mtpy.devices.base import Motion

INFO_FILE = os.environ.get("MTPY_ENGINE_INFO",
                           os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "mtpy", "engine.json"))
MAX_H, MAX_W, MAX_BEADS = 2048, 2560, 4096
# seq u8 | h, w, n u4 | segment i4 | buffer_number i8 | t_camera_s, rate_Hz, t_pc_s f8 | recording u1 | pad
HEADER = struct.Struct("<QIIIiqdddB7x")
HEADER_SIZE = HEADER.size
XYZ_OFF = HEADER_SIZE
GOOD_OFF = XYZ_OFF + MAX_BEADS * 3 * 8
IMG_OFF = GOOD_OFF + MAX_BEADS
SNAP_BYTES = IMG_OFF + MAX_H * MAX_W
MOTION_ATTRS = ("what", "requested_mm", "applied_mm", "coerced")


class SharedSnapshot:
    """Writer side: copies the display tap's latest snapshot into the block whenever its seq moved (a thread at up
    to 100 Hz). Readers see seq last: they re-read when it changed under them."""

    def __init__(self, name):
        self.shm = shared_memory.SharedMemory(name=name, create=True, size=SNAP_BYTES)
        self.buf = self.shm.buf
        self.buf[:HEADER_SIZE] = HEADER.pack(0, 0, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0)
        self._last, self._stop = None, threading.Event()
        self._thread = threading.Thread(target=self._loop, name="engine-snapshot", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(0.01):
            try:
                snap = api.acq.display()
            except Exception:  # noqa: BLE001 - not running, or stopping under us
                snap = None
            if snap is None or snap.seq == self._last:
                continue
            self._write(snap)
            self._last = snap.seq

    def _write(self, snap):
        img = snap.image
        h, w = img.shape[:2]
        if h > MAX_H or w > MAX_W:
            return
        res, rec = snap.result, snap.record
        xyz = None if res is None or res.xyz is None else np.asarray(res.xyz, dtype=np.float64)
        n = 0 if xyz is None else min(len(xyz), MAX_BEADS)
        if n:
            self.buf[XYZ_OFF:XYZ_OFF + n * 24] = xyz[:n].tobytes()
            self.buf[GOOD_OFF:GOOD_OFF + n] = np.asarray(res.good, dtype=np.uint8)[:n].tobytes()
        self.buf[IMG_OFF:IMG_OFF + h * w] = np.ascontiguousarray(img, dtype=np.uint8).tobytes()
        self.buf[:HEADER_SIZE] = HEADER.pack(snap.seq, h, w, n, rec.segment, rec.buffer_number, rec.t_camera_s,
                                             rec.rate_Hz, rec.t_pc_s, int(rec.recording))

    def close(self):
        self._stop.set()
        self._thread.join(2)
        self.shm.close()
        self.shm.unlink()


class Engine:
    def __init__(self, address=("127.0.0.1", 0), authkey=None, workers=8):
        self.authkey = authkey or os.urandom(16)
        self.listener = Listener(address, authkey=self.authkey)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="engine-call")
        self.motions, self._motion_lock, self._next_motion = {}, threading.Lock(), 1
        self.snapshot = SharedSnapshot(f"mtpy_snap_{os.getpid()}")
        self.exit = threading.Event()
        self.info = {"address": list(self.listener.address), "authkey": self.authkey.hex(), "pid": os.getpid(),
                     "snapshot": self.snapshot.shm.name, "started": time.time()}

    # --- the wire -------------------------------------------------------------------------------------------------
    def serve(self):
        """Accept clients until exit() is called; each client gets a receive thread, a send queue and an event tap."""
        os.makedirs(os.path.dirname(INFO_FILE), exist_ok=True)
        with open(INFO_FILE, "w", encoding="utf-8") as f:
            json.dump(self.info, f)
        try:
            while not self.exit.is_set():
                try:
                    conn = self.listener.accept()
                except OSError:
                    break
                threading.Thread(target=self._client, args=(conn,), name="engine-client", daemon=True).start()
        finally:
            self.close()

    def _client(self, conn):
        out, lock = queue.Queue(), threading.Lock()

        def send(msg):
            out.put(msg)

        def sender():
            while (msg := out.get()) is not None:
                try:
                    with lock:
                        conn.send(msg)
                except (OSError, EOFError, ValueError):
                    return
                except Exception as e:  # noqa: BLE001 - one unpicklable message (an event's extra) must not end the link
                    if msg[0] != "event":
                        with lock, contextlib.suppress(Exception):
                            conn.send(("err", msg[1], type(e).__name__, f"reply not picklable: {e}"))
        threading.Thread(target=sender, name="engine-send", daemon=True).start()
        unsubscribe = events.subscribe(lambda ev: send(("event", ev)))
        try:
            while not self.exit.is_set():
                try:
                    msg = conn.recv()
                except (EOFError, OSError):
                    break
                if msg[0] == "call":
                    self.pool.submit(self._run, send, *msg[1:])
        finally:
            unsubscribe()
            out.put(None)
            conn.close()

    def _run(self, send, seq, caller, name, args, kwargs):
        try:
            with events.as_caller(caller):
                result = self._dispatch(name, args, kwargs)
            result = _plain(self._wrap(result))
            pickle.dumps(result)                       # a result the wire cannot carry is an error, not a lost reply
            send(("ok", seq, result))
        except BaseException as e:  # noqa: BLE001 - every failure crosses the wire as the exception's class + text
            send(("err", seq, type(e).__name__, str(e)))

    def _dispatch(self, name, args, kwargs):
        parts = name.split(".")
        if parts[0] == "engine":
            if parts[1] == "ping":
                return {"pid": os.getpid(), "t": time.time()}
            if parts[1] == "exit":
                self.exit.set()
                self.listener.close()
                return True
            if parts[1] == "info":
                return self.info
            raise AttributeError(f"engine has no {parts[1]!r}")
        if parts[0] == "motion":
            m = self.motions.get(int(parts[1]))
            if m is None:
                raise api.NotReady(f"motion {parts[1]} is gone (waited or cancelled already)")
            attr = getattr(m, parts[2])
            result = attr(*args, **kwargs) if callable(attr) else attr
            if parts[2] in ("wait", "cancel"):
                with self._motion_lock:
                    self.motions.pop(int(parts[1]), None)
            return result
        if parts[0] == "events" and parts[1] == "events":
            return events.events(*args, **kwargs)
        if parts[0] not in api.__all__ or len(parts) != 2 or parts[1].startswith("_"):
            raise AttributeError(f"{name!r} is not a public api function")
        return getattr(getattr(api, parts[0]), parts[1])(*args, **kwargs)

    def _wrap(self, result):
        if isinstance(result, Motion):
            with self._motion_lock:
                mid = self._next_motion
                self._next_motion += 1
                self.motions[mid] = result
            return ("motion", mid, {k: getattr(result, k) for k in MOTION_ATTRS if hasattr(result, k)})
        return result

    def close(self):
        try:
            if api.devices.status():
                api.devices.disconnect()           # the cleanup rule: never leave the rig open
        finally:
            self.snapshot.close()
            self.pool.shutdown(wait=False)
            if os.path.exists(INFO_FILE):
                os.remove(INFO_FILE)


def _plain(x):
    """Read-only mappings (safety.profile()) and tuples of them become plain dicts / lists for the wire."""
    if isinstance(x, MappingProxyType | dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple) and not (isinstance(x, tuple) and x and x[0] == "motion"):
        return type(x)(_plain(v) for v in x)
    return x


def serve(address=("127.0.0.1", 0)):
    Engine(address).serve()
