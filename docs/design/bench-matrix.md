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

## Open cells (for the full bench later)
- speed 1/10 and the 20 / 50 / 100 nm steps at the other rates, bead counts, the GPU and under the GUI;
- stage xy steps for the 72 early script runs (they had focus + magnet only);
- a second sample / day (all of tonight is one dry channel with stuck beads, drifting ~15 px/h);
- the full 1440-run product if the owner still wants it after the reduced one is read.
