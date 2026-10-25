# Public function layer (API) — specification, DRAFT v0

Status: first draft, 2026-10-24, for review by the owner and the phase-5 work. Required by decision
[0015](../decisions/0015-extension-architecture.md). The GUI, protocol / recipe scripts, plug-ins, Python experiment
scripts and the AI gateway (0014) all call **these functions and nothing below them**. Names and signatures here are
proposals; phase 5 may refine them, and every change after the first release follows the versioning rule below.

## 1. Conventions
- **Origin:** owner requirement [U37](../spec/ui-requirements.md) (one public function layer) and decision
  [0015](../decisions/0015-extension-architecture.md).
- **Package:** `mtpy` (existing). Public API under `mtpy.api` (one import for scripts: `from mtpy import api`).
  Existing internal modules (`track`, `fast`, `calib`, `lvfiles`) stay as they are; the API wraps them.
- **Units in the name or the argument**: `force_pN`, `position_mm`, `exposure_ms`, `turns`, `z_um`, `rate_Hz`,
  `timeout_s`. No unitless physical number crosses the API.
- **One job per function**; verbs: `get_*` (read, no side effect), `set_*` / `move_*` / `start_*` / `stop_*` (act).
- **Every acting call** goes through the safety layer (section 3), is logged as an event with its caller (GUI user,
  script name and version, plug-in, AI gateway) and returns what the device **read back**, not what was asked.
- **Errors:** typed exceptions — `SafetyRefused` (outside the rig safety profile), `DeviceError` (no reply, bad reply;
  carries device, command, plain-language hint), `NotReady` (e.g. no valid calibration), `Timeout`. Never a silent
  clamp: a value outside the allowed range is refused with the allowed range in the message (the GUI may clamp before
  calling, U30).
- **Blocking vs non-blocking:** moves return a `Motion` handle (`.wait(timeout_s)`, `.done`, `.cancel()`); waits take
  `timeout_s`.
- **Simulator**: every device function works against the simulator (phase 5), selected by the rig preset, so any script
  can be dry-run without hardware.
- **Documentation**: every public function has a docstring with units, safety behaviour, an example and a test.
- **Versioning:** `api.VERSION` (semantic). A rename or behaviour change keeps the old name working with a warning for
  at least one release; scripts declare the API version they were written for.

## 2. Groups and main functions (proposal)

### 2.1 Rig and presets
| Function | Purpose |
|---|---|
| `api.rig.state()` | **development builds only**: shows the shared rig lock (disassembled / assembled / experiment) while the project is under development; absent from the released application (0001, 0009) |
| `api.presets.list(kind)` / `load(kind, name)` / `active(kind)` | rig, sample, camera, protocol, channel-layout presets (U13, U15, U22) |
| `api.presets.save(kind, name, content)` | save a preset (not for the safety profile) |
| `api.safety.profile()` | the active rig safety profile (read-only for every caller except the rig-admin settings screen) |

### 2.2 Devices
| Function | Purpose / safety |
|---|---|
| `api.devices.status()` | per-device state, last reply, last error (U8) |
| `api.devices.info(name)` | identity, settings read back, limits, calibration in use (U8 details) |
| `api.devices.reconnect(name)` | reconnect one device |
| `api.camera.apply_preset(name)` | apply, read back, verify; `DeviceError` on mismatch (U15) |
| `api.camera.set_exposure(exposure_ms)` / `set_gain(gain_dB)` | immediate settings (U17) |
| `api.camera.set_rate(rate_Hz)` / `set_roi(x, y, w, h)` | "needs a short pause": stop, apply, read back, restart (U17) |
| `api.magnet.move_to(position_mm, speed_mm_s=None)` | inside the profile's travel; returns `Motion` |
| `api.magnet.set_force(force_pN, table=None)` | via the recorded position-to-force table (0010) |
| `api.magnet.position()` | position_mm read back |
| `api.rotor.rotate(turns, speed_turns_s=None)` / `api.rotor.position()` | signed turns, inside the profile |
| `api.stage.move_to(x_mm, y_mm)` / `api.focus.move_to(z_um)` | ASI; inside the window; focus moves invalidate nothing but are logged (U35) |
| `api.light.set(laser, on: bool)` | manual on / off (U24); refused while a sequence runs |
| `api.light.load_sequence(seq)` / `start_sequence()` / `stop_sequence()` | illumination sequence run by the Arduino (0005, U24) |
| `api.sync.set_ratio(n)` | JAI frames per EMCCD frame (0005) |

### 2.3 Acquisition and data
| Function | Purpose |
|---|---|
| `api.acq.start(record=True, name=None)` / `stop()` | start / stop acquisition (and recording) |
| `api.acq.wait_frames(n, timeout_s)` | wait for n camera frames |
| `api.acq.mark(text)` | free-text event in the data |
| `api.data.save_run(folder, name)` / `open_run(path)` | save (U21) / open for review |
| `api.data.metadata()` | the run's metadata (U16) |
| `api.data.export(kind, path)` | `.tra` / `.cal` (LabVIEW-compatible), HDF5, `.trace` (smCamera format, U28), MATLAB |

### 2.4 Beads, calibration, tracking
| Function | Purpose |
|---|---|
| `api.beads.find(detector, **params)` | candidates (ring / blob / peak, U23) |
| `api.beads.select(ids)` / `set_role(id, role)` | pick, mark reference |
| `api.calib.run(slices, step_nm, n_avg)` | z scan; refused if the JAI camera position changed and not re-read (U31) |
| `api.calib.valid()` | is the LUT valid for the current geometry |
| `api.tracking.stages()` / `set_stages(...)` | swappable XY / radial / Z stages (0003); recorded in the data |
| `api.tracking.latest(bead)` | latest x, y (px) and z (µm), each with its per-frame uncertainty (U34) |
| `api.tracking.zero(bead_or_all, mode)` | zero at zero force / set zero here / bridge a step (U12, U14) |
| `api.tracking.exclude(bead, t0_s, t1_s, reason)` | excluded segment (U14) |

### 2.5 Fluorescence
| Function | Purpose |
|---|---|
| `api.maps.load(path)` / `check_in_situ()` / `fit(...)` | channel and JAI <-> EMCCD maps (U22, mapping.md) |
| `api.fl.spots(bead=None)` | candidate spots with scores (U25) |
| `api.fl.signals(spot)` | raw per-frame signals per channel and excitation (U36) |
| `api.fl.observable(name, spot)` | FRET E, stoichiometry, presence, ... (U36) |
| `api.fl.corrections()` / `set_corrections(alpha, delta, gamma)` | FRET correction factors, recorded (U28) |

### 2.6 Protocols, events, analysis
| Function | Purpose |
|---|---|
| `api.protocol.load(script_or_path)` / `check()` / `run()` / `pause()` / `stop()` | protocol engine (0012, U19) |
| `api.protocol.edit(draft)` / `apply_edits()` | mid-run edits (U18) |
| `api.events.rule(expr)` / `wait_for(rule, timeout_s)` / `on(rule, callback)` | event rules (U36) |
| `api.screen.run(recipe)` / `results()` | screening (U10) |
| `api.analysis.ewlc_fit(bead, t0_s, t1_s, fixed=...)` | van Noort / Odijk eWLC (U12) |
| `api.analysis.allan(bead, axis)` / `steps(trace)` / `noise(bead)` | basic on-site analysis (0011) |

## 3. Safety behaviour (inside every acting function)
1. Check the request against the **active rig safety profile** (0015 item 5); outside -> `SafetyRefused` with the
   allowed range. (Exception, decision 0018: a magnet force or magnet position outside the position limit is
   coerced to the nearest reachable value with a `coerced` event, not refused; see the 0018 section below.)
2. Act through the device service (its own thread; never on the frame path).
3. Read back and compare; mismatch -> `DeviceError`.
4. Log an event (caller, request, read-back, time); the event goes into the run's metadata.
5. The emergency stop pre-empts everything; an active stop makes every acting call raise `NotReady`.
The safety profile itself is changed only from the rig-admin settings screen with a re-commissioning check; no API
function writes it (the write path lives in `mtpy.admin`, outside the public API; see below).

**Implemented in WP1 (2026-10-24, `api.VERSION = "0.1.0"`):**
- `mtpy.api.errors`: `MtpyError` (base) and the four errors above; `DeviceError(device, command, hint)`.
- `mtpy.api.events`: `log(kind, request, readback, **extra)`, `events(since)`, `subscribe(fn)` (for the HDF5 writer);
  the caller is a context variable set with `as_caller(name)`, one of `gui`, `rig-admin`, `script:<name>@<version>`,
  `plugin:<name>`, `ai:<read|propose|run_approved|autonomous>`; code that sets none is logged as `unknown`.
- `mtpy.api.estop`: `engage(reason)`, `clear()`, `active()`.
- `mtpy.api.safety` (read only): active profile `config/safety_profile.json`, every version kept as
  `config/safety_profiles/<version>.json`; `load_active()`, `profile()` (read-only view), `versions()`,
  `check(quantity, value, origin)` (`origin` = session-start position for relative windows such as the ASI stage;
  returns True for a verified limit, False for an unverified one that the profile allows). Quantity names:
  `magnet_position_mm`, `magnet_force_pN`, `magnet_speed_mm_s`, `rotor_turns`, `rotor_speed_turns_s`, `focus_z_um`,
  `stage_x_mm`, `stage_y_mm`, `laser_power_mW.<laser>`.
- **Unverified limits:** a limit with `"verified": false` is treated like an unset limit (every request refused)
  unless the profile has `"allow_unverified": true`; then every acting call that relies on it logs an
  `unverified-limit` warning event. The profile lists those limits in `"unverified"` (checked against the flags on
  load). The shipped v1 has `allow_unverified: false`, so `rotor_turns` (-5 .. +5 turns from session start, not
  verified for the application) and the placeholders refuse every request.
