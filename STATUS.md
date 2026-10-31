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
  new LUT is still to run on the rig), item 5 (eBUS extras when the MT experiment is fixed, selectable in
  the GUI), then a UI/UX discussion.
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
