# Tethered-bead calibration test under force clamp (prepared 2026-10-28, not yet run)

Owner 2026-10-28: with magnetic beads under about 7 pN, the real-time fluctuation is stronger, so exposure time,
band-pass, z step and frame averaging may matter differently than on fixed beads (and again after a lens change).
Everything below is ready to run the moment the owner asks; nothing here has touched the rig.

## What is recorded (plan `tether` in `tools/refbead_record.py`)
**High force first, low force last** (owner 2026-10-28): a bead left near the surface at low force may bind
non-specifically despite the PEG coating; with the low-force part at the end, such a trace is cut away without
losing the rest. Two rules from the owner shape the plan:
- **the exposure must be the same in calibration and in measurement**, so every exposure gets its own LUT and its own
  rest recording, and the cross-combinations are only an offline check;
- **does the calibration force matter?** the LUT is also taken at a higher force (default 38 mm), and the noise at the
  measurement force (default 36.4 mm) is scored with the LUT from each position.

1. magnet to the highest calibration position (default 38 mm), 3 s settle;
2. per exposure time (default 1909 / 1000 / 500 us at 150 Hz):
   - 20 s at rest (`clamp_m<mm>_e<us>`): fluctuations under force = the measurement noise at that force;
   - z-scan +-5 um in 100 nm steps, **0.5 s (75 frames) per slice** (`zs_m<mm>_e<us>`): the LUT, and offline tests
     of frame averaging (1..75) and z step (100 / 200 / 300 / 500 nm by sub-sampling);
   - z-scan +-3 um in 50 nm steps, 0.5 s per slice (`zf_m<mm>_e<us>`; skipped with `--no-fine`);
3. the same at the next lower position (default 36.4 mm = the measurement clamp);
4. at the end, 10 s at the clamp (`clamp_end_*`), magnet to 0 mm, 10 s at rest (`rest0_*`): the beads that move
   between the two are the tethered ones.
About 7 min per exposure and position: 44 min for 3 exposures x 2 positions with the 50 nm scans, 26 min without
(`--no-fine`). Raw crops 160 x 160 px per bead; about 8 GB per exposure and position for 15 beads. Band-pass and
forget are offline parameters (stored per bead in the LUT), so they need no extra recording.

## Clamp position
- `--magnet-mm` is the owner's number: the position that pulls the tether to about 1600 nm. 36.4 mm is only the
  M-270 v3 equation's value for 7 pN at a touch position of 40.94 mm (`mtpy.forcecal`); with another touch position
  it moves (touch 39 mm -> 34.4 mm). The owner checks the extension in LabVIEW first and gives the position.
- The gate bounds it to 0..39 mm; the plan ends at 0 mm.

## Before the run (owner)
1. Sample in, beads found in LabVIEW as usual, the field chosen so that it holds **at least one reference bead** and
   the tethered beads of interest; note the clamp position; then **close LabVIEW** (it owns the camera).
2. Rig state `assembled`, no experiment declared; say the word in chat.

## The run (chat)
```bash
cd "G:/Codes/LabVIEW_Codes/MinLab/zz_LabView VI/AAA_UNIST/2. Tracking/V6_ParallelLoop" && py -u tools/rig_session.py --purpose "LabVIEW2Scr tether calibration test (owner <date>)" --max-min 3 --no-motor-session -- py -u G:/Codes/LabVIEW2Scr/tools/refbead_record.py snap --out G:/l2s_rig_data/<date>_tether/snap
```
The snapshot's `beads.json` is checked (the picked beads are shown as an image); tethered beads at the clamp look like
fixed ones, so the pick rules apply unchanged. Then:
```bash
cd "G:/Codes/LabVIEW_Codes/MinLab/zz_LabView VI/AAA_UNIST/2. Tracking/V6_ParallelLoop" && py -u tools/rig_session.py --purpose "LabVIEW2Scr tether calibration test (owner <date>)" --max-min 40 -- py -u G:/Codes/LabVIEW2Scr/tools/refbead_record.py run --plan tether --magnet-mm <owner's mm> --calib-mm 38,<owner's mm> --exposures 1909,1000,500 --out G:/l2s_rig_data/<date>_tether --beads G:/l2s_rig_data/<date>_tether/snap/beads.json
```
Stop conditions as always: a gate refusal stops the plan and `rig_session` cleans up (magnet 0 mm, limits
released, camera closed); experiment / LabVIEW / another lock holder -> hands off.

## Analysis (offline, no rig)
1. Tethered vs reference: in `clamp_end_*` and `rest0_*`, a bead whose mean z / xy moves between the two is tethered.
2. Per exposure and position, the parameter sweep on the z-scan with a tethered bead paired with a reference bead:
```bash
cd G:/Codes/LabVIEW2Scr && .venv/Scripts/python.exe tools/refbead_params.py sweep-run G:/l2s_rig_data/<date>_tether/tether zs_m36.4_e1909 <tethered crop col>,<reference crop col>
```
   gives noise and slice error for band / forget, frames per LUT slice and LUT step.
   **Noise at the measurement force with each LUT** (same exposure = the rule; other exposure or the 38 mm LUT = the
   check), per bead, std of z - z_ref at full rate and after 1 s averaging:
```bash
cd G:/Codes/LabVIEW2Scr && .venv/Scripts/python.exe tools/refbead_params.py rest-noise G:/l2s_rig_data/<date>_tether/tether clamp_m36.4_e1909 zs_m36.4_e1909 <cols incl. the reference> <reference col>
cd G:/Codes/LabVIEW2Scr && .venv/Scripts/python.exe tools/refbead_params.py rest-noise G:/l2s_rig_data/<date>_tether/tether clamp_m36.4_e1909 zs_m38_e1909 <cols incl. the reference> <reference col>
```
3. Methods (current / QI / polar3 / spline / phasor) on the same frames: `tools/track_bench.py` with `ZSCAN` and
   `BEADS` pointed at the tether run (a `--run` option is added when the data exists).
4. Force from the clamp fluctuations (x variance, 203 nm / px) against the equation's value: a check of the force
   scale with the measured pixel size.

## Open until the data exists
- Whether the bead pick rules hold for tethered beads at the clamp (ring contrast may differ).
- The 50 nm scan goes through the decimal-Z gate (V6 `723471e6`); the LUT from it is tested like 2026-10-27.