- **Write path, not in the public API:** `mtpy.admin.safety_admin` (never imported by `mtpy.api`).
  `open_admin_session(reason)` -> `AdminSession` (refused for `script:`, `plugin:`, `ai:` and `unknown` callers);
  `propose_change(session, limits, by, reason, allow_unverified=None)` -> an internal pending proposal;
  `activate(session, pending, RecommissioningReport)` re-validates the candidate, recomputes its diff against the
  active profile, requires the report to show every new or changed limit as checked, and refuses a candidate whose
  `base_version` is not the active version. Each step is a `safety_profile` event (who, when, why).
  **This is a guard against mistakes, not protection:** any code in the process can set its own caller name. Real
  protection - `open_admin_session` bound to a GUI login with the rig-admin role, and file permissions on
  `config/` - is phase 8 work.
- `mtpy.api._act.acting(quantity, value, do, readback, tol, origin)`: steps 1, 3, 4 and 5 above for every device
  function (step 2, the device-service thread, comes with the device layer). `tol` must be a finite number >= 0
  (else `SafetyRefused`, nothing sent); an exception from the send or the read-back, or a read-back that is not a
  finite number, becomes `DeviceError(device, command, hint)` with a `device_error` event; only a read-back that
  passed is logged as `act`.
- **Review l2s-wp1-r2 fixes:** `events.log` never raises because of a subscriber - a failing subscriber does not stop
  delivery to the others or reach the acting call (its own `SafetyRefused` / `DeviceError` is preserved), and each
  failure is recorded once as a `subscriber_error` event (not recursively). `estop.clear()` is refused
  (`SafetyRefused` + `refused` event) for `script:`, `plugin:`, `ai:` and `unknown` callers; only `gui` (the
  operator's release button) and `rig-admin` may clear - a guard against mistakes, not protection (phase 8).
  `activate()` refuses a candidate that switches `allow_unverified` from false to true (temporary, until the owner
  decides whether that needs its own re-commissioning report); true -> false is allowed. An int too large for a
  float (e.g. `10**400`) counts as not finite: `SafetyRefused` with a `refused` event, never `OverflowError`.

**Requirements for WP2 (device layer):**
- The session-start `origin` for relative windows (`relative_to: "session_start"`, e.g. the ASI stage, the rotor) is
  read and kept by the device layer at session start and passed to `acting()` by the device function; a caller
  (script, plug-in, AI) never supplies it.
- The read-back tolerance `tol` is decided by each device implementation (its own resolution and settling), bounded
  internally by that implementation; it is not a caller argument and not a rig safety profile entry.
- The caller context travels with each request: the device service runs every request in the caller's context
  (`contextvars.copy_context()` taken per request and per thread, then `ctx.run(...)`), so events logged on the
  device-service thread carry the real caller, never `unknown` or another request's caller.
- WP2 is simulators only; it is not approval to connect real devices.

**Implemented in WP2 (2026-10-24, `api.VERSION = "0.2.0"`, simulators only):**
- `mtpy.devices`: `Device` (open / close / identity / settings / limits / calibration / probe / session_origin /
  stop, plus `tol`, `quantities`, `settings_kinds`, a plain-language `hint`), `DeviceService` (one thread and request
  queue per device; every request runs in `contextvars.copy_context()` of the caller; a failure or no reply becomes
  `DeviceError` with the hint and a `device_fault` event; status connected / disconnected / error / slow (> 0.5 s),
  last reply time and ms, last error; `info()`, `reconnect()`, `self_check()` open -> reply -> read, stopping at the
  first failed step), `Motion` (own thread in the caller's context; `wait(timeout_s)` -> read-back or `Timeout`,
  `done`, `cancel()`; cancelled or e-stopped -> `NotReady` and a `cancelled` event). `make(rig_preset)`: only
  `{"backend": "sim", "fixture": <folder>|None}`; any other backend raises `NotImplementedError`.
- The session-start origin of relative windows (stage x/y, rotor, focus) is read at the first open of a session and
  kept across reconnects; it is dropped at `devices.disconnect()`.
- Simulators (`mtpy.devices.sim`): `SimCamera` (fixture replay or synthetic rings; absolute buffer numbers that
  restart at 0 on each acquisition start as in IMAQdx; `t_camera_s` from the sim's clock - the real JAI has no
  hardware timestamp, so the real driver will carry PC receive time; open resets ROI / exposure / rate; rate and ROI
  locked while acquiring; frame period and exposure in 1 us steps; `drop_every`, `stall(s)`, `fault`),
  `SimMagnet` (TMN/TMX 0..39 reject with ERR 7, hard travel 0..40.94), `SimRotor` (500 pulses/turn), `SimStage`
  (SL/SU stop the motor without an error, so only the read-back shows it), `SimFocus`, `SimArduino` (ratio N, records
  `(m, first JAI buffer, lights on)` per EMCCD frame from the camera's exposure line), `SimLight` (532 / 637 on/off).
  Fault injection `fault = "no_reply" | "nan"`.
- Functions added: `devices.connect(rig_preset)` / `disconnect()` / `status()` / `info(name)` / `reconnect(name)` /
  `self_check()`; `camera.apply_preset(preset)` / `set_exposure` / `set_gain` / `set_rate(rate_Hz, confirm=False)` /
  `set_roi(x, y, w, h, confirm=False)`; `magnet.move_to` / `position()` / `use_force_table(table)` /
  `set_force(force_pN, table=None)`; `rotor.rotate(turns, speed_turns_s=None)` / `position()`;
  `stage.move_to(x_mm, y_mm)` / `position()`; `focus.move_to(z_um)` / `position()`; `light.set(laser, on)`;
  `sync.set_ratio(n)`.
- **Changes against section 2.2:** `devices.connect` / `disconnect` are new (until `presets.load("rig")` exists);
  `camera.apply_preset` takes the preset content `{"name", "roi", "rate_Hz", "exposure_ms", "gain_dB"}`, not a name,
  until `api.presets` exists, and remembers it to re-apply after a reconnect; `set_rate` / `set_roi` take
  `confirm=True` to change while recording (U17 "guarded"; a `guarded_change` event); `rotor.rotate(turns)` is
  RELATIVE (target = position read now + turns; the target is checked against the session-start window);
  `magnet.use_force_table(table)` is new (`set_force` raises `NotReady` without a table; no physics is invented);
  `magnet.move_to(..., speed_mm_s=None)` always checks the speed against `magnet_speed_mm_s` (see the review
  l2s-wp2-r1 fixes below). Positions, stage x/y and the rest read back through the service.
- `_act.acting` gained `check=` (a device-range check for settings that are not rig-safety-profile quantities, or
  that span two quantities like stage x/y) and `match=` (non-scalar read-back), and passes `NotReady` from the send /
  read-back through unchanged with a `cancelled` event; `_act.precheck` (e-stop + profile check alone) lets a Motion
  refuse on the caller's thread before its own thread starts. `estop.add_stopper(fn)`: `engage()` sets the flag,
  then calls each device's `stop()` directly (not queued); a failing stopper is an `estop_error` event (order
  refined by the review fixes below).
- Quantity names in events for the non-profile settings: `camera_exposure_ms`, `camera_gain_dB`, `camera_rate_Hz`,
  `camera_roi`, `camera_preset`, `stage_xy_mm`, `light_<laser>`, `sync_ratio`.

**Review l2s-wp2-r1 fixes (simulators only; evidence, not proof - a real driver's direct stop path onto its port is
checked separately in phases 6/7):**
- **E-stop order:** `estop.engage()` raises the flag and a generation number (`estop.generation()`) first, then calls
  every registered stopper, each wrapped so one failure does not skip the others, and only after every stop attempt
  logs the `estop` event and one `estop_error` per failed stopper (a slow event subscriber never delays a stop).
  `clear()` does not reset the generation.
- **Send window:** an acting call records the generation when the request is made (a Motion: when `move_*` is
  called) and its Motion's cancel flag. The device service checks both right before the device send (void ->
  nothing is sent) and right after it (void -> the device thread calls `stop()` again). Either way the call ends with
  `NotReady` and a `cancelled` event, and no `act` event. So a request queued before an emergency stop never runs
  after `clear()`, and an engage -> clear (or a cancel) while the send is in progress still leaves the device stopped.
- **Direct cancel:** `Motion.cancel()` sets the cancel flag and calls `device.stop()` directly, not through the
  service queue (which may be busy).
- **Magnet speed always checked:** when `speed_mm_s` is omitted the controller's current speed is read back
  (`VEL?`) and checked against `magnet_speed_mm_s`; the checked speed is sent with the move. A profile without a speed
  maximum refuses the move (`SafetyRefused`). **With the shipped profile v1 (`magnet_speed_mm_s` max unset) every
  magnet move - `move_to` and `set_force` - is refused until a rig-admin sets that maximum (owner decision pending).**
- **Divider reset rule (`SimArduino`):** the divider counts its own JAI pulses; the count starts at 0 on `open()`
  (the port's auto-reset) and on every `set_ratio(n)`, and nothing else resets it (not a camera acquisition restart).
  Pulse p triggers EMCCD frame m = p // N when p % N == 0, so frame m covers the divider's pulses [mN, (m+1)N); each
  record keeps the JAI buffer number seen with the triggering pulse, for matching only.

**Re-review l2s-wp2-r2 fixes (simulators only; same evidence level as above):**
- **Generation before the pre-reads:** `magnet.move_to` and `rotor.rotate` record the e-stop generation on their
  first line, before reading the magnet speed (`VEL?`) or the rotor position, and pass it to `_move(gen=...)`; an
  engage -> clear during either pre-read voids the move (`NotReady`, nothing sent). Moves without a device pre-read
  (focus, stage) record it in `_move`.
- **Void check after any end of the send:** the device service checks for voiding (generation changed or the cancel
  flag set) after the send whether it returned or raised (a send may apply the move and then raise). A voided send
  is stopped again on the device thread and ends in `NotReady` + `cancelled`, never `act`; when it had raised, the
  original exception is the `NotReady`'s cause and is recorded as a `device_fault` event (field `voided`; the U8
  status is not marked as error); `estop_error` only if the re-stop itself fails. A send that raised and is not void
  keeps the usual `DeviceError` handling.
- **Deferred (agreed in l2s-wp2-r2):** (1) the rotor's omitted speed is not yet read back and checked like the
  magnet's (`rotor_speed_turns_s`) - deferred to the package that opens rotor ranges (the shipped profile v1 refuses
  every rotor move until then); (2) `Motion.wait_arrival` checks the stop flag and cancel flag but not the generation
  - deferred to later.

