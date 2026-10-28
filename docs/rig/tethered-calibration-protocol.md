# Tethered-bead calibration test under force clamp (prepared 2026-10-28, not yet run)

Owner 2026-10-28: with magnetic beads under about 7 pN, the real-time fluctuation is stronger, so exposure time,
band-pass, z step and frame averaging may matter differently than on fixed beads (and again after a lens change).
Everything below is ready to run the moment the owner asks; nothing here has touched the rig.

## What is recorded (plan `tether` in `tools/refbead_record.py`)
**High force first, low force last** (owner 2026-10-28): a bead left near the surface at low force may bind
non-specifically despite the PEG coating; with the low-force part at the end, such a trace is cut away without
losing the rest. So the magnet goes to the clamp once and stays there for every exposure.
1. magnet to the clamp position (default 36.4 mm), 3 s settle;
2. per exposure time (default 1909 / 1000 / 500 us at 150 Hz):
   - 20 s at rest (`clamp_e<us>`): fluctuations under force, for noise and a force check from the variance;
   - z-scan +-5 um in 100 nm steps, **0.5 s (75 frames) per slice** (`zs_e<us>`): LUT and offline tests of frame
     averaging (1..75) and z step (100 / 200 / 300 / 500 nm by sub-sampling);
   - z-scan +-3 um in 50 nm steps, 0.5 s per slice (`zf_e<us>`; skipped with `--no-fine`);
3. at the end, 10 s at the clamp (`clamp_end_*`), magnet to 0 mm, 10 s at rest (`rest0_*`): the beads that move
   between the two are the tethered ones.
About 7 min per exposure; 22 min for three. Raw crops 160 x 160 px per bead; about 8 GB per exposure for 15 beads.
Band-pass and forget are offline parameters (stored per bead in the LUT), so they need no extra recording.

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
cd "G:/Codes/LabVIEW_Codes/MinLab/zz_LabView VI/AAA_UNIST/2. Tracking/V6_ParallelLoop" && py -u tools/rig_session.py --purpose "LabVIEW2Scr tether calibration test (owner <date>)" --max-min 40 -- py -u G:/Codes/LabVIEW2Scr/tools/refbead_record.py run --plan tether --magnet-mm <owner's mm> --exposures 1909,1000,500 --out G:/l2s_rig_data/<date>_tether --beads G:/l2s_rig_data/<date>_tether/snap/beads.json
```
Stop conditions as always: a gate refusal stops the plan and `rig_session` cleans up (magnet 0 mm, limits
released, camera closed); experiment / LabVIEW / another lock holder -> hands off.

## Analysis (offline, no rig)
1. Tethered vs reference: in `clamp_end_*` and `rest0_*`, a bead whose mean z / xy moves between the two is tethered.
2. Per exposure, per z-scan segment, the parameter sweep with a tethered bead paired with a reference bead:
```bash
cd G:/Codes/LabVIEW2Scr && .venv/Scripts/python.exe tools/refbead_params.py sweep-run G:/l2s_rig_data/<date>_tether/tether zs_e1909 <tethered crop col>,<reference crop col>
```
   gives noise and slice error for band / forget, frames per LUT slice and LUT step. Repeat per exposure.
3. Methods (current / QI / polar3 / spline / phasor) on the same frames: `tools/track_bench.py` with `ZSCAN` and
   `BEADS` pointed at the tether run (a `--run` option is added when the data exists).
4. Force from the clamp fluctuations (x variance, 203 nm / px) against the equation's value: a check of the force
   scale with the measured pixel size.

## Open until the data exists
- Whether the bead pick rules hold for tethered beads at the clamp (ring contrast may differ).
- The 50 nm scan goes through the decimal-Z gate (V6 `723471e6`); the LUT from it is tested like 2026-10-27.
