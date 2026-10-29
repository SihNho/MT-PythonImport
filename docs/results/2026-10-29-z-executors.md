# Three Z estimators on three executors; the fused CUDA kernel (2026-10-29, offline; decision 0024)

`current` (phase, 5-point quadratic), `spline` (continuous LUT, SSD) and `phase_spline` (continuous LUT, phase = 0)
exist as the numpy reference (`mtpy.track.Z_METHODS`), as numba CPU code (`mtpy.fast.FastKernel(z_method=)`) and as
CUDA code (`mtpy.gpu.GpuKernel`, numba.cuda). Replay frames of the 2026-09-06 fixture, 5 beads, LabVIEW's own LUT
(60 slices, 37 points):

| executor pair | current | spline | phase_spline |
|---|---|---|---|
| numba vs numpy reference, max z diff (um) | 8.9e-16 | 0 | 0 |
| CUDA vs numba, max diff in xyz (px / um) | 5.7e-14 | 5.7e-14 | 5.7e-14 |

numba.cuda 0.68 has no two-argument `min` / `max` and `math.floor` returns a float there; `gpu.py` works around both.

## The fused kernel (owner 2026-10-29: "GPU 쓸거면 XYZ 전부 GPU에서 처리 해야함")

The first CUDA version (same day, earlier) ran only the Z stage on the GPU and took the radial profile from the CPU;
it was slower than numba at every bead count (about 2 ms of copies and launches per frame, estimator serial on one
thread). It is replaced by one kernel per frame, one thread block per bead, that does every stage:
cross profiles (SGL sums as the VI), the three-pass parabola centre on direct DFTs (twiddle table in shared memory),
the radial profile (the VI's pixel set, float64 atomics into the radius bins, then the SGL rounding), the band-passed
mirrored profile, the SSD to every LUT slice (one thread per slice) and the estimator with every sum over the profile
reduced across the block (`_block_sum`), so the 30 golden-section / bisection steps cost a reduction each instead of a
37-point loop on one thread. Host side: pinned staging buffers, one stream, one synchronisation per frame.

### Where a block's time goes (30 beads = one wave on the 30 SMs, cuda events, `spline`)

| stage | ms | note |
|---|---|---|
| cross profiles + prep | 0.02 | |
| forward DFT (2 x 120) | 0.04 | |
| three parabola passes (3 IDFT + 2 shifts) | 0.28 | 3 x 240 x 120 complex MACs in float64 |
| radial profile | 0.43 | 0.26 of it the shared-memory float64 atomics (measured by replacing them) |
| band-pass DFT + IDFT, SSD per slice, argmin | 0.05 | |
| estimator (current / spline / phase_spline) | 0.03 / 0.06 / 0.17 | was the whole bottleneck before the block reduction |
| **whole block** | **0.86** | |

Host side per frame: pinned copy of the 1.3 MB frame 0.08 ms, DMA 0.15 ms, and about 0.15-0.2 ms **per CUDA API
call** under Windows WDDM (two copies, one launch, one copy back, one sync: about 0.7 ms). The frame cannot get
under about 1 ms on this machine whatever the kernel does.

### Whole frame (RTX 2060, 12 CPU threads, p50 per frame, ms)

| beads | numba current / spline / phase_spline | fused GPU current / spline / phase_spline |
|---|---|---|
| 5 | 0.33 / 0.33 / 0.43 | 2.35 / 2.36 / 2.54 |
| 20 | 0.63 / 0.62 / 0.83 | 2.31 / 2.35 / 2.55 |
| 80 | 2.04 / 2.02 / 2.70 | 3.63 / 3.75 / 4.12 |
| 320 | 7.85 / 7.79 / 10.4 | 7.26 / 6.94 / 8.06 |
| 1000 | 23.7 / 23.5 / 32.1 | 17.1 / 17.4 / 21.0 |

### What limits it: float64 on a GeForce

The numbers must match the CPU (and LabVIEW) to rounding, so every stage is float64. A GeForce RTX 2060 executes
float64 at 1/32 of its float32 rate (2 FP64 units per SM, about 0.2 TFLOPS in all); the 12-thread CPU with AVX2 is
about 0.3 TFLOPS float64. The kernel's heavy stages (the DFTs, the radial geometry) sit within 2-3x of that FP64
roofline, so **on this card the GPU can at best tie the CPU**: it loses below about 250 beads (API latency) and wins
by about 30 % at 1000. The estimator itself is no longer the cost; the three Z methods differ by 0.15 ms per wave.

Ways out, none taken here:
- a GPU with full-rate float64 (Tesla / Quadro class) would run this kernel 10-30x faster as it stands;
- float32 anywhere in the chain breaks the identity with LabVIEW's numbers (the owner's acceptance criterion), so it
  is the owner's decision, not an optimisation;
- an FFT instead of the direct DFT (120 = 8 x 15, mixed radix) would cut the three passes by a few times;
- the radial atomics (0.26 ms) could be replaced by a warp-level combine of equal bins.

## Owner's reading (2026-10-29)
CPU for tens of beads, GPU worth it only at hundreds; the GPU executor is kept as a candidate and not developed
further now (decision 0024 item 5). Fusion, pinned memory and the asynchronous stream are already applied; what is
left is the WDDM call latency and the FP64 rate of the card, neither of which code can remove.

## What this means
- `make_kernel(beads, z_method="current", gpu=False)` keeps today's behaviour; `gpu=True` is a complete,
  numerically identical alternative executor for every stage, not a faster one on this machine.
- numba meets the 6 ms budget (150 Hz) up to about 200 beads with any of the three methods; 1 kHz (1 ms) is within
  reach of numba up to about 30 beads and of no executor beyond that on this PC.
- Timing scripts: `tools/bench_speed.py` (numba); the GPU tables came from scratch scripts of this session
  (`gpu_scale2.py`, `gpu_stages.py`, `gpu_host.py`); `tests/test_gpu.py` checks agreement only.
