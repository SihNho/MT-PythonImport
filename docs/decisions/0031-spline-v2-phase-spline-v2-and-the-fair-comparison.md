# 0031 - `spline_v2` / `phase_spline_v2`: a scale-free correlation and the angle of the sum; the fair comparison from recorded bead windows

**Decided:** 2026-11-07 (owner, after the night's bench: "design v2 and, if possible, bench it at the current
position, the same position reference as the bench"). Follows 0030 item 3 (the CPU methods are improvable:
interpolation order, search range, convergence and fallback, the per-frame tail) and item 4 (a change that alters
the numbers raises the version).

## What the 11-07 data said about the v1 methods
- **`spline_v1` sits 7 nm from the reference on the LabVIEW fixture** (offline_compare: median 7.1 nm, p99 121 nm,
  no index jumps), while `phase_spline_v1` is within 0.9 nm. The sum of squared differences is not scale-free: an
  intensity difference between the live profile and the LUT moves its minimum, the phase criterion ignores it.
- **`spline_v1` loses 2-6 x the bead-frames, all at the LUT's lower edge during the stage steps**: in the 555 Hz
  three-bead run 1520 frames read z in [0, 0.1) um (the search collapsed on slice 0) and each cost the next frame
  (the kernel's not-good -> lost -> restart). `current_v1` reads 163 such frames in its run and reports the rest
  in range: on the same disturbed frames the 5-point quadratic lands somewhere inside the LUT, the bracketed
  search at its lower end. Which of the two is right on those frames needs the same frames through both methods.
- **`phase_spline_v1` is the slowest on numba** (0.41 ms against 0.30-0.31 per frame on the fixture: one atan2 per
  profile element per evaluation, 30 evaluations) and **as noisy as `current_v1` at 555 Hz** (per-hold z std
  58-137 nm against `spline_v1`'s 21-58): the per-element angle wraps at +-pi where the signal is weak, and those
  elements enter the weighted mean as outliers.
- **The fair comparison was still missing**: every 11-07 accuracy row is its own rig run, and the piezo's
  run-to-run variation (2026-11-01: 84 nm rms, the same for every method on the same frames) is larger than the
  differences between the methods. 11-01 showed the way: the bead windows of one run kept by the pipeline's frame
  tap, tracked offline by every method.

## The v2 methods (track.py reference, fast.py numba, gpu.py CUDA; `Z_METHODS` holds five names)
- **`spline_v2`**: the cost is minus the normalised correlation of the live prepped profile with the Catmull-Rom
  interpolated LUT, `-sum(c p) / sqrt(sum(c c))` (p's norm is constant), scale-free; the golden section within
  +-1 slice of the best slice ends when the bracket is under `TOL` = 1e-3 slice (0.1 nm) instead of after 30
  steps. On the GPU its two sums are float64 in every build (0030: mixed precision where a stage needs it): the
  maximum is flat, 1 - O(dz^2), and an FP32 sum of 119 terms placed it 1.1 nm off numba.
- **`phase_spline_v2`**: theta(z) = arg(sum(c_live conj(c_lut(z)))), the angle of the amplitude-weighted sum,
  instead of v1's weighted mean of per-element angles: no per-element wrap, no per-element atan2; the bracket
  widens from +-1 to +-2 slices before the quadratic fallback; bisection to a `TOL` bracket.
- Unchanged: the radial profile, the band, the best-slice search, Catmull-Rom (a higher interpolation order
  cannot be told apart with the piezo as the reference, 11-01), the not-good bounds, `current_v1` (the reference)
  and the v1 methods (aliases of the old names).

## Offline gates (no rig time)
| gate | result |
|---|---|
| numba = numpy reference, CUDA fp64 = numba (tests, 1e-9) | pass, five methods |
| CUDA fp32 against numba (test_gpu, the 0030 limits) | `spline_v2` 0.13 nm class after the float64 sums (1.13 nm before), `phase_spline_v2` under 0.01 nm |
| LabVIEW fixture against `current_v1` numba (offline_compare, 501 frames x 5 beads) | `spline_v2` 1.6 nm median / 15 p99 (v1: 7.1 / 121); `phase_spline_v2` 0.90 / 7.8 (v1: 0.88 / 7.8); 0 index jumps; numba 0.30 / 0.31 ms (v1 spline 0.30, phase_spline 0.41) |
| the 11-01 windows (4086 frames x 4 beads, 90 Hz, the piezo staircase) | slopes within 0.3 % of each other, residual 84-86 nm (the piezo), differential z noise 2.6 (spline v1 / v2), 2.7 (phase_spline v1 / v2), 2.9 nm (current); online `current_v1` = offline to 0.000 nm |

## The bench (tools/rig_bench_v2.py, data `G:\l2s_rig_data\2026-11-07c_<block>`, logs bench_out/v2/matrix)
Per rate (90, 150, 248 Hz full frame; 555 Hz half ROI), the four beads left after the night (three in the ROI),
the LUT at Cal+ (37.4 mm), the drift hold, the 11-07 step sequence (focus +-1 um, stage 1 / 2 / 5 um, magnet
30 / 10 / 0 mm):
- `w<rate>`: one `current_v1` numba run with `WINDOWS=1` (rig_accuracy.Tap: the 208 x 208 px window of every real
  bead on every tracked frame, `windows_<run>.npz`), then `tools/offline_windows.py`: the same frames through the
  five methods on numba and on the FP32 GPU, the accuracy columns from the online run's marks, the not-good /
  lost bead-frames per method on identical frames, ms per frame;
- `v<rate>`: `spline_v2` / `phase_spline_v2` x numba / gpu x 4 (3) and 50 beads: drops, throughput and the
  accuracy columns beside the 11-07 tables.
Results: results/2026-11-07-v2-bench.md.

## Consequences
- `track.Z_METHODS` = current_v1, spline_v1, phase_spline_v1, spline_v2, phase_spline_v2 (kernel method ids 0-4);
  the GUI's Z-method box, `offline_compare.py`, `rig_fair_compare.py` and the bench tools take every name.
- `rig_accuracy.py`: `WINDOWS=1` keeps the windows; `accuracy_of(run)` works on any run-shaped dict (the offline
  tool); the 11-01 `piezo` marks count as focus holds.
- The default stays `current_v1` on the FP32 GPU (0030) until the owner reads the v2 bench.
