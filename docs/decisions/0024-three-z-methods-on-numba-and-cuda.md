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
   CUDA (`gpu.GpuKernel`, numba.cuda, no cupy or C). Tests `test_fast.py` and `test_gpu.py` hold them together to
   1e-9 on the replay frames. 2026-11-07 (owner: "improve the GPU code, cut the frame drops"): the per-frame cost
   on the RTX 2060 was 0.85 ms of CUDA calls plus a 0.65 ms kernel at 5 beads; now the kernel's DFT passes stop at
   bin `half` (calib.windows' Hilbert half-window is zero from there, so the dropped terms were exact zeros:
   bit-identical), the radial profile sums into per-warp bins (4x less atomic contention; the per-thread private
   bins tried first were slower at 100 beads), and the per-bead input / result arrays are mapped (two CUDA calls
   fewer). 5 beads 1.83 -> 1.44 ms, 20 beads 1.63 -> 1.30, 100 beads 2.87 -> 2.25, the 555 Hz half ROI 1.37 ->
   1.05-1.28 ms. A mapped (zero-copy) frame was slower (the kernel's scattered reads over PCIe); the frame copy
   (0.39 ms full, ~0.17 half ROI) and numba's launch (0.16 ms) remain.
2. **The default stays `current`** (0023 item 4: an alternative becomes the default only when measured not worse
   on every benchmark, including tethered beads and phase 9). `make_kernel(beads, z_method=, gpu=)` selects.
3. **The GPU executor runs every stage (XY, radial profile, Z) in one fused kernel per frame** (owner, same day:
   "GPU 쓸거면 XYZ 전부 GPU에서 처리 해야함"; the estimator's sums are reduced across the thread block: "그거 병렬화
   진행해야겠고"). The XY algorithm is one (the VI's), implemented once per executor like the Z methods, and the
   tests hold the implementations together. It is numerically complete but not faster on this machine
   ([results/2026-10-29-z-executors.md](../results/2026-10-29-z-executors.md)): float64 on a GeForce (1/32 rate)
   ties the 12-thread CPU at best, loses below about 250 beads to CUDA API latency, wins about 30 % at 1000 beads.
   The default executor stays numba; float32 is not an optimisation but a change of the acceptance criterion, so it
   would need the owner's decision.
4. The existing fused CUDA kernel of MT_LabVIEW (0002, 0003 item 4) is unchanged and unused here.
5. **GPU executor kept as a candidate, not developed further (owner 2026-10-29: "이 부분은 인제스트하고 후보만 두고 있자").**
   Measured on this PC: tens of beads - the CPU wins outright; hundreds of beads - the GPU starts to pay
   (owner: "수 백개 트래킹을 한다면 GPU를 쓰는게 이득이겠고, 수십개 레벨이면 CPU가 압도적"). Kernel fusion, pinned staging and one
   asynchronous stream are already in; the remaining cost is the WDDM per-call latency (about 0.7 ms per frame) and
   float64 on a GeForce (1/32 rate). An in-kernel FFT (numba, length 120) or a C/CUDA kernel (decision 0002 would
   need revising) are the next steps only if a measured case needs the GPU; the executors stay unmixed: a frame is
   tracked XY -> radial -> Z entirely on one processor (owner 2026-10-29).