**Frame contract for WP3 (acquisition pipeline), agreed in review l2s-wp2-r1:**
- Acquisition runs in **segments**: every acquisition start (including the restart after a "needs a short pause"
  change, U17) begins a new segment with its own segment number, increasing through the run.
- The **original buffer number** IMAQdx gives each frame is kept unchanged with its segment number; it is never
  renumbered or joined into one running number.
- The **frame rate (and the settings that set it) is recorded per segment**.
- A loss at the end of a segment that cannot be confirmed (how many frames the camera produced after the last one
  received is unknown) is recorded as **unknown, never as zero**. Exact segment lengths are promised only after the
  real driver shows what IMAQdx reports at a stop (open question: whether the last buffer number is readable after
  Stop Acquisition, and whether Start alone restarts buffer numbers at 0).
- The **elapsed time between segments** is recorded separately (PC clock) and is never replaced by a buffer-number
  offset.

**Implemented in WP3 (2026-10-24, `api.VERSION = "0.3.0"`, simulators only):**
- `mtpy.acq` (internal): `Pipeline` = camera thread -> `FrameRing` -> tracking worker -> sink thread, plus
  `DisplayTap`. The camera thread takes frames from the camera's frame path (`next_frame`, never a device-service
  queue or a serial call), stamps a `FrameRecord` (segment, original buffer number, `t_camera_s` with its
  `t_source` - "sim camera clock" now, the real JAI driver will name PC receive time -, PC receive time, segment rate
  and ROI, `gap_before`, recording flag) and never waits: a full ring (default 64 frames) drops its oldest frame,
  counted as a **pipeline drop** per segment and passed on as a `FrameResult` with `dropped=True`. **Camera gaps**
  are counted from the buffer numbers (also a first buffer > 0 in a segment). The worker runs `BeadTracker`
  (track.Tracker's frame-to-frame rule on the numba `FastKernel`: start from the previous output rounded half to
  even, -1 on the frame after a bad flag, all beads back to their calibration positions after any -1).
  `FrameResult` = record + x, y (px), z (um), good per bead + tracking ms. `Segment` keeps rate / ROI / exposure read
  back, first / last buffer, counters, `pc_gap_s` (PC time since the previous segment ended) and `end_loss = None`
  (unknown, never 0). A buffer number that goes backwards without an API restart opens a new segment ("unannounced
  restart", settings not read back).
- `ResultSink` (`write_frame(result)`, `write_event(event)`, `close()`) and `MemorySink`. All sink calls come from
  one sink thread fed by a lossless queue; it receives recorded frames (drops included) and every `api.events` event
  logged while recording (subscribed through `events.subscribe`). The WP4 writer implements `ResultSink`.
- Control between loops by latest value only: the recording flag (read by the camera thread per frame, changed
  between two frames under the segment lock), `latest()`, and the display snapshot (at most ~30 Hz, offered by the
  worker; reading it never slows acquisition). Queues carry data only.
- API: `acq.start(record=False, name=None, sink=None, ring_capacity=64)`, `stop()`, `set_recording(on, name=None)`,
  `wait_frames(n, timeout_s)` (frames produced = received + camera gaps), `mark(text)`, `status()` (fps measured
  from the camera timestamps with its source, camera gaps, pipeline drops, unknown-loss segments, tracking ms and
  receive -> result latency p50 / p99, ring fill, errors, segments), `sink()`, `display()`, `running()`;
  `tracking.latest(bead)` (x_px, y_px, z_um, good, segment, buffer number, camera time; `uncertainty: None` with
  `"not yet computed"`); `beads.select(ids, cal_path=None)` (1-based ids of a `.cal`; None = the first `cal*` in the
  sim camera's fixture folder; refused while acquiring), `beads.selected()`.
- `api.camera.set_rate` / `set_roi` during acquisition now close the segment after the stop (frames still in the
  camera buffer are taken first) and open the next one with the settings read back before the restart. While
  recording, every device service's `recording` flag is set, so the "guarded while recording" settings need
  `confirm=True`.
- **Changes against section 2.3:** `start` defaults to `record=False` (exploration first, U17) and takes `sink=` (a
  seam until WP4 builds the HDF5 sink from `name`) and `ring_capacity=`; `set_recording`, `sink`, `display`,
  `running` are new; `beads.select` takes `cal_path=` until `api.calib` exists. `SimCamera.timestamp_source` is new.
- **Emergency stop:** 0007 stops motion only, so acquisition and recording continue through an e-stop and `start`
  is allowed while it is engaged (the camera's `stop()` is a no-op; a real camera driver's `stop()` must stay one).
- **Speed through the pipeline** (`tools/bench_pipeline.py`, 150 Hz sim replay, 5 s, beads repeated): tracking
  p50 / p99 0.39 / 1.07 ms (5 beads), 0.87 / 1.51 ms (20), 2.88 / 4.11 ms (80); no drops, no gaps. (Superseded by
  the l2s-wp3-r1 rerun below with wall-clock rates.)
- **Not done here:** a camera reconnect during acquisition ends the frames without a segment end (stop and start
  acquisition again); per-frame uncertainty (U34). (The ROI change that moved beads out of the image is now refused
  while beads are tracked: see the l2s-wp3-r1 fixes below.)

**Review l2s-wp3-r1 fixes (simulators only; evidence level: unit tests on the sim camera, not the real driver):**
- **Stop that does not finish:** `Pipeline.stop(timeout_s)` checks `is_alive()` after each join (camera thread, then
  worker, then sink). On a timeout it returns False with `stop_state = "incomplete: <thread> still running after
  <t> s"`; the sink's end marker is queued only after the worker ended (so a late result is never cut off) and the
  sink is not closed. `api.acq.stop(timeout_s=10.0)` then keeps `_pipe` (status shows `running: True`,
  `stop: "incomplete: ..."`), logs an `acquisition` event with action `stop incomplete`, refuses `start` and
  `set_recording(True)`, and a second `stop()` resumes only the draining (the camera stop, segment end and recording
  off ran once). A completed stop (`stop: "complete"`) means everything was drained into the sink and the sink closed.
  Tested with a slow tracking worker (0.3 s per frame) and a slow sink (50 ms per frame).
- **ROI changes that do not suit the tracked beads are refused before the camera stops**, in `set_roi` and
  `apply_preset` (inside `precheck`: `SafetyRefused` + one `refused` event, nothing paused or sent). While
  acquisition tracks beads, refused: a moved ROI origin (bead positions are ROI pixels and are NOT translated) and a
  size that leaves a bead's tracking window (half-size `rint(0.6 * cross)`) outside the image. A smaller ROI with the
  same origin that still holds every window is allowed (new segment as before). Not covered: an ROI moved while
  acquisition is stopped (the `.cal` does not record its ROI; `start` checks the size only).
- **Recording-on snapshot:** every `recording` event with action `on` carries `segment_info` (`Segment.as_dict()` of
  the current segment, taken under the segment lock with the flag change) and `settings` (roi, rate_Hz, exposure_ms,
  gain_dB read back from the camera at that moment). The key `segment` stays the segment number, as in every event
  with a frame position (the review text said `segment=`; renamed so the number is not overwritten).
  `start(record=True)` reuses the settings read it does before the camera starts (one read, nothing runs in between).
  A setting changed while exploring (exposure, gain) is therefore in the recording although its event was not.
- **Settings read failure (owner's choice in chat for the open item; to be re-checked in the re-review):** the read
  comes first; if it fails, recording is refused - `NotReady` ("camera settings could not be read back ...") with the
  device error as its cause, one `refused` event (request `{"recording": "on", "name": ...}`), the recording flag and
  the services' `recording` flags stay off. Acquisition and the display keep running (U15: the frame rate and the
  settings as read back are never missing from recorded data, 0006).
- **Events stay off the worker path:** checked, unchanged. Events reach the sink queue from the thread that logs them
  (`Pipeline._on_event`); the tracking worker only pops the ring, tracks, and queues frame results.
- **Bench rerun** (`tools/bench_pipeline.py 5 300`, 150 Hz, 5 s after the first frame, 2026-10-24). Sources:
  `memory` = 300 fixture frames preloaded (no file read in the camera thread), `disk` = SimCamera reading files it
  read before (OS-cached), `disk-cold` = files read for the first time. TIFF read per frame: 7.10 ms median for
  first-time files, 1.45 ms for cached ones (frame period 6.67 ms).

  | source | beads | 1st frame / 1st result ms | received / tracked per s (wall clock) | sim producer /s | fps (sim clock) | track p50 / p99 ms | latency p50 / p99 ms | drops |
  |---|---|---|---|---|---|---|---|---|
  | memory | 5 | 0.40 / 1.13 | 149.1 / 149.3 | 149.2 | 149.99 | 0.34 / 0.46 | 0.69 / 1.21 | 0 |
  | memory | 20 | 0.37 / 1.35 | 149.4 / 149.6 | 150.2 | 149.99 | 0.66 / 1.23 | 1.33 / 3.02 | 0 |
  | memory | 80 | 0.50 / 4.32 | 149.7 / 149.9 | 149.9 | 149.99 | 2.11 / 4.04 | 4.21 / 11.36 | 0 |
  | disk | 5 / 20 / 80 | 2.6 / 3.5, 2.1 / 3.1, 2.7 / 6.6 | 150.0, 149.4, 149.6 | 150.3, 149.5, 149.9 | 149.99 | 0.43 / 1.99, 1.11 / 1.38, 2.63 / 4.03 | 0.54 / 24.90, 1.15 / 1.51, 3.73 / 7.05 | 0 |
  | disk-cold | 5 / 20 / 80 | 9.9 / 10.7, 7.6 / 8.9, 9.3 / 13.4 | 116.2, 113.8, 116.3 | 116.4, 114.1, 116.5 | **149.99** | 0.39 / 4.85, 0.91 / 1.96, 3.44 / 6.83 | 0.53 / 30.98, 1.04 / 2.12, 3.57 / 8.84 | 0 |

  The pipeline keeps up at 150 Hz with 5, 20 and 80 beads (received = tracked = what the producer made, no drops);
  the first frame arrives < 1 ms after the start with frames in memory. **The earlier 652 / 750 (5 beads, 5 s)** was
  the sim camera, not the pipeline: when its producer thread reads a TIFF for the first time (7.1 ms > 6.67 ms) it
  falls behind and makes only ~116 frames per second, while `fps_measured` still shows 149.99 because the sim clock
  stamps each frame with its scheduled time. In that run frames 0-299 were cached by the replay tests just before
  (2 s at 150 Hz = 300 frames) and frames 300-749 were first-time reads (3 s at ~116 Hz = ~350): 300 + 350 = ~650,
  matching 652. Consequence: `fps_measured` from the sim clock cannot show a slow source; the wall-clock rates in
  the bench can. (The real JAI's frame time will be PC receive time, decision 0005.)

**Carried (agreed in l2s-wp3-r1):**
- **WP4:** arrival order at the sink is not event order (frames come through the worker, events straight from the
  logging thread): keep each event's time and identity and never infer order from arrival; aligning by PC time
  (event `t`, frame `t_pc_s`) is for display and lookup only, not exposure-accurate (0005: the JAI has no hardware
  timestamp; exact motor / frame alignment needs the 0005 camera reference); a `recording off` event is not a
  file-close signal - only a completed stop means drained; splice recorded setting changes (`guarded_change`,
  `act`, segment events) into the stored settings; how storage errors during recording are stored and shown.
- **Real camera driver:** the display snapshot must copy the IMAQdx buffer (its lifetime ends when the driver reuses
  it); the IMAQdx buffer-number reset rule (Start alone, or Configure needed?); the camera's `stop()` stays a no-op
  on an emergency stop; read back the segment end loss (`end_loss`) if IMAQdx can report it.
- **WP6:** a camera reconnect as a segment end; the `mtpy.api` <-> `mtpy.devices` circular import; long runs.

**Carried (agreed in l2s-wp3-r2):**
- **WP4 (a) - done in WP4:** the writer refuses a recording-on event missing any of the four settings (roi, rate_Hz,
  exposure_ms, gain_dB): `RecordingRefused`, no file opened, no recording or segment started from it.
- **WP4 (b) - done in WP4:** recording-on precedes the acquisition-start event in arrival; the writer assumes no
  arrival order between recording-on, acquisition start, segment events and frames (both orders tested).
- **Driver / WP6 (d) - not implemented:** a `stop_acquisition` failure still clears `_pipe` (`_finish` runs
  `pipe.stop` in `finally`); whether the camera really stopped must be checked separately (read `acquiring()` after
  the failed stop and show it).
- **WP6 / U23 - not implemented:** store the ROI at bead selection and compare its origin at `acq.start` (today
  `start` checks the size only; a moved origin while stopped is not caught).

**Implemented in WP4 (2026-10-24, `api.VERSION = "0.4.0"`, simulators and files only):**
- `mtpy.data.HDF5Writer(path, beads=None, roles=None, metadata=None, flush_frames=150, flush_s=1.0)` implements
  `ResultSink`; `api.acq.start(..., folder=..., roles=...)` builds it for `<folder>/<name>.h5` when no `sink` is given
  (an existing file is refused, `NotReady`; it stores the camera identity and settings at start). The file is opened
  at the first **accepted** recording-on event, never before; frames and events that arrive earlier are held in
  memory (frames bounded by `max_pending`, default 20000) and written then.
- **Arrival order:** nothing is inferred from it. Segment rows are merged from the recording-on `segment_info`, the
  segment begin / end events and the frame records (start settings: first value received; counters: the segment-end
  event is final; the segment's own `start_pc_s` is preferred to the begin event's log time). Recording rows pair each
  on with the first off after it by event time. The same items in both orders give the same `/mt` and `/segments`
  (test).
- **Refusal (carry a):** `RecordingRefused` (a `NotReady`) from `write_event`; the pipeline shows it as
  `sink_error` / `sink_failures` in `api.acq.status()`; the refusal is kept in `writer.refused` and, once a file
  exists, written to `/events/writer_refused` (root attribute `recordings_refused`). Frames no accepted recording-on
  covers raise `RecordingRefused` at close (count in `writer.unwritten_frames`), never dropped silently.
- **Rate never missing (U15):** every `/segments` row has `rate_Hz` (read back: from the segment events or the
  recording-on snapshot, else from the frame records, which carry the same read-back; `settings_source` says which),
  `rate_Hz_measured` (recorded frames' `t_camera` and buffer numbers), `roi`, `exposure_ms` and `gain_dB` in force
  at the segment's first recorded frame, and `settings` (JSON: every known value with time and source, changes during
  the segment). Setting changes recorded while recording (`act` read-backs of camera settings, preset read-backs,
  segment begins) are spliced in by event time. `/metadata/run/frame_rate_hz` = preset / read back / measured of the
  first recorded segment, attribute `warning` when they disagree or the rate changes between segments.
- **Drops and gaps:** a pipeline drop is a `/mt` row with `dropped = 1` and NaN positions; a camera gap is
  `lost_before` on the next row; per segment `frames_dropped`, `camera_gaps` (recorded rows) and
  `pipeline_drops_segment`, `camera_gaps_segment`, `frames_received` (whole segment, from the end event; -1 before
  it); `end_loss = -1` (unknown). A frame whose tracking raised has `track_error = 1` and a
  `/events/writer_tracking_error` row.
- **Magnet / rotor:** `magnet_mm` / `rotor_deg` per frame are the last `act` read-back of `magnet_position_mm` /
  `rotor_turns` (x 360) logged before the frame's PC receive time, filled at flush (a reading that arrives after
  its rows were flushed is back-filled at the next flush: review fix 4 below), with its time in `magnet_t` /
  `rotor_t`. NaN before the first reading: there
  is no motor polling thread yet (WP6), so between moves the value is the last move's read-back.
- **Crash behaviour (tested points only, wording per review l2s-wp4-r1):** rows are buffered in memory and written
  at a flush (every `flush_frames` rows or `flush_s` seconds, checked at each write, and at close). Two crash points
  are tested, each a subprocess ended with `os._exit` after a flush of 100 rows: (1) with 40 more rows waiting in
  memory, (2) right after an event of a new kind created its group in the file. In both the file opens, holds exactly
  the 100 flushed rows and `closed_cleanly = 0`. For those points the loss is the rows since the last flush (at most
  `flush_frames`, default 150). **Not tested and not promised:** a crash during a flush, including the motor
  back-fill rewrite (WP6 carry below). Option (c) of hdf5-v1.md open item 1, without a repair tool; no SWMR (event
  tables are created when a kind first appears, which SWMR does not allow).
- **Readers / export:** `mtpy.data.read_run(path)` (nested dicts, JSON columns parsed), `legacy_matrix(path)`
  (`.tra` columns per segment), `export_tra(path, base=None, nominal=2_000_000)` (tracked rows only; frame =
  buffer - segment first buffer; one series per segment when there are several: `<base>-s<k>-000`; header by
  `lvfiles.tra_header` with the local start time and the `.cal` path), `export_cal(path, out)` (the `.cal` bytes stored
  in the file, checked by sha256; byte-identical to the fixture `cal002`, test). `api.data.open_run(path)`,
  `api.data.export("tra" | "cal", path, out)`. MATLAB: `matlab/read_mtpy_h5.m` (`[data, run]`: legacy matrix and
  every group); **not run in MATLAB** (none here) - the datasets it names are checked from Python.
- **Bead roles:** `roles` given -> `role_source = "user"`; else the `.cal` exp/ref flag (0 -> `reference`,
  1 -> `tethered`, `role_source` says the meaning is inferred); else `candidate` / `not set`. The `.cal` is read from
  `beads.source` or the acquisition-start event's `cal`.
- **Deviations from docs/format/hdf5-v1.md** (the draft is updated to match; schema_version stays "1.0" while the
  draft is not fixed): new groups `/segments` and `/recordings`; `/mt` gains `segment`, `dropped`, `track_error`,
  `track_ms`; `/mt/frame` is not stored (buffer numbers restart per segment: frame = `buffer_number` -
  `/segments/first_buffer`); `t_camera` is float64 seconds with attribute `source` (no camera ticks: the JAI has no
  timestamp, 0005); event tables keep the common columns plus `segment`, `request`, `readback` and `data` (JSON of
  the event's own fields) instead of one dataset per own column, and `buffer_number` is int64 with -1 when the event
  carries none (only events with a frame position carry one; arrival order is not used to guess); event kinds are
  the `api.events` kinds (`act`, `refused`, `recording`, `segment`, `acquisition`, `mark`, `guarded_change`, ...),
  plus the writer's `writer_refused` and `writer_tracking_error`. Not written yet (no source in WP3/WP4): `focus_pos`,
  `cal_slice`, `reseed`, `autofocus_move`, `protocol_*`, `clamp_state`, `emccd_frame`, `light_state`,
  `/fluorescence`, `/derived`, `/metadata/presets` content (only what `metadata=` passes), `git_commit`,
  `legacy_tra_files` (stays empty: export does not modify the data file). `/metadata/calibration` adds `cal_bytes`,
  `n_slices`, `date`, `path`.
- **Open for the owner:** HDF5 field names (`/segments`, `/recordings`, the event `data` column); whether event own
  columns must be separate datasets for MATLAB; `.tra` export of a multi-segment run (one series per segment, or one
  file with a running frame number); whether magnet / rotor need a polling thread (LabVIEW reads them every frame)
  before `.tra` column 1-2 match LabVIEW's meaning; how storage errors during recording are stored (now: only
  `api.acq.status()` `sink_error`, the file may not be writable).

**Review l2s-wp4-r1 fixes (simulators and files only; unit tests, not a real MATLAB or rig):**
1. **Four settings checked before the flag:** `api.acq.set_recording(True)` (and `start(record=True)`) refuses a
   settings read that lacks any of roi, rate_Hz, exposure_ms, gain_dB (or gives None) with one `refused` event and
   `NotReady`, before the recording flag or the services' `recording` flags change.
2. **Recording intervals by position:** the writer writes a frame only inside an accepted interval: after the on
   event's (segment, buffer) up to and including the off event's (the first off after that on and before the next
   on, by event time; without an off, up to the next on, or open-ended); an on without a buffer number starts before
   the segment's first frame. Frames not yet placed are held (bounded by `max_pending`) until an on / off event
   places them. At close, frames still outside are counted in the root attribute `frames_not_written`, written rows
   outside the final intervals (an off that arrived after its frames) in `frames_outside_recordings`, and either
   raises `RecordingRefused` after the file is closed cleanly. Segment counts cover written rows only.
3. **Late .cal:** a `.cal` path that arrives after the file was opened (acquisition-start event late) is stored at
   the next flush (`/metadata/calibration`, root `legacy_cal_file`), and `/beads` is rebuilt from it at every flush
   (roles from the exp/ref flags, pick positions; user roles kept).
4. **Late motor reading:** a magnet / rotor read-back that arrives after rows with later PC times were flushed
   rewrites those rows' `magnet_mm` / `magnet_t` / `rotor_deg` / `rotor_t` at the next flush (the file is scanned
   back from the end in 4096-row blocks to the first row at or after the reading).
5. **Crash right after a new group** is tested (see "Crash behaviour" above).
6. **libver:** the file is opened with `libver=("earliest", "v108")` (upper bound HDF5 1.8 object formats, so a newer
   format raises at write time instead of silently making a file older MATLAB HDF5 builds cannot read). h5py 3.16
   (HDF5 2.0.0 here) accepts it; the real MATLAB check is WP6.
7. **Crash wording** limited to the tested points (above and in `mtpy.data.hdf5`).
- Tests (tests/test_data.py): `test_api_recording_on_missing_setting_refused_before_flag` (1),
  `test_frames_outside_accepted_intervals_reported_at_close`, `test_frames_held_until_their_interval_arrives` (2),
  `test_late_cal_applied_and_beads_rebuilt_order_independent` (3, needs the G: fixture),
  `test_late_motor_reading_backfills_flushed_rows` (4, flush every 2 rows),
  `test_crash_keeps_everything_up_to_the_last_flush[new group]` (5), `test_file_written_with_hdf5_1_8_upper_bound`
  (6).
- **Not changed (owner question pending):** the `.tra` column-0 origin (segment's first received buffer).

**Re-review l2s-wp4-r2 fix:** `api.acq.start(record=True)` runs the four-settings check on its settings read
before it builds the sink, uses the ROI or starts the pipeline: a missing setting gives exactly one `refused` event
and `NotReady`, acquisition not running, no file (tests `test_api_start_record_missing_setting_refused_first[roi |
gain_dB]`; a late off with written rows beyond it: `test_late_off_reports_written_rows_outside`).

**Carried (agreed in l2s-wp4-r2):**
- **WP5:** a status test for the `max_pending` overflow (the pipeline's sink loop, pipeline.py:295-298, catches the
  `RecordingRefused` per frame and continues; show the count in `api.acq.status()`).
- **WP6:** motor back-fill across several flushed 4096-row blocks (tested only within one block).
- **Driver:** a late `.cal` is ignored when its path does not exist (only a `note` attribute); `start(record=False)`
  with `roi` missing from the settings read raises `KeyError` at the ROI fit check instead of `NotReady`.

**Carried (agreed in l2s-wp4-r1), WP6:**
- a crash during a flush, including the motor back-fill rewrite path (not tested, nothing promised);
- a real MATLAB run of `matlab/read_mtpy_h5.m` and of the owner's analysis scripts on an exported `.tra` (owner's
  MATLAB version needed; also confirms the `libver` bound);
- per-frame motor reading (a polling path outside the frame acquisition path; today the last move's read-back, NaN
  before the first move);
- `sink_error` (storage errors during recording) stored in the file, not only in `api.acq.status()`;
- the `.tra` column-0 origin: docs/format/tra-cal.md:78 says relative to the first **saved** buffer, `export.py`
  (`legacy_matrix`, frame = buffer - `/segments/first_buffer`, the segment's first **received** buffer) differs when
  recording starts after acquisition; owner to confirm before Python export and MATLAB reader change together.

**Implemented in WP5 (2026-10-24, `api.VERSION = "0.5.0"`, simulators and files only):**
- `mtpy.protocol` (internal): `grammar.parse(text, file)` -> `Script` for the three kinds of
  [grammar.md](../format/grammar.md) (protocol, sequence, recipe; draft v0, grammar 0.1); `check.check(script,
  devices)` validates against the public API and the rig safety profile; `engine.Engine` runs a protocol on its own
  thread. The WP5 decisions on open grammar points are in grammar.md section 12.
- `api.protocol`: `load(script_or_path, file=None)` (parse only; nothing runs, no event), `check(script,
  devices=None)` -> `{"ok", "errors", "warnings", "min_duration_s"}` (errors as `file:line:col: message`),
  `run(script, motion_timeout_s=120, ramp_step_s=0.5)` (checks again with the rig state; a failed check logs one
  `refused` event and raises `ScriptError`; refused while the emergency stop is engaged or another protocol runs),
  `pause()`, `resume()` (refused once the run ended, in particular after an emergency stop), `stop()`,
  `wait(timeout_s)`, `status()`, `running()`, `edit(draft)` (full check, kept as the draft) and `apply_edits()`
  (applied at the next step boundary).
- **The engine calls only `mtpy.api`** (a test checks that `mtpy.protocol` never imports `mtpy.devices` or reaches a
  device service), so each step passes the profile, the emergency stop and the read-back checks like a manual action.
  Run states: running, paused, completed, stopped, refused (the API refused a step), failed (device error, time-out,
  other API error), aborted (emergency stop). Events `protocol`, `protocol_step`, `protocol_edit` (grammar.md 12.17)
  go through `api.events.log`, so they reach the HDF5 `/events` while recording (test).
- **Checker:** every statement is mapped to API functions by name (`check.API_MAP`); a missing function fails the
  check (`light`, `if`, `wait until`, `on` today), and each key's unit must match the unit in the API parameter's
  name. Every value is checked with `api.safety.check`; every magnet statement also needs a usable
  `magnet_speed_mm_s` maximum, so **with the shipped profile v1 every magnet statement fails the check** (test).
  With the rig state: devices connected, force table loaded and covering every force (position inside the magnet
  travel), focus target from the current position, acquisition running for `record`.
- **New / changed functions:** `api.magnet.force_table()` (read-only copy of the loaded table, for the checker);
  `api.ScriptError` (`diagnostics`, `warnings`); against section 2.6, `run` takes the script, and `resume`, `wait`,
  `status`, `running` are new; `check` returns a report instead of raising.
- **WP5 carry (max_pending):** `api.acq.status()` gains `frames_not_written` (the sink's `unwritten_frames`, None
  for a sink without it); test `test_max_pending_overflow_visible_in_status`: with no accepted recording-on and
  `max_pending=5`, `frames_not_written` and `sink_failures` grow, `sink_error` names the overflow, acquisition goes
  on per frame, and the close reports it; no file is written.
- Tests: `tests/test_protocol.py` (parser positions, header / sequence / recipe errors, the grammar.md examples, load
  without execution, check refusals: missing API function, out-of-profile value, profile v1 magnet speed; full run
  event sequence, rotate / focus through the API, pause / resume, stop, emergency stop mid-step (aborted, magnet
  stopped in place, nothing moves after the release, no resume), refusal mid-run, mid-run edit applied / refused,
  end-to-end HDF5 events, the max_pending carry).
- **Not done (WP5):** `if` / `wait until` / `on` / `light` execution (needs `api.events.rule`, `api.light` sequences);
  screening rule evaluation (metric library); running `.mtseq` / `.mtrec` (parsed and checked only); the tracking zero
  in `zero`; the run-time / frame / light-time / data-size estimate of grammar.md section 8 (only `min_duration_s`);
  storing the protocol files with the run beyond the `protocol` start event (text + sha256 in `/events/protocol`);
  the per-frame `protocol_step` / `protocol_loop` / `protocol_version` columns of hdf5-v1 `/mt`.
- **Still open from earlier (unchanged):** the rotor's omitted-speed check (the engine always passes a speed);
  `Motion.wait_arrival` generation check (the engine itself ends the run when the generation changes).

**Review l2s-wp5-r1 fixes (simulators only; unit tests with barriers, not the real devices):**
1. **Run generation through to the send:** `api.estop.run_scope(gen)` (ContextVar) wraps the whole protocol run.
   `guarded_send` now records `(request generation, cancel, run generation)` instead of overwriting the context
   (`_act.py` `acting` -> `estop.guarded_send`), `estop.invalid(guard)` requires BOTH generations current, and the
   device service checks it right before and right after each send; `_act.precheck` also refuses inside a void run
   scope (`estop.run_scope_void()`). The engine also re-checks after the rotor pre-read. Tests:
   `test_estop_engaged_and_released_during_step_start_event_sends_nothing`,
   `test_estop_engaged_and_released_during_rotor_pre_read_sends_nothing` (zero sends, run aborted; with the run scope
   disabled the first one fails with one magnet send - checked once as a negative control, not kept as a test).
2. **One run at a time:** `api.protocol.run` does the running() check, the check and the engine start under one lock;
   the engine is registered only after it started. Test: `test_only_one_run_starts_and_the_running_one_is_never_overwritten`
   (re-reviews l2s-wp5-r2 / r3: signals, no sleep). A spy around `_run_lock` shows run A inside its check holding
   the lock. It sets B's `waiting` signal only after B's `acquire(blocking=False)` was **refused** (proof that the
   lock is held, not mere arrival); B's following wait is `acquire(timeout=5)` and a failure raises in `__enter__`
   (never proceeds without the lock, never releases a lock it does not hold). A is released and both threads are
   joined in `finally` on every path. Real lock: passed 3 times in a row (2026-10-25). **Negative control**
   (scratch, not committed; the same observer with only the mutual exclusion removed - an inner lock whose
   `acquire` always succeeds): fails with "no waiting signal: B's non-blocking acquire was not refused", which no
   run order can avoid. (The r2 control - both runs started, `_engine` overwritten by A - is superseded.)
3. **Focus reference:** the engine reads `focus_z0` in `start()` (before its thread), and `edit()` checks against
   it (`check(..., run_focus_z0=)`); a focus step without a run reference is refused. Tests:
   `test_mid_run_edit_focus_uses_the_run_start_reference`, `test_focus_step_without_run_reference_is_refused`.
4. **Edits are value-only:** `check.structure_diff(old, new)`; `edit()` refuses any structural change with
   `ScriptError` (line named) and a `protocol_edit` refused event; the engine re-checks at the boundary. Tests:
   `test_mid_run_structural_edits_are_refused_with_an_event`, `test_engine_refuses_a_structural_draft_at_the_boundary`,
   regression `test_mid_run_edit_applies_at_next_step_boundary` (loop n, force and text edits still applied).

**Carried (agreed in l2s-wp5-r1):**
- **WP6:** `Engine.offer_edit` replaces a pending, not yet applied draft without an event (log the overwrite);
  re-check the stop -> release gap between `run()`'s check and the generation the engine records at `start()` (fix 1
  covers requests made inside the run, not that gap); a warning before `zero` runs; `zero` is NOT accepted as meeting
  U12 (no tracking zero; owner to confirm what it means).
- **WP6:** show the value-only edit restriction in the GUI.
- **Phase 8 editor:** structural mid-run edits and statement identity (so inserts / deletes can be told apart).

**Carried (agreed in l2s-wp5-r2):**
- **WP6:** the focus reference is read twice at a start (once by `run()`'s check, once by `Engine.start()`); they
  can differ - use one read for both. A failure in `Engine.start()` (e.g. the focus read) raises to the caller but
  logs no event. `test_mid_run_edit_applies_at_next_step_boundary` depends on timing (a 0.1 s sleep to land inside
  the first hold); make it signal-driven.
- **Phases 6-8:** screening `rule` lines are not part of the structure comparison (`structure_diff` compares the
  statements only), so a mid-run edit may change, add or remove rules; decide when rules are evaluated.

**Carried (agreed in l2s-wp5-r3):**
- **WP6:** the one-run test assumes A's engine (`wait t=1`) is still running when B gets the lock; make the run's
  end a signal too.

**Owner decisions 0016, implemented (2026-10-25, `api.VERSION = "0.6.0"`, simulators and files only):**
1. **Rig safety profile v2** (magnet speed max 15 mm/s), made ONLY through the admin write path
   (`mtpy.admin.safety_admin`: caller `rig-admin`, `open_admin_session` -> `propose_change` -> `activate`; no hand
   edit of `config/`). v2 = v1 + `magnet_speed_mm_s` [0, 15] mm/s, `verified: true`; every other limit is identical
   (stage x/y +-2 mm, magnet travel 0-39 mm, rotor / focus / force still unverified or unset); v1 stays in
   `config/safety_profiles/1.json`. **Its re-commissioning record says the value comes from the owner's decision
   and that NO move-and-read-back at 15 mm/s was done** (no hardware here): the rig check is a WP6 carry. Effect:
   magnet moves (`move_to`, `zero`, `move mm=`) were allowed up to 15 mm/s; force steps still failed (no
   `magnet_force_pN` maximum). **Superseded by v3 (review l2s-wp5-r4, below): v2's `verified: true` / `checked: true`
   recorded the owner's value as a rig check, which it was not.** v2 stays in the history as written.
   The WP1 profile / admin tests start from a v1-only config (their fixture), unchanged otherwise.
2. **`zero`** = magnet to 0 mm, owner-confirmed; the U12 tracking zero stays open (grammar.md 12.7).
3. **`end protocol`** (grammar.md 12.18): last statement at the top level; logs `protocol` `end_statement`, then
   `api.acq.set_recording(False)` (acquisition keeps running), run `completed`. Without it recording continues after
   the protocol; stop / e-stop never switch it off. Tests: `test_end_protocol_parse_rules`,
   `test_end_protocol_switches_recording_off_and_closes_the_interval` (HDF5 `/recordings` off_buffer = the off event,
   no row after it), `test_without_end_protocol_recording_keeps_going`.
4. **`.tra` frame column from the first RECORDED frame** of each segment (`legacy_matrix`, `export_tra`, and the
   MATLAB reader): `buffer - smallest recorded buffer of the segment`. Test:
   `test_tra_frame_column_counts_from_first_recorded_frame` (recording started 20+ frames after acquisition).
5. **MATLAB 2026** is the target of `matlab/read_mtpy_h5.m` (header note).

**Carried (decision 0016):**
- **WP6:** run `matlab/read_mtpy_h5.m` in MATLAB 2026 (release letter not given; not installed on the development
  PC), including its new frame rule; check magnet moves at 15 mm/s on the rig (move and read back) and record it in a
  re-commissioning report; `magnet_force_pN` maximum still to be set by the owner.

**Review l2s-wp5-r4 fixes (simulators and files only):**
1. **Admin path:** `safety_admin.activate` lets a changed entry go without `checked` ONLY when its new value is
   `verified: false` AND the new profile has `allow_unverified: false` (it refuses every request, so nothing is
   claimed as checked); such entries are listed in the record as `recommissioning.not_checked_unverified`. Any other
   new or changed entry - a `verified: true` change, or any change while `allow_unverified` is true - still needs
   `checked`.
2. **Profile v3** through the admin path (`rig-admin`, open -> propose -> activate, `checked: {}`; no hand edit of
   `config/`): `magnet_speed_mm_s` [0, 15] mm/s `verified: false`, `allow_unverified: false`; reason: v2's check was
   the owner's value, not a rig move-and-read-back. v1 and v2 stay in the history; every other limit is identical to
   v1. Result: **every magnet move is refused again** (also `zero`, `move mm=`) until a rig move-and-read-back at
   15 mm/s activates a verified entry with `checked`.
3. Tests: `test_shipped_config_is_v3_magnet_speed_15_unverified`, `test_unverified_change_activates_without_checked_and_refuses`,
   `test_verified_change_without_checked_is_refused`, `test_no_unchecked_exception_when_unverified_limits_are_allowed`,
   `test_shipped_profile_refuses_rotor_and_focus` (10, 15, 16 mm/s and the omitted speed refused, nothing moves),
   `test_shipped_profile_v3_refuses_magnet_moves_before_anything_runs`, `test_profile_v1_still_refuses_every_magnet_move`.

**Carried (agreed in l2s-wp5-r4):**
- **WP6 / rig session:** the 15 mm/s rig check (move and read back; then a new profile version with
  `verified: true` and `checked`); run `matlab/read_mtpy_h5.m` in MATLAB 2026.
- **WP6 (one-run test):** the negative control is a scratch file, not committed (make it a committed, opt-in test);
  joining a B thread that never started (an assertion before `b.start()`) must not hide the first failure; the
  assumption that A's engine is still alive at `wait t=1`.
- **Policy:** a future `allow_unverified` false -> true switch must cover the entries that were never rig-checked
  (e.g. those in `not_checked_unverified`): switching it on must not turn an owner's value into a usable limit
  without a rig check.

**Implemented in WP6 (2026-10-25, `api.VERSION = "0.7.0"`, simulators and files only):**
- **Walking skeleton** `tools/walking_skeleton.py` (how to run: [dev/walking-skeleton.md](../../dev/walking-skeleton.md);
  test `tests/test_walking_skeleton.py[protocol | estop]`, needs the G: fixture). Through the public API only: a copy
  of `config/` in the output folder (the shipped files are never written; sha256 compared before and after); with
  the shipped profile (then v3; now v4, see below) the protocol is refused before anything moves; a TEST-ONLY next version (v4, now v5) in the copy through the admin
  path (magnet speed [0, 15] mm/s and force [0, 20] pN marked verified, report notes "TEST ONLY ... NOT a rig
  check"); sim devices with the fixture frames, camera preset 90 Hz read back, beads 1-5 of `cal002` (bead 1 =
  reference, user role), a TEST-ONLY force table; recording to HDF5; a `.mtprot` with hold / move / mark / loop of
  ramps / `zero` / `end protocol`; stop; then the file is read and exported and 17 checks run (frames, one segment,
  rate triple preset / read back / measured, every step's start / end line, mark, recording on / off, magnet on
  every frame following the moves, `.tra` frame column from the first recorded frame and magnet column = `/mt`,
  `.cal` byte-identical, roles). `--estop`: the stop is engaged during a magnet move; 20 checks since 1b52a11 (19 before; the 20th: at least 2 new magnet
  readings with distinct completion times after the stop, present in `/mt`) (run aborted at the
  step's line, magnet stopped in place and still there after the release, acquisition and recording go on, frames
  after the stop in the file, magnet column constant after it, no move read-back after it, file closed cleanly).
- **New / changed:** `acq.start(..., motor_poll_s=0.05)` (None = off); `acq.status()` gains `camera_stop` and
  `motor_poll`; `Beads.roi` / `beads.select` keeps the camera ROI; `devices.reconnect("camera")` during acquisition
  is a segment end; `camera.apply_preset` remembers the preset for the run file (`/metadata/presets/camera`, so the
  frame-rate triple has its preset value); `HDF5Writer.note_error`; `mtpy.data.hdf5.mt_rows`; `Engine(gen=,
  focus_z0=)`. New events: `motor_reading`, `motor_reading_error`, `sink_error` (in the file), `protocol` actions
  `warning` and `start_failed`, `protocol_edit` action `replaced`, `device_fault` with `applied_after_timeout`.

| WP6 carry (where agreed) | Result | Test, or reason |
|---|---|---|
| per-frame magnet / rotor reading, off the frame path (WP4-r1) | done: `api.acq` poller thread reads `api.magnet.position` / `api.rotor.position` every 50 ms (one read before the first frame), `motor_reading` events with the newest frame; writer fills `/mt` from them | `test_motor_poller_gives_every_frame_a_reading_off_the_frame_path`, `test_slow_or_failing_motor_never_blocks_acquisition` |
| `sink_error` stored in the file (WP4-r1) | done: pipeline -> `note_error` -> `/events/sink_error` + root `sink_failures` (limit: a failing file may not take the row either) | `test_sink_error_is_stored_in_the_file`, `test_sink_error_before_the_file_exists_is_written_when_it_opens` |
| failed `stop_acquisition` must not hide a running camera (WP3-r2 d) | done: `acquiring()` read separately after every stop; `camera_stop` in status + event | `test_failed_stop_does_not_hide_a_running_camera` |
| ROI at bead selection, origin compared at start (WP3-r2, U23) | done (None when no camera connected at selection: size check only) | `test_roi_origin_moved_while_stopped_is_refused_at_start` |
| `wait_arrival` generation check (WP2-r2) | done (also the run scope) | `test_estop_engaged_and_released_during_a_move_ends_it_cancelled` |
| a send applied after a reply timeout (cycles, WP2) | done: abandoned atomically under a per-request lock; a late send is not sent if still queued, else stopped again with an event (a camera setting's `stop()` is a no-op: the event records it) | `test_send_applied_after_reply_timeout_is_stopped_again` |
| `offer_edit` replacing a pending draft logs an event (WP5-r1) | done | `test_offer_edit_replacing_a_pending_draft_logs_an_event` |
| e-stop engage + release between `run()`'s check and the engine's generation (WP5-r1) | done: the run's generation is taken when `run()` is called; a change during the check refuses; after it, the engine aborts at once | `test_estop_engaged_and_released_during_the_run_check_refuses_the_run`, `test_estop_between_the_check_and_the_engine_start_aborts_with_nothing_sent` |
| warning before `zero` (WP5-r1) | done | `test_zero_logs_a_warning_before_the_magnet_moves` |
| focus reference read once (WP5-r2) | done | `test_focus_reference_is_read_once_for_check_and_engine` |
| `Engine.start()` failure logs an event (WP5-r2) | done (`start_failed`, also for the focus read) | `test_engine_start_failure_logs_an_event`, `test_focus_read_failure_at_start_logs_an_event` |
| loop value-edit test timing-independent (WP5-r2) | done: the engine pauses itself in the step-start event of the first hold | `test_mid_run_edit_applies_at_next_step_boundary` |
| one-run test: negative control committed (WP5-r4) | done, runs always (fast: B's progress = waiting or finished) | `test_one_run_negative_control_without_mutual_exclusion_fails` |
| one-run test: join of a never-started B (WP5-r4) | done: only started threads are joined | `overlapping_runs` |
| one-run test: A alive at B's decision (WP5-r3 / r4) | done: A's engine is held by a signal; asserted | `test_only_one_run_starts_and_the_running_one_is_never_overwritten` |
| crash during a flush incl. the back-fill (WP4-r1) | done for two tested points + reader rule (`frames_written`, `mt_rows`) | `test_crash_inside_a_flush[mt columns | back-fill]` |
| motor back-fill across several 4096-row blocks (WP4-r2) | done (9000 rows, three blocks) | `test_late_motor_reading_backfills_across_several_flushed_blocks` |
| camera reconnect as a segment end (WP3-r1) | done (refused restart if the ROI no longer suits the beads) | `test_camera_reconnect_while_recording_is_a_segment_end` |
| `mtpy.api` <-> `mtpy.devices` import cycle (WP3-r1) | done: `import mtpy.devices` first FAILED before; fixed (devices loads `mtpy.api` first, camera imports `mtpy.devices.base`) | `test_import_order_devices_first_works` |
| long runs (WP3-r1) | deferred | needs hours of acquisition; phase 6 soak on the rig (frame loss at 150 Hz) |
| value-only edit restriction shown in the GUI (WP5-r1) | deferred | phase 8 (no GUI yet) |
| 15 mm/s magnet move and read-back, then a verified profile (0016, WP5-r4) | done 2026-10-25 (V6 card pivel15r) -> profile v4 (8068225); see "Rig check evidence and its limits" below | V6 tools/bench/pi_vel15_check_20261025.log |
| MATLAB 2026 run of `matlab/read_mtpy_h5.m` (0016, WP4-r1) | not done | no MATLAB here; that run should also add the crash-file rule (`frames_written`) to the MATLAB reader |

- **Unchanged, owner decisions pending:** `.tra` origin when recording restarts within one segment; `end protocol`
  keeps acquisition (current behaviour); the `magnet_force_pN` maximum; when the U12 tracking zero is set; whether
  value-only mid-run edits meet U18.
- **Limits:** poller readings are PC-timed (0005: ms level), not exposure-accurate; its reads share the device
  service queue with moves (interleaved, never on the frame path); the skeleton's TEST-ONLY profile and force table are
  TEST ONLY and live only in its output folder.

**Review l2s-wp6-r1 fixes (simulators and files only):**
1. **Skeleton destination:** `walking_skeleton.check_destination` refuses (ValueError) BEFORE anything is written
   when `<out>/config` is the repository's `config/`, lies inside it or contains it, or already exists; nothing is
   ever deleted (`rmtree` removed). Tests `test_destination_overlapping_the_repository_config_is_refused_before_writing`,
   `test_existing_config_in_the_destination_is_refused_and_kept`.
2. **Poller time:** `t_read` is the read's COMPLETION time; `t_request` (when it was asked) is a separate field, not
   used for `/mt`. Test `test_poller_reading_counts_from_its_completion_time` (a read held by a signal is not shown on
   the frames received while it was outstanding).
3. **Test filter:** `_no_poll` leaves out only `motor_reading`; `motor_reading_error` stays visible.
4. **U8 state:** poller reads run in `mtpy.devices.base.passive_reads()`: a successful poll never clears an error or
   slow state (a failing one still marks it). Test `test_poller_read_does_not_clear_an_error_state`.
5. **E-stop variant:** a 20th check - at least 2 new magnet readings with distinct completion times after the stop,
   and `/mt` after the stop shows those readings (magnet only).

**Carried (agreed in l2s-wp6-r1):**
- **Phase 6:** the MATLAB 2026 run of `matlab/read_mtpy_h5.m`, with the crash-file rule (`frames_written`) added to
  it; the in-process `api.events` list grows without bound (soak test / bounded history); the real PI `POS?` reply
  time and the device-queue occupancy of the poller next to moves; whether and how `t_request` is used.
- **Minor:** the skeleton check name "10 mm at the 1 pN hold" (its test reads the ramp maximum, 11.111 mm); the
  `move mm=3` step's position is not checked by the skeleton.
- **Phase 8:** show the value-only mid-run edit rule in the GUI.

**Rig safety profile v4 (2026-10-25, shipped; config changed only through the admin path):** the 15 mm/s rig check
was done on the real PI C-863.11 (V6 card pivel15r, PASS 3/3 gates, log V6
`tools/bench/pi_vel15_check_20261025.log`: session start with reference and limits TMN 0 / TMX 39 read back;
VEL? = 15 (it already was 15); MOV 1 30 -> POS 30.00000, ERR 0, ONT 1, motion about 2.25 s vs 2.05 s expected;
MOV 1 0 -> POS 0.00000, ERR 0; session end with limits released and read back. The bgrun wrapper's last line says
rc=1 only because rig_session's own RESULT line is not in its result-line/1 schema; the process exited 0). v4 =
v3 with `magnet_speed_mm_s` [0, 15] mm/s `verified: true`, made by `rig-admin` (open -> propose -> activate) with
`checked: {"magnet_speed_mm_s": true}` - the normal checked path, no unverified exception - and that log cited in
the report notes and the limit's source. Every other limit is identical to v3; v1-v3 stay in the history.
Effect: magnet POSITION moves (`move_to`, `zero`, `move mm=`) at <= 15 mm/s pass the profile (given or read-back
speed); > 15 mm/s is refused; force steps (`set_force`, `hold`, `ramp`, `rotate`) are still refused - no
`magnet_force_pN` maximum (owner); rotor and focus unchanged (refused). The walking skeleton's TEST-ONLY profile is
now the shipped version + 1 (v5) in its own copy. Tests: `test_shipped_config_is_v4_magnet_speed_15_rig_checked`,
`test_shipped_profile_v4_magnet_moves_up_to_15_mm_s_rotor_focus_force_refused`,
`test_profile_v3_still_refuses_every_magnet_move`, `test_shipped_profile_v4_runs_position_moves_and_refuses_force_steps`,
`test_profile_v3_still_refuses_magnet_moves_before_anything_runs`. This closes the "15 mm/s rig check" carry of the WP6
table above; the profile change was not run through the simulator-only skeleton as a rig claim.
(Superseded in part by decision 0017 below: force steps are no longer refused for lack of a force maximum; v4 is now
history, v5 is shipped; the tests above were renamed.)

### Decision 0017: force limit from the position limit (2026-10-25, `api.VERSION = "0.8.0"`)
The danger is the magnet hitting the stage, not a large force, so the only magnet safety limit is the position limit
(`magnet_position_mm`, today [0, 39] mm, verified). There is no separate maximum force.
- **Profile v5** (shipped; made through the admin path as `rig-admin`, open -> propose -> activate): v4 with the
  `magnet_force_pN` entry **removed** (the simpler safe option, chosen over a derived non-editable entry: nothing in
  the profile can drift from the table, and `safety.check("magnet_force_pN", ...)` refuses as "not in the profile").
  Every other limit is identical to v4 (`unverified` loses `magnet_force_pN`); `checked: {}` (nothing added or
  changed, so there is nothing to move to on the rig); v1-v4 stay in the history. A `magnet_force_pN` entry in an
  older profile (v1-v4) is ignored by the force path.
- **Force -> position** (**the refusal below is replaced by decision 0018: such a force is now coerced, see the next
  section**): `set_force(force_pN, table=None)` converts the force through the table in use (0010) with
  `force_position(force_pN, table=None)` (read only; nothing moves or is logged) and checks that position against the
  position limit **before anything moves**; a force reachable only outside the limit, or outside the table, is
  `SafetyRefused` with the requested force, the position it needs, and the table's force at the limit end, e.g.
  "magnet force 25 pN needs magnet position 40.6897 mm by the force table 'wide test table', outside the magnet
  position limit [0, 39] mm; the table gives 23.04 pN at the limit end 39 mm (reachable force [0.1, 23.04] pN ...)".
  Then `move_to` checks speed (<= 15 mm/s) and position again as before. No table -> `NotReady` (as before).
- **Tables:** `position_mm` must now be strictly monotonic (needed to invert the table); force strictly increasing as
  before.
- **`force_range(table=None)`** (read only): the reachable force range = the table's force at the position-limit
  ends, clipped to the table's own ends: `{"force_pN": (min, max), "position_mm", "limited_by": ("position limit" |
  "table end", ...), "position_limit_mm", "table", "table_version", "profile_version"}`. Loading another table
  changes it without any profile change; changing the position limit is a profile change.
- **Protocol checker:** `hold` / `ramp` / `rotate f=` forces go through `force_position` in the profile layer when a
  table is loaded (an out-of-range force fails the check with its line and column); with no table the profile layer
  gives a warning and the rig-state layer (`run()`) refuses the step. `zero` and `move` are position moves (unchanged).
- **Unchanged:** speed (`magnet_speed_mm_s` <= 15 mm/s, verified); rotor and focus limits (unverified / unset ->
  refused).
- **Walking skeleton:** runs on the shipped v5 copy unchanged (no TEST-ONLY profile any more); its first checks are
  now "force beyond the magnet position limit refused before anything moves" (a TEST-ONLY wide table) and "shipped
  profile, the protocol passes the check". Tests: `test_shipped_config_is_v5_without_a_force_limit`,
  `test_history_v4_magnet_speed_15_rig_checked`,
  `test_profiles_v4_and_v5_magnet_position_moves_up_to_15_mm_s_rotor_focus_refused`,
  `test_shipped_v5_force_inside_the_reachable_range_runs`,
  `test_force_needing_a_position_beyond_39_mm_is_refused_with_the_numbers`, `..._below_0_mm_...`,
  `test_changing_the_force_table_changes_the_reachable_range_not_the_profile`, `test_no_force_table_force_requests_refused`,
  `test_shipped_profile_v5_runs_position_moves_and_force_steps_in_range`.

### Decision 0018: live force equation and coercion (2026-10-25, `api.VERSION = "0.9.0"`)
Replaces the refusal of 0017 item 2: a force (or a direct magnet position) outside what the magnet position limit
allows is **coerced to the nearest reachable value** - no alarm, no refusal - and written back everywhere.
- **Calibration** (`mtpy.forcecal`, pure maths, swappable per 0010): the default is `M270_V3`, "M270 v3 (LabVIEW
  Magnet2Force v3, case 1)", computed live: `F_pN = 48.8162*exp(-d/1.13483) + 22.8394*exp(-d/3.68428) - 0.45845`,
  `d = touch_mm - pos_mm` (read from `Magnet2Force v3_for M270.vi` case "1, Default" and checked by running it, V6 card
  m2feq2: 16 points, worst relative deviation 2.2e-16; `Max Trans Pos.vi` is an identity). F rises strictly with the
  position. The inverse is a bisection on the reachable position interval to 1e-9 mm. The VI's unused case "0" is
  kept as `M270_CASE0`, a named alternative, never the default. A recorded table (`TableCalibration`, the pre-0018
  default) works behind the same interface (`force`, `position`, `domain`, `describe`).
- **Session state:** `api.magnet.set_touch_position(mm)` ('Mag pos when touched to glass'; reset at every connect);
  `use_force_calibration(name_or_object)`; `use_force_table(table)`; `force_calibration()` (name, kind, equation,
  constants or table, `touch_mm`, `ready`, `why`). Each change is a `calibration` event. Without a touch position
  the equation is not ready: `set_force` / `force_range` / `coerce_force` / `force_at` raise `NotReady`.
- **Forces:** `coerce_force(f)` (read only) -> `{"requested_pN", "applied_pN", "position_mm", "coerced", "reason",
  "calibration", "touch_mm"}`; the reachable range is `[F(limit min), F(limit max)]` for the current touch
  (`force_range()`, now also `calibration`, `kind`, `touch_mm`, and for an equation `touch_beyond_limit`).
  `set_force(f)` moves to the coerced force's position and returns the Motion with `requested_pN`, `applied_pN`,
  `coerced`, `position_mm` (so the GUI rewrites the typed field and the applied field). A coerced request logs a
  `coerced` event (request, applied, position, reason, calibration, touch) before `force_request` and `act`.
  `force_position(f)` = the coerced position. A non-finite force is still refused; |applied - requested| <= 1e-9 is
  numerical noise (applied silently).
- **Direct positions (0018 item 5):** `move_to(p)` outside `magnet_position_mm` -> the nearest limit, `coerced`
  event, Motion `requested_mm` / `applied_mm` / `coerced`. Non-finite -> refused.
- **Second safeguard (0018 item 4):** the device send (`magnet._send`) coerces the final position into the limit once
  more, whatever the caller computed (a `coerced` event with `stage: "send"` when it had to); the controller's TMN /
  TMX remain the hardware layer below. Speed is unchanged: `magnet_speed_mm_s` above 15 mm/s is refused.
- **Protocols:** the checker coerces instead of failing (forces of `hold` / `ramp` / `rotate`, `move mm=`); the report
  gains `coerced` (line, col, key, requested, applied, reason, calibration), `text` (the corrected source = the edit
  buffer) and `script` (its parsed plan). `run()` runs that plan and `edit()` keeps it as the draft; both log one
  `coerced` event per value (`stage: "protocol run check"` / `"protocol edit check"`, original and plan sha256). The
  plan's numbers have at most 4 decimals, rounded toward the inside, so the run needs no second coercion; a change of
  touch or calibration during the run is still coerced by `set_force` at each step.
- **Off the frame path (0018 item 1):** the acquisition's motor poller adds `force_pN`, `force_calibration`,
  `touch_mm` to each magnet `motor_reading` (via `magnet.live_force`, two exponentials, never on the acquisition
  thread); the raw record stays the position (0010).
- **Run file (0010):** `metadata/devices/magnet/force_calibration_at_start` = `force_calibration()` at acquisition
  start (name, equation, constants, touch); later changes are `calibration` events in `/events`.
- **Open point (not decided, owner):** when `touch_mm` is below the position-limit max (39 mm), positions between
  touch and 39 mm give d < 0 and very large forces (F(d = -5) = 4088 pN; F(d = 1) = 37.18 pN). The code then treats them as reachable:
  the force range's max is F(39 mm), a large force request moves the magnet past the touch position up to 39 mm, and
  only the position limit stops it; `force_range()["touch_beyond_limit"]` is True. Whether the limit should follow
  the touch position (e.g. min(39, touch)) is for the owner.
- Tests: `tests/test_forcecal.py` (equation values at d = 0 and 2 and more, round trip, cost, table interface);
  in `tests/test_devices.py` `test_direct_position_outside_the_limit_is_coerced_to_the_nearest_limit`,
  `test_last_step_coerces_whatever_the_caller_computed`, `test_table_force_above_/below_the_reachable_range_...`,
  `test_default_calibration_is_the_live_equation_and_needs_the_touch_position`,
  `test_equation_force_coerced_above_and_below_and_touch_changes_the_range`,
  `test_bad_internal_position_from_a_calibration_is_still_coerced`; in `tests/test_protocol.py`
  `test_check_coerces_out_of_range_force_and_position_in_the_checked_plan`,
  `test_shipped_profile_v5_runs_position_moves_and_force_steps_in_range` (coerced ramp runs to 39 mm),
  `test_equation_run_file_records_calibration_coercion_and_live_force`. Walking skeleton: "default force
  calibration is the live equation" and "force beyond the magnet position limit coerced, not refused; runs to 39 mm".

## 4. Example: the enzyme-cleavage experiment as a Python experiment script (level 3)
```python
from mtpy import api   # api.VERSION >= 0.1

api.presets.load("rig", "MT-TIRF 60x/1.50")
api.camera.apply_preset("Experiment 90 Hz")
api.magnet.set_force(force_pN=2.0).wait(timeout_s=30)
api.light.load_sequence("green, red every 10th")
api.acq.start(record=True, name="cleavage_run01")
api.light.start_sequence()
cut = api.events.rule("present(Cy3) and not present(Cy5)")
api.events.on(cut, lambda ev: api.acq.mark(f"cleaved spot {ev.spot} at {ev.t_s:.1f} s"))
api.acq.wait_frames(n=90 * 600, timeout_s=700)       # 10 min at 90 Hz
api.light.stop_sequence()
api.acq.stop()
api.data.save_run(folder=None, name=None)             # None -> file dialog at the start folder (U21)
```
The script file and its version are stored with the data (0015 item 4).

### Rig check evidence and its limits (review l2s-wp6-r2, peer V6 archive/peer/2026-10-25-pivel15_rcfail.md)
- **What v4's `verified: true` rests on:** `VEL?` read back 15 after `VEL 1 15`; the 30 mm move out and back reached
  30.00000 / 0.00000 by the controller's encoder with `ERR?` 0 each time; the session start (reference, limits 0 / 39
  read back) and end (magnet at 0, limits released and read back) were clean. The admin path check is structural
  (the normal `checked` path was used).
- **What it does not show:** the controller was already at VEL 15, so the effect of a speed WRITE is untested; the
  elapsed-time check polls about every 0.525 s and would pass any speed from about 11.5 to 20 mm/s (the "+9.8 %"
  figure is not a real precision; uncertainty about +-12 %). The encoder belongs to the same controller (no
  independent position check).
- **The rc=1 of that log** comes only from `rig_session.py`'s final summary line, which is not a valid result-line/1;
  every other RESULT line passed. Fix belongs to V6 tooling (rig_session prints a valid result line; bgrun unchanged,
  it checks every RESULT line on purpose).
- **Speed-write test DONE 2026-10-25 10:47 (owner: "속도 변경 하도록 하고"; V6 card pivelsw, PASS 5/5; log V6
  tools/bench/pi_velsw_check_20261025.log):** VEL 15 -> 10 read back 10, ERR 0; 30 mm move at 10 mm/s reached
  30.00000, ERR 0, elapsed 5.2 s (predicted 4.9-5.6 s); VEL 10 -> 15 read back 15; move back at 15 mm/s reached
  0.00000, ERR 0, elapsed 4.1 s (predicted about 4.1 s); difference 1.1 s vs predicted 0.98 +- 0.525 s (one poll). So
  the speed write takes effect; the time resolution stays about one poll (0.5 s). VEL left at 15; session end clean.
- **Carries:** Phase 8: show the time of the last reply
  (`last_reply_t`). V6 tooling: rig_session RESULT format.

## 5. Open
- Final names and the split between `api.magnet` / `api.focus` / `api.stage`.
- Event-rule expression grammar (shared with the protocol grammar spec, U19).
- Which functions the AI gateway may call at each permission tier (0014).
- Thread model for callbacks (`events.on`) and how scripts are stopped safely.
