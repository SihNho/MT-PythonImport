# Status (2026-10-31)

Short and current. Details live in the linked documents; the history is in git and `dev/cycles.md`.

## Where the project is
- **Phases 1-3 (offline core): done.** Tracking matches the LabVIEW program on recorded frames; `.tra` / `.cal`
  read and write byte-identical. Branch `phase1-3-offline-core`.
- **Phase 5 (API, safety, simulators, data, protocols, walking skeleton): done** - WP1-WP6, each reviewed in Claude-GPT
  discussions until they converged ([dev/cycles.md](dev/cycles.md)). Branch `phase5-skeleton`, api 0.10.1, 229 tests
  passing on simulators. Not merged into `main` yet (owner to decide).
- **Phase 8 first build (GUI, simulators): done 2026-10-29** ([docs/design/gui.md](docs/design/gui.md)): `python -m mtpy.gui
  --sim-dev` runs the whole flow on the simulators (connect, beads, acquisition with live tracking, protocol,
  recording, z scan, export). Owner's order (2026-10-29): GUI first, then phases 6 and 7 on the rig (motor limits
  checked explicitly), then the tethered-bead calibration and the ABBA comparison.
- Three Z estimators on numpy / numba / CUDA (decision 0024); the fused GPU kernel ties the CPU at best on the
  RTX 2060 (float64 at 1/32 rate) - numba stays the default.
- **Phase 6 (real JAI camera through the API) done 2026-10-29** ([docs/results/2026-10-29-phase6-camera.md](docs/results/2026-10-29-phase6-camera.md)):
  150 Hz with the GUI, 0 of 44 984 frames lost.
- **Phase 7 motion gate approved and run on the rig 2026-10-30** (decision [0025](docs/decisions/0025-motion-gate-approved.md),
  [docs/results/2026-10-30-phase7-motors.md](docs/results/2026-10-30-phase7-motors.md)): real PI / ASI / Autonics
  drivers (`src/mtpy/devices/pi.py`, `asi.py`, `autonics.py`, backend `real-motors`); run 2: 31 steps, 0 failed -
  magnet 0..39 mm, stage +-0.5 mm, focus +-1 um, rotor +-0.5 turn moved and read back; every out-of-envelope
  request refused before a write; magnet homed and both controllers released at disconnect (independent readback).
  Profile **v6**: `focus_z_um` = the ASI controller's SL/SU Z (-75..+75 um); **v7**: `rotor_turns` +-5 turns verified
  on the rig (both edges, one pulse past refused), rotor moves through the API allowed. Independent audit: PASS per path on the
  working tree; open items listed in the results page.
- **2026-10-30 (owner: "그걸 리밋으로 두면 될듯"):** decision 0027 - the rotor's limit is the controller's own soft-limit
  registers read at open (factory values = the 24-bit counter range, read on the rig); nothing is written to the
  controller. `tools/rotor_limits_probe.py --adopt` ran 2026-10-31 on the owner's word: profile **v8**, `rotor_turns`
  = the controller's counter range (+-16777 turns, absolute).
- **2026-10-31 (owner: "모터 리밋은 40.9 까지 잡아두자"):** profile **v9** - `magnet_position_mm` max 40.9 mm (0.04 mm short of
  the 40.94 mm travel end = PI Max Trans Pos = the touch position); TMX 40.9 written and read back at the PI open on the
  rig the same day. Tests that document decisions 0017 / 0018 at [0, 39] mm run on v8 from the history.
- **2026-10-30 (owner: "Shutdown + lock"):** decision 0026 - the program holds the shared rig lock itself
  (`api.rig`, taken by `devices.connect` for real backends, released only after a clean `disconnect`) and shuts
  down through a visible step dialog (`gui/shutdown.py`, design/shutdown.md); `MT Tracker (rig).cmd` runs the GUI
  without the V6 wrapper. Same day on the rig: owner's motor sequence (results/2026-10-30-motor-sequence.md), iXon
  first contact, shutter freed by cycling, 47.5 fps max at VS 3.3 us (results/2026-10-30-emccd-*.md),
  camera parameter catalogue (design/camera-parameters.md).
