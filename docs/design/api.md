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
   allowed range.
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
  `magnet.move_to(..., speed_mm_s=None)` uses the controller's current speed unchecked, a given speed is checked
  against `magnet_speed_mm_s`. Positions, stage x/y and the rest read back through the service.
- `_act.acting` gained `check=` (a device-range check for settings that are not rig-safety-profile quantities, or
  that span two quantities like stage x/y) and `match=` (non-scalar read-back), and passes `NotReady` from the send /
  read-back through unchanged with a `cancelled` event; `_act.precheck` (e-stop + profile check alone) lets a Motion
  refuse on the caller's thread before its own thread starts. `estop.add_stopper(fn)`: `engage()` sets the flag,
  then calls each device's `stop()` directly (not queued); a failing stopper is an `estop_error` event.
- Quantity names in events for the non-profile settings: `camera_exposure_ms`, `camera_gain_dB`, `camera_rate_Hz`,
  `camera_roi`, `camera_preset`, `stage_xy_mm`, `light_<laser>`, `sync_ratio`.

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

## 5. Open
- Final names and the split between `api.magnet` / `api.focus` / `api.stage`.
- Event-rule expression grammar (shared with the protocol grammar spec, U19).
- Which functions the AI gateway may call at each permission tier (0014).
- Thread model for callbacks (`events.on`) and how scripts are stopped safely.
