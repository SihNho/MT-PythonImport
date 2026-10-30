# Status (2026-10-30)

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
- **2026-10-30 (owner: "Shutdown + lock"):** decision 0026 - the program holds the shared rig lock itself
  (`api.rig`, taken by `devices.connect` for real backends, released only after a clean `disconnect`) and shuts
  down through a visible step dialog (`gui/shutdown.py`, design/shutdown.md); `MT Tracker (rig).cmd` runs the GUI
  without the V6 wrapper. Same day on the rig: owner's motor sequence (results/2026-10-30-motor-sequence.md), iXon
  first contact, shutter freed by cycling, 47.5 fps max at VS 3.3 us (results/2026-10-30-emccd-*.md),
  camera parameter catalogue (design/camera-parameters.md).
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

## Rig (state: assembled; 2026-10-30 owner: experiment over, a channel with reference and magnetic beads together is mounted)
- Rig safety profile **v5**: magnet 0..39 mm and 15 mm/s, both rig-verified (speed write 10 <-> 15 shown to take
  effect); rotor, focus unverified -> refused. ASI +-2 mm from the session start.
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
