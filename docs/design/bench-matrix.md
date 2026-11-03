# The bench matrix (owner 2026-11-01 20:55-21:05) and what has been run

The owner's list of benchmark dimensions for the tracking program on the rig, the measurements per run, the reduced
configuration run on 2026-11-01 night ("run the configuration you recommended, the rest is filled in later when the
bench is done properly") and the cells still open. Tools: `tools/rig_accuracy.py` (script), `tools/gui_rig_isolate.py`
with `STEPS=1 CLIENT=1` (GUI client of the engine process), `tools/rig_bench_matrix.py` (the blocks in order).
Results: [results/2026-11-01-accuracy-fps-roi.md](../results/2026-11-01-accuracy-fps-roi.md) and the matrix page
that follows it.

## Dimensions
| dimension | values | note |
|---|---|---|
| frame rate / ROI | 90, 150, 248 Hz (full frame; 248 = the camera's cap), 555 Hz (640 x 512 at (344, 376): the cap at that ROI) | a LUT per rate, made at that rate (a 90-Hz LUT at 150 Hz read z 0.9 um low) |
| bead count | 5, 10, 20, 50, 100 | copies of the owner's beads (1, 13, 11, 8 of the 15:02 frame); the half ROI holds beads 2-4 only |
| z method | current, spline, phase_spline | |
| executor | numba (CPU), GPU (CUDA) | |
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
- calibration frame count: 10 vs rate-matched n_avg (same light per slice as 10 frames at 90 Hz) at 150 / 248 / 555 Hz,
  20 beads, 3 methods; expected: the per-hold noise falls by up to 30 % at the fast rates, the step error's fixed part more;
- GUI 248 / 555 Hz; GUI 90 Hz at 100 beads and 150 Hz from 10 beads (drift-spoiled); focus speed 1 um/s (4 blocks);
- speed 1/10 and the 20 / 50 / 100 nm steps at the other rates, bead counts, the GPU and under the GUI;
- stage xy steps for the 72 early script runs (they had focus + magnet only);
- a second sample / day (all of tonight is one dry channel with stuck beads, drifting ~15 px/h);
- the full 1440-run product if the owner still wants it after the reduced one is read.
