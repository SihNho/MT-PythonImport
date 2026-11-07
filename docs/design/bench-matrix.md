# The bench matrix (owner 2026-11-01 20:55-21:05) and what has been run

The owner's list of benchmark dimensions for the tracking program on the rig, the measurements per run, the reduced
configuration run on 2026-11-01 night ("run the configuration you recommended, the rest is filled in later when the
bench is done properly") and the cells still open. Tools: `tools/rig_accuracy.py` (script), `tools/gui_rig_isolate.py`
with `STEPS=1 CLIENT=1` (GUI client of the engine process), `tools/rig_bench_matrix.py` (the blocks in order),
`tools/rig_bench_1107.py` (the 2026-11-07 blocks on the owner's six picked beads). Since 2026-11-07 the script
takes `CAL_MAGNET_MM` (the magnet position for the LUT; the owner calibrates at Cal+, 37.4 mm), `N_AVG` (frames
per LUT slice) and `HOLD=0` to switch off the drift hold: before every run's steps `rig_accuracy.hold()` reads the
tracked beads, moves the stage so they sit at their LUT positions again (image px per stage um from the 11-01 stage
steps: +4.71 in x, -4.82 in y) and the focus so their median z is the LUT's middle (a bead reading high: the sample
down), at most 2 um per round, three rounds, marks starting with "hold" (skipped by the analysis). Owner: "keep a
reference point and move the stage, z included, so the ROI stays; then it measures until the channel dries."
`rig_motion_noise.magnet_steps` now returns the magnet to where the run found it, not to 0.
Results: [results/2026-11-01-accuracy-fps-roi.md](../results/2026-11-01-accuracy-fps-roi.md) and the matrix page
that follows it.

## Dimensions
| dimension | values | note |
|---|---|---|
| frame rate / ROI | 90, 150, 248 Hz (full frame; 248 = the camera's cap), 555 Hz (640 x 512 at (344, 376): the cap at that ROI) | a LUT per rate, made at that rate (a 90-Hz LUT at 150 Hz read z 0.9 um low) |
| bead count | 5, 10, 20, 50, 100 | copies of the owner's beads (1, 13, 11, 8 of the 15:02 frame); the half ROI holds beads 2-4 only |
| z method | `current_v1` (LabVIEW's, the reference), `spline_v1`, `phase_spline_v1`; improved versions raise the number (decision 0030) | the old names are aliases |
| executor x precision | numba fp64 (the reference), cuda fp64 (the 0024 kernel, the baseline), cuda fp32 (the production candidate, 0030) | the bench tools' `EXEC`: numba, gpu (fp32), gpu64 |
| focus (piezo) speed | the opening speed, 1/10 of it | `api.focus.set_speed`; a slower move may leave less to correct after arrival |
| focus step size | 20, 50, 100 nm (staircase of five up, five down) and the +-1 um pattern (0, +0.5, +1, 0, -1, 0) | 20 nm is the size of the per-hold noise: compare hold means, hold 3 s |
| calibration frames (n_avg per LUT slice) | 10 (today's), and the rate-matched count that collects the same light as 10 at 90 Hz: 17 at 150, 28 at 248, 62 at 555 Hz | owner 2026-11-03: "put it on the list, later when there is time"; the LUT's own noise is a fixed bias, the live frame's noise averages out |
| motion in a run | focus steps, then stage xy steps 1 / 2 / 5 um in x and in y, then magnet 0, 10, 30, 0 mm | the 5-um stage step is the one that lost beads on 11-01 afternoon |
| where it runs | script alone, the GUI as a client of the engine process | the GUI has no ROI control and offers 90 / 150 Hz only: the tool sets those through the API and says so |

## Measurements per run
gaps / drops; tracking ms and latency as median / std / slowest 1 % / max; focus-step error raw and after
reference-bead correction (median / max |error|, nm); stage and magnet moves: z shift raw / corrected; per-hold z
noise; follow time (arrival report -> within 50 nm of the hold mean); overshoot (z 0.1-0.3 s after arrival against
the settled mean); lost bead-frames; in the GUI the GUI tick time.

## The reduced configuration (run 2026-11-01 night)
The focus speed and step size are properties of the focus drive and do not interact with bead count, executor or
the GUI, so they are measured in one condition (90 Hz, 20 beads, numba, script) and every other dimension at the
+-1 um pattern and the opening speed:
- script, 5 / 10 / 20 beads x 4 rates x 3 methods x 2 executors (72 runs, 20:06-20:59; no stage steps in these);
- script, 50 / 100 beads x 4 rates x 3 methods x 2 executors (48 runs, with stage steps);
- focus block: 3 methods x (20 / 50 / 100 nm x speed 1 / 0.1) + 3 methods at +-1 um, speed 0.1 (21 runs);
- GUI client, 5-100 beads x 4 rates x 3 methods x 2 executors (120 runs), a fresh LUT per rate.
About 260 runs, 2.5 h of rig time.

## What ran on 2026-11-01 night (results: [results/2026-11-01-bench-matrix.md](../results/2026-11-01-bench-matrix.md))
Script 50 / 100 beads at the four rates (48 runs), the focus block (21 runs), GUI 90 Hz (30, valid to 50 beads), GUI 150 Hz
(30, valid at 5 beads). Not run: GUI 248 / 555 Hz and the 1 um/s focus speed (the sample left focus at 23:19).

## 2026-11-07 (owner asleep; "GPU first, then the bench, holding a reference point")
The GPU kernel changed (decision 0024 note: the one-sided window's zero bins skipped, per-warp radial bins, mapped
input / result arrays; 5 beads 1.83 -> 1.44 ms, 100 beads 2.87 -> 2.25, half ROI 1.37 -> 1.05-1.28), so every GPU
row of 11-01 is superseded by the 11-07 run; the numba rows stand. Blocks (`tools/rig_bench_1107.py`): s90 / s150
/ s248 / s555 at 6, 50, 100 beads; the rate-matched LUT frame counts n150 / n248 / n555; the 1 um/s focus blocks;
the GUI client at the four rates. Results: results/2026-11-07-bench.md - run 02:40-06:30 on the owner's six beads
(four from 04:15: two came loose as the channel dried); the FP32 GPU with `current_v1` dropped nothing up to 200 beads
at 248 Hz / 100 at 555 Hz and matched numba FP64's 2-5 nm reference-corrected step error; numba drops from 200 beads
at 150 / 248 Hz and 50 at 555 Hz; `spline_v1` loses 2-6 x the bead-frames. User report docs/reports/2026-11-07-bench.html.

## After decision 0030 (2026-11-07 ~02:30): two stages instead of the product
- **Stage 0, offline** (`tools/offline_compare.py`, no rig): the replay frames through the reference and every
  variant - index jumps, |dz|, |dxy|, ms. 2026-11-07 (1250 frames x 5 beads): the FP32 kernel against numba FP64 -
  0 index jumps, z within 0.002 nm (current_v1, phase_spline_v1) / 0.13 nm (spline_v1: its golden section on an
  FP32 SSD), xy within 2e-6 px; `spline_v1` differs from `current_v1` by 7 nm median / 119 nm p99 (another
  estimator: the piezo staircase decides which is right), `phase_spline_v1` by 0.9 nm / 8 nm.
- **Stage 1, the standard condition** (block m90: 90 Hz, 20 beads): every method version x numba / gpu / gpu64.
- **Stage 2, the survivors over rate x bead count x ROI** (s90 / s150 / s248 at 6-200 beads, s555 at 5-100; numba
  and the FP32 GPU): the zero-drop boundary table; the rate-matched LUT frame counts; the 1 um/s focus blocks;
  the GUI client at the four rates. Runner `tools/rig_bench_1107.py`; results/2026-11-07-bench.md; the user
  report `docs/reports/2026-11-07-bench.html` (`tools/bench_report_html.py`).
- **Not built, measured instead**: the double-buffered (two-stream) frame path. The FP32 kernel is 0.84-0.90 ms
  per frame in the half ROI at 1-40 beads and 1.1-1.5 ms full frame at 5-200 beads (offline), inside every
  camera rate's budget (555 Hz: 1.8 ms; 248 Hz: 4 ms); the copy it would hide is 0.17 / 0.39 ms. It costs a
  frame of latency; to revisit if a faster camera or a larger ROI needs it.
- **Deferred**: CPU `spline` / `phase_spline` improvements wait for the piezo staircase's verdict (stage 1 / 2),
  which is the only ground truth offline comparison cannot give; the next versions are `spline_v2` etc.

## Open cells (for the full bench later)
- **bandpass against a ceiling bead's pattern** (owner 2026-11-03: a bead that flew to the ceiling lays a wide
  interference pattern over the beads below; LabVIEW mostly ends in bead loss there): tracking noise, z bias and
  lost-frame rate of a bead under a superimposed far-defocus pattern, as a function of the calibration bandpass
  (low / high) and the forget radius, three z methods. Offline first: saved frame windows + a recorded or synthetic
  defocused pattern added at several amplitudes and offsets, the same kernel as online (rig_fair_compare's offline
  path); then on a real ceiling-bead frame when one is recorded. Output: the bandpass that keeps the bead tracked
  at the largest overlap, and the overlap at which each setting loses it. Owner: the channel is 0.2 mm deep, so a
  ceiling bead is ~200 um out of focus (its pattern is wider than the field: at the window scale a slow background,
  the easy case) while a tethered bead moves 1-2 um; the dangerous band is beads a few to tens of um up, whose
  pattern is window-sized. So the disturber's height is a dimension (5, 20, 50, 200 um or as far as the focus
  drive reaches), its pattern recorded by defocusing a reference bead by that much. The tracked bead's place in
  that pattern is the other dimension (owner): at the pattern's centre the overlap is symmetric about the bead and
  biases z only (the profile lifts as a whole, the LUT match slides); where a fringe crosses the window it pulls xy
  and breaks the symmetry (the lost case); outside, nothing. Offsets: centre, mid, fringe crossing, outside; measure
  the xy bias with the z bias and the noise.
- calibration frame count at 20 beads (11-07 measured 17 / 28 / 62 frames per slice at 3-4 beads: no visible gain; the
  expected 30 % noise fall at the fast rates did not show at that bead count);
- GUI at 100 beads (11-07 ran the GUI client at the four rates with 4 / 50 beads);
- speed 1/10 and the 20 / 50 / 100 nm steps at the other rates, bead counts and under the GUI (11-07: 90 Hz, 4 beads,
  numba and the GPU);
- stage xy steps for the 72 early script runs of 11-01 (they had focus + magnet only; every 11-07 run has them);
- the 5 um stage step's hold window: it still contains the move (per-bead std ~1 um, hundreds of lost frames), which
  is the 0.4-2.3 um in the stage max columns; a longer settle in `rig_accuracy` before that hold, then re-read 11-07;
- a second sample / day (11-01 and 11-07 are each one channel drying overnight; 11-07 lost two of six beads, one of
  them tether-like from the start: 0.7-0.9 um with the magnet);
- the tethered-bead force ramp (0030; the owner's bead 3 gave an accidental reading on 11-07, not a ramp);
- the full 1440-run product if the owner still wants it after the reduced one is read.
