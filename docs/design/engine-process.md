# The engine process and the GUI client (decision 0029)

Why: [results/2026-11-01-motion-noise-bead-count-gui.md](../results/2026-11-01-motion-noise-bead-count-gui.md)
(last section). What: the whole `mtpy.api` runs in one process ("the engine"); the GUI runs in another and calls it.

## 1. Processes
```
GUI process (PySide6, pyqtgraph)                 engine process (no Qt)
  app.py  --calls-->  mtpy.client.api  ==RPC==>  mtpy.engine.serve  -->  mtpy.api.* (unchanged)
          <--events-- (stream)                    events.subscribe            devices, pipeline, sinks,
          <--snapshot (shared memory)             DisplayTap -> SharedSnapshot   rig lock, estop, safety
```
- The engine is `python -m mtpy.engine [--listen ADDRESS]`: it imports `mtpy.api`, opens a
  `multiprocessing.connection.Listener` (default `("127.0.0.1", 0)`: a free port, written with the auth key to a file
  the GUI reads, `%LOCALAPPDATA%\mtpy\engine.json`), serves calls until told to exit. It takes no lock and opens
  no device by itself: `api.devices.connect` does that on the first call, as today.
- The GUI starts it (`subprocess.Popen`, same interpreter, same `src`), or attaches to a running one when the file
  names a live process (a script and the GUI can then share one engine; the rig lock has one holder: the engine).
- A script keeps importing `mtpy.api` in-process. That is the engine without the listener.

## 2. Calls
- Transport: one `Connection` per client (the GUI), messages `("call", seq, caller, "module.function", args, kwargs)`
  -> `("ok", seq, result)` | `("err", seq, exception_class_name, str, module_path)`; pickled by the connection
  (numpy arrays pass as they are; the objects the API returns are dicts, tuples, numpy arrays and the `Motion`
  handle).
- The engine runs calls on a small thread pool so a long `wait()` does not block a `status()`; calls that must be
  one at a time already lock themselves (`devices.connect`, `acq.start`).
- `Motion`: the engine keeps the live object in a table and returns `("motion", id)`; the client proxy exposes
  `wait(timeout)`, `cancel()`, `done`, `requested_mm`... as remote calls; the table drops an entry when `wait`
  returned or `cancel` ran, and on disconnect.
- Exceptions: the same classes (`mtpy.api.errors`) are re-raised on the client by name; an unknown class becomes
  `EngineError`. `SafetyRefused` and `NotReady` therefore reach the GUI's `_fail` unchanged.
- Caller: the client sends `events.caller()` of its own context ("gui" for the window) with every call; the engine
  runs the call inside `events.as_caller(name)`. The estop clear rule (`_CLEAR_CALLERS`) keeps working.
- Latency budget: a call is ~0.2 ms on localhost; the GUI's 2 Hz status tick makes about ten; the 30 Hz tick makes
  none (the snapshot is shared memory).

## 3. The snapshot (display tap)
`SharedSnapshot`: one `multiprocessing.shared_memory` block per acquisition, created by the engine at `acq.start`
and named in the start event: header (seq u64, h, w, n_beads u32, segment, buffer_number, t_camera_s f64, rate_Hz,
recording u8), then xyz float64 (n_beads x 3), good u8 (n_beads), then the frame uint8 (h x w). The engine's
DisplayTap writes it at its rate (seq last, after the data: a reader that sees seq unchanged reads nothing; a reader
that sees seq changed twice during its copy re-reads). The GUI's tick copies it when seq moved. Nothing blocks.

## 4. Events
The engine subscribes once per client and forwards every event as `("event", Event)`; the client's `events` module
appends it to its own list and notifies its subscribers (event log, plot marks), so `app.py` keeps
`events.subscribe(self._on_event)`. The event list in the client is the engine's from the moment it connected (a
client can ask `events.events()` for the history).