- **2026-10-30/31 (iXon cooler):** CoolerOFF does not stop this camera's cooler; the close warms it up through the
  set point (SetTemperature(top) + CoolerON, judged by the temperature alone, fails fast when it does not move) and
  the open reads the state a previous owner left and adopts a cold sensor as the set point (owner 2026-10-31:
  check the configuration status at device start; results/2026-10-30-ixon-cooler.md). "Close anyway" from the
  Disconnect button now ends the program (2026-10-31); a failed device close stays listed and the next close
  repeats the cleanup on the still-open device (since 2026-10-31 evening: no re-open, so no PI reference move and no
  iXon cool-down on a Retry; bounded by the 60-s warm-up stall check).
- **2026-10-31 evening (owner: dry channel with reference beads, EMCCD powered):** the same reference bead tracked 18
  times with every tracker (3 Z methods x numba / CUDA) plus a piezo-step run, all through the API on the rig
  ([results/2026-10-31-refbead-track.md](docs/results/2026-10-31-refbead-track.md)): 0 frames lost in 19 runs, the six
  trackers agree (5 / 8 / 12 nm per frame in x / y / z on this dry sample), tracked z follows the piezo with slope
  1.04-1.06 (an unsettled 8-s z scan is the likely cause: proposal = settle time per slice), focus drift 60-70 nm/min.
  iXon open / close with the camera powered but warm: fine (the cold path is still to be exercised). The same evening:
  a merged **fault-scenario list** from three review sessions ([design/fault-scenarios.md](docs/design/fault-scenarios.md));
  G1 / G7 (double Connect / Start built two device sets / pipelines, confirmed on the sim), D5 (a raising lock check
  ended the heartbeat silently) and D7 (a silent PI read as "still moving") fixed with tests; D1 (a cleanup Retry
  re-opened and re-referenced the PI) and G15 (Connect cleared the e-stop) fixed on the owner's word ("둘 다 고쳐"). The device panel became a control panel (rows + numeric fields per device) the same night.
- **2026-11-01 00:00 (owner installed the eBUS SDK 6.5.3):** the installer bound the JAI camera to Pleora's USB3 Vision
  driver; **IMAQdx no longer enumerates the camera** (program connect: camera disconnected, motors fine). NI's U3V driver
  is still in the store. **Owner: "eBUS로 간다" -> decision 0028:** `src/mtpy/devices/ebus.py` drives the JAI through
  the eBUS .NET API (pythonnet + a 10-line C# pointer helper built on first use); on the rig 90 Hz 901 / 150 Hz 1500
  frames through `api.acq`, 0 gaps, 0 drops, hardware timestamps (1 GHz). Then (owner, same night: LabVIEW still runs the
  experiments) the camera goes back to NI's driver, **IMAQdx is the default again** and the Setup panel's "Camera SDK"
  box picks IMAQdx or eBUS (`camera_sdk`); the SDK must match the driver bound (manuals/camera-jai-ebus.md).
  **02:40 the owner bound the camera back to NI's driver; IMAQdx verified on the rig** (90 Hz 900 / 150 Hz 1499 frames,
  0 gaps, 0 drops, disconnect clean, lock released). LabVIEW experiments can use the camera again.
- **2026-11-01 03:30 (owner: items 2 and 4 "실행할것" / "진행해야"):** the iXon **cold path** on the rig: cooled to -61 C
  through the program, close warmed it above -20 C and shut down in 86 s, reopened warm (nothing adopted)
  (manuals/andor-ixon.md). Fault list: P5/G5 (camera settings locked during a z scan; the GUI asks before a guarded
  change while recording), P4/G6 (touch position fixed while a protocol runs), P1 (first sink I/O failure = event +
  recording off), D13 (dead camera thread visible), D6 (e-stop reason shown), D4 (atexit closes the run file; the
  lock refusal names the recovery) fixed with tests. Open from the owner: item 1 (40.9 mm travel, at the lab),
  item 3 decided ("0.2초로 넣어": 0.2 s settle per slice in `zscan.run`, a Calibrate field; the slope re-check with a
  new LUT **verified 13:57: slope 0.992-0.994**, results/2026-11-01-lut-settle-and-kill-restart.md), item 5 (eBUS extras when the MT experiment is fixed, selectable in
  the GUI), then a UI/UX discussion.
