# Three Z estimators on three executors (2026-10-29, offline; decision 0024)

`current` (phase, 5-point quadratic), `spline` (continuous LUT, SSD) and `phase_spline` (continuous LUT, phase = 0)
now exist as the numpy reference (`mtpy.track.Z_METHODS`), as numba CPU code (`mtpy.fast.FastKernel(z_method=)`) and
as CUDA code (`mtpy.gpu`, numba.cuda, one thread block per bead). Replay frames of the 2026-09-06 fixture, 5 beads,
LabVIEW's own LUT (60 slices, 37 points):

| executor pair | current | spline | phase_spline |
|---|---|---|---|
| numba vs numpy reference, max z diff (um) | 8.9e-16 | 0 | 0 |
| CUDA vs numba, max diff (px / um) | 2.6e-14 | 0 | 0 |

The CUDA band-pass is a direct DFT (the profile has 119 points), the CPU's an FFT; the difference is rounding only.
numba.cuda 0.68 has no two-argument `min` / `max` and `math.floor` returns a float there; `gpu.py` works around both.

## Speed (RTX 2060, 12 CPU threads, p50 per frame; XY + radial always on the CPU)

| beads | method | numba frame (ms) | GPU Z alone (ms) | CPU XY + GPU Z frame (ms) |
|---|---|---|---|---|
| 5 | current / spline / phase_spline | 0.32 / 0.31 / 0.41 | 2.06 / 2.00 / 4.65 | 2.20 / 2.12 / 4.76 |
| 20 | " | 0.62 / 0.60 / 0.82 | 1.70 / 1.70 / 4.50 | 2.16 / 2.08 / 5.04 |
| 80 | " | 2.03 / 2.01 / 2.72 | 2.72 / 3.30 / 8.82 | 4.54 / 5.13 / 10.95 |
| 320 | " | 8.43 / 8.10 / 14.64 | 10.2 / 11.8 / 28.7 | 18.0 / 19.4 / 39.7 |

- **numba meets the 6 ms budget (150 Hz) up to about 200 beads with any of the three methods**; `spline` costs
  nothing over `current`, `phase_spline` about 30 % more (atan2 per element per bisection step).
- **The GPU executor is slower than the CPU at every count.** Two reasons, both structural, neither fixed here:
  about 2 ms per frame of host-device copies, launch and synchronisation (visible at 5 beads, where the kernel does
  almost nothing), and the estimator running on one thread per block (the SSD / phase sums over the 37 profile
  points and the 30 search steps are serial), so 320 blocks keep the GPU mostly idle.
- Upgrade path if phase 6 shows the CPU over budget: move XY and the radial profile to the GPU too (one copy of the
  frame instead of a profile round trip), reduce the per-element sums over the block (warp shuffles), and keep the
  frame on the device between kernels. The fused MT_LabVIEW CUDA kernel did this for the current method and ran
  faster from Python than inside LabVIEW (0002); it cannot swap stages (0003 item 4).

## What this means
- The owner's three Z methods are selectable on both executors with identical numbers; the choice waits for the
  tethered-bead data (`tether` plan, [rig/tethered-calibration-protocol.md](../rig/tethered-calibration-protocol.md)).
- `make_kernel(beads, z_method="current", gpu=False)` keeps today's behaviour; nothing in the pipeline changes.
- Timing scripts: `tools/bench_speed.py` (numba, all methods via `FastKernel(z_method=)`); the GPU scaling table
  came from a scratch script of this session and is reproduced by `tests/test_gpu.py` for agreement only.