## 5. Lifetime and failure
| case | behaviour |
|---|---|
| GUI closes normally | the shutdown dialog runs the sequence through the client (`api.devices.disconnect` step by step, as now), then tells the engine to exit; the lock is released by the engine's cleanup |
| GUI dies | the engine keeps running with its devices and the lock; the heartbeat goes on; a restarted GUI attaches to it (`client.attach`, 2026-11-05) and shows the state as it is. The rig is never left without its holder. The engine has no console window (`CREATE_NO_WINDOW`) so closing the GUI's terminal does not kill it; its stderr and faulthandler go to `<out>/engine.log` |
| engine dies | the lock is STALE (a person recovers, RULES.md); the GUI shows "engine gone" on the next failed call / missed ping, disables every device button, keeps the last snapshot |
| engine unresponsive (a device call hangs) | other calls still run (thread pool); the watchdog ping is answered; the GUI shows the slow call in the status bar as today |
| emergency stop | a call like any other; the engine's `estop.engage` runs the stoppers in-process as now. A GUI that cannot reach the engine cannot stop the rig: the hardware limits (TMN/TMX, SL/SU) and the heartbeat are the protection, as they are today for a hung GUI |

## 6. What changes in the tree
- new `src/mtpy/engine/__init__.py` (serve loop, call dispatch, Motion table, SharedSnapshot writer, event forwarder);
  `src/mtpy/client/__init__.py` (`api` proxy with the same module / function names, `events` replay, snapshot
  reader, watchdog); `python -m mtpy.engine`.
- `gui/app.py`: `from mtpy.client import api, events` instead of `from mtpy import api`; `_tick` reads the shared
  snapshot; `_connect` starts or attaches the engine; `closeEvent` ends it after the shutdown sequence.
- `tests/`: a fixture `api_mode` in `("inprocess", "client")` for `test_devices.py`, `test_acq.py`, `test_gui.py`;
  an engine started in a subprocess on the simulator backend; the GUI tests run on the client only.
- Not changed: everything under `mtpy/api`, `mtpy/devices`, `mtpy/acq`, `mtpy/data`, the tools (in-process).

## 7. Known costs and limits
- Windows `spawn`: the engine imports numba and compiles / loads the cache on its own (3-5 s at start, as the GUI
  does today); the GUI no longer imports numba.
- The GPU executor lives in the engine; the GUI never touches CUDA.
- Two processes, one rig lock: the engine holds it; a script that imports `mtpy.api` while an engine runs is
  refused by the lock ("held by mtpy"), which is right.
- The drawing fixes (one scatter item for the boxes, a bounded history array, 10 Hz plot refresh) are still
  worth doing for the GUI's own responsiveness; they are independent of this design.

## 8. Order of work (the owner's roadmap decides when)
1. engine + client with the simulator - **done 2026-11-01** (owner "구현 시작"): `src/mtpy/engine/` (Listener, thread
   pool, Motion table, event stream, `SharedSnapshot`), `src/mtpy/client/` (`api` proxy, `events` replay, snapshot
   reader, `ping`, `launch` / `connect`), `python -m mtpy.engine [--config DIR]`; `tests/test_engine.py` runs connect,
   a Motion, two error classes, acquisition with recording, the snapshot through shared memory, the event stream and
   the exit with cleanup against a launched engine. Not yet: the API suite parametrised over both modes (the one
   engine test covers the representative calls).
2. the GUI on the client - **done 2026-11-01**: `gui.app.use_client(client)` rebinds `api` / `events` / `estop` /
   `safety` of the window and of the shutdown sequence to the client (`use_inprocess()` for the tests); the z scan
   moved into the API (`mtpy.api.zscan`, `progress()` polled by the window at 2 Hz; `gui/zscan.py` re-exports);
   module constants the window read became calls (`devices.default_mode()`, `devices.close_order()`);
   `python -m mtpy.gui` launches the engine for the real backends (`--engine` / `--no-engine`) and ends it after the
   window closes. `tests/test_gui_client.py`: connect, display from the snapshot, picks + z scan in the engine,
   bead selection, recording, Disconnect through the shutdown sequence, all on a launched engine. Found on the
   way: a result the wire cannot pickle (the read-only safety profile) silently ended the engine's sender thread -
   results are made plain and checked before sending, a sender failure answers with an error instead of dying.
3. the rig - **done 2026-11-01 17:04**: gui_rig_isolate.py in CLIENT mode (the engine launched by the script):
   4 beads 0.39 / 0.61 ms, 256 GPU 5.7 / 6.6 ms under the GUI = the script's; 256 numba needed the engine to leave
   two cores to the GUI (`NUMBA_NUM_THREADS` = cores - 2 by default): 7.4 / 8.5 ms under the GUI vs 7.4 / 7.9 idle.
   Acceptance met (results page). Open: the drawing fix for the GUI's own 276 ms tick at 256 beads.