- **2026-11-01 13:50 (the PC rebooted without a clean shutdown at 07:53, cause unknown, nothing of ours running):**
  all eight devices reconnect cleanly; a program killed while recording leaves a readable run file (526 / 545 frames)
  and a STALE lock that the restart refuses by the rules - the owner takes it over by hand after checking the rig
  ([results/2026-11-01-lut-settle-and-kill-restart.md](docs/results/2026-11-01-lut-settle-and-kill-restart.md)).
- **2026-11-01 14:20 (owner: max light, all three Z methods):** new LUT, piezo steps per method: slopes `current`
  0.986-0.990 / `phase_spline` 0.983-0.985 / `spline` 0.970-0.977 - **not a fair comparison**: each method got its
  own piezo run and the piezo's run-to-run variation exceeds the method differences (owner's objection). The
  10-28 offline bench (same frames) stands: the continuous-LUT methods have the smaller slice bias. A fair rig
  test = the same recorded frames through all three. One unexplained 0-frame acquisition restart (rerun fine) is
  open in the results page.
- **Owner 2026-11-01 (beads):** of the four reference beads 1 (doublet) and 4 (fragment) are invalid, 2 and 3 valid;
  calibration is done at a focus where the ring radius is small (linear region). The owner sets that focus by hand
  before the next scan; the fair three-method comparison (same frames) starts from there.
- **2026-11-01 15:05 (owner's focus, owner's beads, fair comparison):** five 20 s runs 9004 frames, 0 lost / dropped;
  noise 1.3 / 1.1 / 2.2 nm x / y / z (small-ring focus). The same frames through the three Z methods (pipeline frame
  tap, offline): slopes agree to 0.3 %, noise to 0.3 nm (spline / phase_spline 0.2-0.3 nm quieter); the 84 nm
  residual is the focus piezo, whose 100 nm steps land anywhere between +11 and +267 nm (results page).
