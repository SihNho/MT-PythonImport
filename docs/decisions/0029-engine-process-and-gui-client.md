# 0029 — The engine (API, devices, acquisition, safety) runs in its own process; the GUI is a client

**Decided:** 2026-11-01 (owner, in chat): after the isolation measurement
([results/2026-11-01-motion-noise-bead-count-gui.md](../results/2026-11-01-motion-noise-bead-count-gui.md), last
section) the owner chose the process separation over the drawing fix alone ("프로세스 분리 설계"), having said that a
change of language was on the table if Python could not solve it.

## Background (measured on the rig, 2026-11-01 16:00)
- The pipeline alone (GUI timers off) tracks 256 beads at 90 Hz: 6.3 / 11.3 ms per frame (numba), 5.7 / 7.4 ms (GPU).
- With the GUI's 33 ms tick running, the same pipeline reads 11.1 / 15.1 ms (numba) and 7.1 / 34 ms (GPU), the
  latency p99 86 ms: the GUI thread's drawing (a 317 ms tick at 256 beads) shares the one interpreter (GIL) with the
  tracking worker. Even at 4 beads the plot alone triples the p99 (0.9 -> 3.2 ms).
- Decision 0002 (acquisition, tracking and saving never touch the GUI thread) was kept with threads; threads share
  the interpreter, so the GUI's Python work still steals from the worker. LabVIEW's parallel loops did not have this.

## Decision
1. **One engine process hosts everything that is not drawing:** `mtpy.api` (devices, acquisition, protocol, magnet,
   beads, events, estop, rig lock, safety), the device services, the pipeline, the sinks. It takes the rig lock
   (0026), runs the heartbeat, the motion gate (0025), the cleanup. Nothing of this moves or changes.
2. **The GUI process is a client.** It talks to the engine over a local connection and draws. It never imports a
   device, never holds the lock, never runs a pipeline. The GUI code keeps calling `api.<module>.<function>(...)`:
   `mtpy.client` provides an object with the same functions, each one a remote call; `app.py` changes only its
   import and the display read.
3. **The display tap crosses the boundary through shared memory**, not messages: the engine writes the latest
   snapshot (frame uint8 h x w, the result xyz / good, the record fields, a sequence number) into a
   `multiprocessing.shared_memory` block; the GUI reads it at its own rate. The same latest-value rule as today
   (0002: the GUI can never slow acquisition).
4. **Events stream to the client** (the engine's `events.subscribe` -> the connection); the client's `events`
   module replays them to its subscribers (the event log, the plot's marks). The client sends its caller name with
   every call, so `events.caller()` in the engine says "gui" as now (0011 naming).
5. **Scripts and tests are unchanged:** they import `mtpy.api` in-process as today. The engine is the same code
   hosted behind a listener; the client is a thin proxy. One test fixture runs the API suite through the client as
   well, so the two paths cannot drift.
6. **Failure rules:** the GUI dying leaves the engine running with the rig lock (an operator restarts the GUI and
   reconnects to the running engine; nothing on the rig changes); the engine dying leaves a STALE lock, as a crash
   does today (0026, RULES.md) - the GUI shows "engine gone" and offers nothing else. The emergency stop is a call
   like any other, plus a client-side watchdog: the GUI pings; after 2 s without an answer it shows the engine as
   unresponsive (it does not, and cannot, stop the rig from outside - the engine's own heartbeat and the hardware
   limits do that).
7. **Acceptance:** the GUI bench of 2026-11-01 (tools/gui_rig_bench.py, tools/gui_rig_isolate.py) repeated through
   the client: the tracking p50 / p99 under the GUI within 20 % of the script's at 4 and 256 beads, numba and GPU;
   the display rate and the event log as today; shutdown through the dialog releases the lock.

## Not decided here (the design page settles them, the owner reviews)
The transport (`multiprocessing.connection` over localhost with an auth key is the default), the snapshot layout,
how the engine is started (by the GUI, or standing alone for a script and a GUI together), the drawing fixes (one
scatter item for the boxes, a bounded history: still worth doing, since they shorten the GUI's own tick, but they
no longer decide the tracker's tail).

## Follows
- Design: [design/engine-process.md](../design/engine-process.md).
- 0002 amended in spirit: "never touch the GUI thread" becomes "never share the GUI's interpreter".
- Phase plan: a new phase (engine + client, then the GUI on the client, then the bench); the owner's roadmap decides
  when.
