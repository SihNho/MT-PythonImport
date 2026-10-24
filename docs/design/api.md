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