- **2026-11-01 15:15-15:33 (owner: noise under focus / stage / magnet motion, numba and GPU; frame time against the
  bead count; the same through the GUI):** [results/2026-11-01-motion-noise-bead-count-gui.md](docs/results/2026-11-01-motion-noise-bead-count-gui.md).
  Holds: 1 / 1 / 2 nm whatever moves; the magnet's travel does not shake the beads; a 5 um stage jump loses the
  beads (the VI's restart-from-calibration rule); 256 beads at 90 Hz: numba 6.3 / 11.2 ms, GPU 5.6 / 7.3 ms, 0
  drops. Through the GUI the noise is the same but the tracking p99 is 3-4x (29 ms at 256 beads numba, 39 ms GPU):
  ~100 beads is the comfortable GUI limit at 90 Hz. GUI bug: the bead-chip row does not wrap (14 726 px window at
  256 beads). read_run fixed for JSON list cells.
- **2026-11-01 16:00 (isolation, owner):** with the GUI idle the pipeline equals the script (256 beads 6.3 / 11.3 ms);
  the GUI tick is 317 ms at 256 beads (boxes recreated and the history rebuilt every tick) and shares the interpreter
  with the worker; the GPU executor suffers most. Fix order: cheap drawing, then the pipeline in its own process
  (decision needed). No language change needed for this (results page, last section).
- **2026-11-01 16:10 (owner: "프로세스 분리 설계"): decision 0029** - the engine (API, devices, pipeline, safety) in its own
  process, the GUI a client ([design/engine-process.md](docs/design/engine-process.md)); the roadmap places the
  work (engine + client on the simulator, the GUI on the client, the rig bench again as acceptance).
- **2026-11-01 16:40 (owner "구현 시작"): decision 0029 step 1 done** - `mtpy.engine` (the API hosted behind a local
  listener, Motion handles, event stream, shared-memory display snapshot, cleanup on exit) and `mtpy.client` (`api`
  proxy with the same names, `events` replay, snapshot reader, watchdog ping, launch / connect); `tests/test_engine.py`
  on the simulator. Next steps of 0029: the GUI on the client, then the rig bench as acceptance.
- **2026-11-01 17:30 (owner "2단계 진행"): 0029 step 2 done** - the window runs as a client (`gui.app.use_client`), the
  z scan is an API function run in the engine, `python -m mtpy.gui` launches the engine for the real backends;
  `tests/test_gui_client.py` drives the whole flow on a launched engine. 301 tests. Step 3 (the rig bench through
  the client, acceptance of 0029) is next.
- **2026-11-01 17:10 (owner "리그 벤치 진행"): 0029 step 3 done, acceptance met** - through the engine client the GUI
  no longer costs the tracker: 4 beads 0.39 / 0.61 ms (was 3.2 p99), 256 GPU 5.7 / 6.6 ms (was 34); 256 numba
  7.4 / 8.5 ms once the engine leaves two cores to the GUI (default now). The GUI's own 276 ms tick at 256 beads
  (drawing) is the remaining item.
- **2026-11-01 17:20 (owner: no drawing rework; the plot Hz as a user control):** "Plot refresh" (1-30 Hz, default 10)
  in the plot bar paces the redraw only; the data keep arriving at the display rate.
- **2026-11-01 17:30 (owner, side chat on how benches are shown):** timings as **median / std / slowest 1 % (p99) / max**;
  `acq.status()` carries the four for tracking time and latency, the rig tools print them (design/README.md).
- **2026-11-01 17:47 (owner: 5 / 10 / 20 beads on the rig, the three Z methods as a bench dimension):** 36 runs
  (3 counts x 3 methods x 2 executors, pipeline alone and under the client GUI): numba 0.4-0.9 ms median, p99 < 1.7
  ms; GPU 2.2-2.4 ms flat; phase_spline ~30 % dearer than current / spline on numba; the GUI adds nothing to the
  median; 0 drops. Rare single-frame 15-95 ms outliers noted (results page).
- **2026-11-01 18:10 (owner: the PC dies while idle about weekly; PSU and supply replaced, not them):** System log:
  18 unexpected shutdowns in 4 months, bugcheck 0, no sleep (high-performance plan, 0 sleep events), one WHEA
  corrected CPU parity error (00:15 today). `tools/pc_heartbeat.py` writes a line every 10 s (daily file, 7 days
  kept) so the next death shows whether the PC stopped at once or hung first; the owner registers it at logon
  (schtasks, user level). Hardware suspects: CPU / board power delivery, memory.
  Ingested as [rig/pc-stability.md](docs/rig/pc-stability.md) (+ .ko.md for the 2026-11-02 meeting). The owner
  experiments tonight. 19:54: the owner registered and started the logon task "mtpy pc heartbeat" (log lines
  arriving); after the next death run `tools/pc_heartbeat.py --report`.
- **2026-11-01 20:06-20:59 (owner: the accuracy test, per method, rate and bead count, piezo and magnet moving, raw and
  reference-corrected; then the camera's maximum rate and a half-size ROI):** 72 script runs at 90 / 150 / 248 Hz
  (full frame) and 555 Hz (640 x 512, the driver's cap at that ROI, now read by `JaiCamera.limits`). Reference-
  corrected step error 1-33 nm median at every rate and method; the raw 5-190 nm is drift / creep of the focus
  drive, not tracking. 0 drops at 90 / 150; 2 runs drop at 248 (phase_spline numba); 16 of 18 drop 0.06-1.9 % at
  555 Hz with 0.3-1.1 ms tracking (overhead outside the kernel, to profile). A LUT must be made at the rate it
  is used at (a 90-Hz LUT at 150 Hz: z 0.9 um low, bead 1 ambiguous). Bead 1 is ambiguous ~1.4 um below the LUT
  centre. [results/2026-11-01-accuracy-fps-roi.md](docs/results/2026-11-01-accuracy-fps-roi.md).
  21:07: the reduced matrix (owner's list, [design/bench-matrix.md](docs/design/bench-matrix.md)) runs:
  `tools/rig_bench_matrix.py`, 15 blocks (50 / 100 beads, the focus speed / step block, the GUI client at the
  four rates), ~2.5 h; `api.focus.set_speed` added for it (ASI `S Z`, capped at the opening speed, restored at
  close). The rig lock went stale once (a bench killed from outside) and was released on the owner's words.
- **2026-11-01 21:07-23:20, the reduced matrix** ([results/2026-11-01-bench-matrix.md](docs/results/2026-11-01-bench-matrix.md)):
  script 50 / 100 beads at 90-555 Hz (48 runs), focus step 20 / 50 / 100 nm x speed 4.96 / 0.50 mm/s (21), GUI client
  90 Hz (30) and 150 Hz (30). 555 Hz carries ~20 beads, 248 Hz ~100 on numba; accuracy independent of the bead
  count (corrected 1-12 nm); focus speed changes nothing (overshoot 14-63 vs 11-54 nm); the GUI client at 90 Hz
  equals the script (0 drops to 100 beads). The sample drifted ~40 px/h in the stage-step blocks (the ASI stage
  returns 0.1-0.2 um off) and left focus at 23:19, so GUI 248 / 555 Hz and the 1 um/s blocks did not run (open
  cells in design/bench-matrix.md). 2026-11-02 12:35: rig state `experiment` on the owner's words ("곧 실험 시작").
- **2026-11-02 13:30 (owner: "꺼진 것 같음"):** the PC died 2026-11-01 23:58, the first death under the heartbeat:
  10-s lines to the last one, idle (CPU 0.3 %), no WHEA - an instant stop, the power-delivery / board family
  ([rig/pc-stability.md](docs/rig/pc-stability.md)).
- **2026-11-04 (owner: the PC died again; replace the board):** two more instant deaths on 11-03 (07:34 idle; **20:14
  under the GUI 248-Hz bench, CPU 73 %**) - four in three days, same pattern, the board / CPU power family. Inventory
  and the replacement spec (LGA1200 B560 / H570 / Z590 micro-ATX, x16 + a free x1/x4 for the SUNIX serial card, 4
  DIMM) in [rig/pc-stability.md](docs/rig/pc-stability.md). **The 20:14 death cut the bench make-up block (GUI
  248 Hz, 3 of 16 runs done; GUI 555 Hz make-up not started): the rig lock is stale (pid 2808) and the focus / stage /
  magnet may stand where the run left them (up to 1 um / 5 um / 30 mm from their start). Nothing touched since; the
  owner's word is needed for the lock.**
- **2026-11-04 13:53 (owner: "clean up the stale lock, finish before the experiment"):** the stale lock (pid 2808)
  taken over and released on the owner's words; `tools/rig_restore.py` found the stage 0.2 um from the last run's
  start and the magnet at 0 mm (nothing moved), camera at its .icd defaults; the beads were not found within
  90 px: the field is several um out of the ring focus and looks different (a large blurred object at the bottom),
  so the focus was left for the owner, who refocuses for the experiment anyway. Rig state stays `assembled`
  until the owner says the experiment starts. Open: the bench make-up (GUI 248 Hz 13 runs, 555 Hz 4 runs) and
  the results page for the 11-03 blocks (1 um/s focus speed, GUI 248 / 555 Hz).
- **2026-11-04 evening (owner ran a real force-step experiment with the program, then: "no bench today, fix the
  problems first"):** z scan refuses an edge-near pick and a folder / existing .cal path before any move (70d974a);
  Explore shows every motor's position and the force live, magnet / rotor speed, Cal+ / Cal- presets, move-by
  entries back to 0, the GUI log also in `gui_events.log` (657b686); **`ramp` is one magnet move at distance / t**
  instead of 0.5-s force increments (the owner's trace showed stairs, and a 10-s ramp ran 52 s: 1 pN increments
  each a move plus a wait). The second-Start symptom is still unexplained (the simulators run twice; the next
  refusal is in gui_events.log). Requirements kept in design/gui.md: Experiment table editor, calibration panel,
  camera / EMCCD settings panels, bead-pick clicks.
- **2026-11-04 night (owner: "you did not touch the camera settings"):** the camera's whole attribute tree in the
  program: `api.camera.catalogue / get_attribute / set_attribute` (IMAQdx enumeration; 156 attributes on the rig,
  150 reads in 0.14 s, TriggerMode round trip ok), `api.emccd.catalogue()`, the generic panel `gui/attrs.py` (tree,
  search, level, favourites, read-back) in Setup -> Camera settings for both cameras; refusals for reset / stored
  defaults / factory / non-Mono8; frame-producing categories pause the acquisition and need confirm while
  recording. [manuals/camera-jai-attributes.md](docs/manuals/camera-jai-attributes.md).
- **2026-11-04 late (owner: "how does the program work again after a stale lock without asking the agent"; "start an
  error list"):** `api.rig.recover_stale(reason)` takes a dead holder's lock over on the user's own words (riglock
  take-over + recovery record in G:/Codes/rig/recovery/ + release; a live holder is never taken, not during an
  experiment); the GUI offers it in a dialog when Connect meets a STALE lock, `tools/rig_recover.py` does it from a
  prompt. [troubleshooting.md](docs/troubleshooting.md) started with 19 entries.
- **2026-11-04 23:22: the PC died again** (idle, instant; fifth). Before that, 22:27:50 the owner's GUI session took the
  lock (pid 8228, backend real), opened the devices, started acquisition, and 44 s later a Connect was refused as
  STALE (8228 gone): that process ended without releasing - no event between 22:28:02 and 22:28:46, so most likely
  the window was closed by the X with "Close anyway" or the process crashed; to ask the owner. The lock is stale
  now; the owner clears it with the new Take-over dialog (GUI restart) or `tools/rig_recover.py`.
- **2026-11-05 00:xx (owner: "carry on"):** the Experiment table (rows Force / Wait / Motor mm/s / Rotor degrees /
  Rotor SPD, columns = steps; + / - column, Table -> script, Start from table) compiles to the protocol script;
  `ramp` takes `speed=` mm/s as the alternative to `t=` (checked against the profile, the engine moves at it).
  The owner's five-column example compiles as shown in design/gui.md. Open: the calibration panel (bandpass /
  forget radius, PSF, dr-dz), the 22:28 stale lock's origin (how the window was closed), the second-Start symptom.
- **2026-11-05 (owner: "the program ends suddenly for reasons nobody knows - a system error or a slip"):** the 22:28
  case is resolved from the Windows event log: 22:28:37 Application Hang, python.exe "stopped interacting with Windows
  and was closed" (pid 0x31a4, the window), 35 s after the acquisition start; no crash of the engine recorded, so the
  engine (8228) was killed from outside with the frozen window (console closed / process tree ended). Three changes:
  the 2 Hz read-backs run on a worker (a slow device call can no longer freeze the window); the engine has no console
  window and logs to `<out>/engine.log` with faulthandler (closing the terminal does not kill it); a GUI that starts
  while an engine runs attaches to it (`client.attach`) instead of launching a second one, so a dead window is closed
  cleanly by Disconnect. The Take-over dialog shows what Windows recorded about python.exe since the lock was taken
  (troubleshooting #1, #20).
- **2026-11-05 ~02:00 (owner ran the program on the rig; "the motor ramps but not as the table, the force differs, the
  rotor does not turn, Start from table does nothing, trace export does not work"):** the log explains all of it. What
  ran was the text example (`hold f=1`, `ramp 1->5 t=5`), not the table: "Start from table" was refused first because
  the text protocol was still running, then by the check (two errors) - the rotor speed limit was never set in profile
  v9 (`max None`), so every rotation is refused; the owner sets it with the new `tools/rig_set_limit.py` (#21). The
  "355 errors" and the Cal+ `TypeError` were one client bug (#22, fixed). The .tra export worked: `run_..._015517-000`,
  10650 rows x 18 beads (#23). The .cal path is browsed now and takes the next free `cal00N`. Not done: the
  calibration panel (profile / bandpass / forget radius / PSF).
- **2026-11-05 ~03:00 (owner, five points):** (1) Start replaces a running protocol; a top-bar badge shows the
  protocol state. (2) rotor speed limit set to 3 turns/s (owner: "SPD 150", profile v10, `tools/rig_set_limit.py`);
  the Setup panel shows the profile file, its version and every limit. (3) Names follow the LabVIEW program: the run
  file (the raw data) is `tra001.h5`, its export `tra001-000`, the calibration `cal001`; a typed .cal name that exists
  is overwritten after a prompt, the next scan gets the next number. (4) STOP = emergency stop, understood. (5) The
  owner wants, once the code settles, the means to see where things are set and what state the code is in (not now).
- **2026-11-05 ~04:00 (owner):** the graph shows every pick's radial profile per slice during the z scan; "New
  calibration" (Beads) drops the selected beads and restarts the acquisition without them so the image takes picks
  again (#27); the scan ends with the focus at the LUT's middle (tracking starts there); rotor +1 / -1 turn buttons
  in Explore; the z scan's IndexError at a runaway pick fixed (#25); #26 (the program ends mid-scan).
- **2026-11-05 ~04:30 (owner: "why is the calibration not fixed - band-pass, forget radius, PSF"):** the
  calibration viewer (`gui/calview.py`, in Calibrate): per bead the PSF stack image, the band-passed LUT image and
  the self-fit (z found vs z scanned, residual nm) with LOW / HIGH / forget spins re-processing live and Save to
  .cal (bead_i32; select the beads again). To confirm with the owner what LabVIEW's "delta r vs delta z" picture is.
- **2026-11-05 ~05:00 (owner: "the data files must be the LabVIEW files, .cal and .tra"):** checked against the
  2023-2026 files: the layouts were byte-identical already (tests); two values were not: the .cal date string
  (now LabVIEW's Korean long date + 12-hour time, `lvfiles.cal_date`) and the z step (now the single-precision
  value LabVIEW stores, 0.10000000149). The .tra export (tra001-000) was identical: header, weekday, columns
  (frame, magnet mm, rotor deg, x y z per bead).
- **Next:** protocols on hardware (force ramps, rotation, 3-state clamp, autofocus), the stop / watchdog paths
  exercised on the rig, then the tethered-bead calibration.
- **Queued (owner 2026-10-30):** lock the camera settings while a z scan runs (the GUI must not change exposure,
  rate or ROI between slices; `api.acq.average` would otherwise mix frames of two settings).

## Decided since phase 5 (owner, 2026-10-25 / 26)
| # | Decision |
|---|---|
| [0016](docs/decisions/0016-owner-answers-after-wp5.md) | magnet speed max 15 mm/s; `zero` = 0 mm; `end protocol` only ends the protocol (MT recording and acquisition go on; on/off is for fluorescence); `.tra` frame numbers continue within one file; MATLAB 2026 |
| [0017](docs/decisions/0017-force-limit-follows-the-magnet-position-limit.md) | no separate force maximum: the force limit follows the magnet position limit; force <-> position one-to-one |
| [0018](docs/decisions/0018-force-input-coerced-to-the-reachable-range.md) | force from the LabVIEW equation, live; out-of-range force or position coerced and written back (no alarm, logged); motor value coerced at the last step; no second bound from the touch position |
| [0019](docs/decisions/0019-magnet-stall-returns-to-zero.md) | stall (controller error -1024): return to 0 mm once, error window + record, else lock - an extinguisher |
| [0020](docs/decisions/0020-rig-core-parameters-register.md) | stall threshold stays 1.0 mm; rig core parameters in one register ([docs/rig/core-parameters.md](docs/rig/core-parameters.md)) |

## Rig (state: assembled; 2026-10-31 owner: a dry channel with reference and magnetic beads is mounted, in focus)
- Rig safety profile **v9**: magnet 0..40.9 mm and 15 mm/s (rig-verified; the owner's 40.9 of 2026-10-31), focus
  -75..+75 um (v6), rotor = the controller's counter range (v8). ASI +-2 mm from the session start.
- PI controller read: stall threshold 1.0 mm; normal lag at 15 mm/s about 0.05 mm (1/20). Stage model unknown.
- Force equation read from `Magnet2Force v3_for M270.vi` and checked by running it (16 points, 2e-16).

## Recently ingested
- smCamera file formats from a real dataset and the MT-FRET workflow (colleague's `mtFRET_2.pptx`):
  [docs/manuals/smcamera-files.md](docs/manuals/smcamera-files.md),
  [docs/manuals/smcamera-workflow-mtfret.md](docs/manuals/smcamera-workflow-mtfret.md); requirement candidates R1-R10
  in [docs/spec/ui-requirements.md](docs/spec/ui-requirements.md). Key fact: `.traces` holds donor / acceptor
  intensities only; FRET is computed in MATLAB.

## Open (owner)
- Merge `phase5-skeleton` (and `phase1-3-offline-core`) into `main`?
- MT-FRET: default beta / direct-excitation / gamma; excitation pattern and movie length; manual pairing UI; bead
  view select or highlight; write smCamera-compatible files?
- MATLAB 2026 run of `matlab/read_mtpy_h5.m` (no MATLAB on this PC).
- Rig: 50x pixel size, focal-shift source (0.88), stage model, rotor and focus windows.

## Known tool items (V6 repo)
rig_session RESULT line format; gate self-test 14e pins the rig state; guard list lacks the fast-poll sender (not
used until added); V6 `STATUS.md` too long.
