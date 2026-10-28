# 0024 — Three Z estimators kept as swappable slots, on numba and on CUDA; the default stays the current method

**Decided:** 2026-10-29 (owner, in chat): "3가지 방법 전부 구현해두고, GPU로도 구현해두자"

## Background
The 2026-10-28/29 benchmarks ([results/2026-10-28-track-bench.md](../results/2026-10-28-track-bench.md)) on the
reference-bead z-scan: the current method's z error between the 100 nm slices (7.7 nm) comes from the 5-point
quadratic root of the phase difference, not from the phase criterion. A continuous LUT removes it either way:
`spline` (Catmull-Rom LUT, sum of squared differences) 4.9 nm / 4.47 nm noise, `phase_spline` (the same LUT with the
current phase criterion brought to zero by bisection) 4.9 nm / 4.66 nm noise. Fixed beads only; the owner wants the
tethered-bead data before choosing.

## Decision
1. **Three Z methods are implemented and kept**, each in three executors that must agree:
   numpy reference (`track.Z_METHODS`: `current`, `spline`, `phase_spline`), numba CPU (`fast.FastKernel(z_method=)`),
   CUDA (`gpu.GpuKernel` / `gpu.GpuZ`, numba.cuda, no cupy or C). Tests `test_fast.py` and `test_gpu.py` hold them
   together to 1e-9 on the replay frames.
2. **The default stays `current`** (0023 item 4: an alternative becomes the default only when measured not worse
   on every benchmark, including tethered beads and phase 9). `make_kernel(beads, z_method=, gpu=)` selects.
3. **The GPU executor is a working implementation, not yet a faster one**
   ([results/2026-10-29-z-executors.md](../results/2026-10-29-z-executors.md)): the Z stage alone on the GPU costs
   more than the whole numba frame at every bead count measured (5-320 beads), because the per-frame copies and
   launch cost about 2 ms and the estimator runs on one thread per bead. It becomes worth tuning only if the camera
   pipeline (phase 6) shows the CPU over budget; the upgrade path is written in the results note.
4. The existing fused CUDA kernel of MT_LabVIEW (0002, 0003 item 4) is unchanged and unused here.
