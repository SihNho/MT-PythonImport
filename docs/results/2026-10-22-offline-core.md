# Phase 3 — offline core: results (2026-10-22)

Checks for the phase 3 completion criterion in [plan.md](../plan.md): the tracking matches LabVIEW on recorded frames
within the decision-0004 tolerance, and it meets the 150 Hz budget (6 ms per frame).

## Input
- Recorded fixture: `G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch\test` (5 beads, 10 043
  frames, 1280 x 1024, 8-bit), with its `cal002` and `tra002-000`.
- LabVIEW reference: the kernel output per frame recorded by MT_LabVIEW (`fixture_compare_results.jsonl`) and the
  calibration cluster LabVIEW handed its kernel (`harness_inputs.npz`). Hashes in [third_party/MANIFEST](../../third_party/MANIFEST).
- Environment: Python 3.10.9, NumPy 2.2.6, numba 0.68.0, rocket-fft 0.4.1; the rig PC (12 logical cores).

## 1. Tracking vs LabVIEW (`tests/test_track_replay.py`, `tests/test_fast.py`)
Tolerance (decision 0004): |dx|, |dy| < 1e-6 px, |dz| < 1e-4 um.

| Check | Bead-frames | Worst x / y (px) | Worst z (um) | Result |
|---|---|---|---|---|
| Reference port, every 20th frame | 2 505 | 3.8e-7 / 1.9e-7 | 1.3e-5 | pass |
| Reference port, all 10 043 frames | 50 137 | 4.8e-7 / 4.5e-7 | 1.3e-5 | pass (1 known slice flip, below) |
| numba executor vs reference port (every 97th frame) | 520 | 2.3e-13 | 8.9e-16 | pass |
| numba executor vs LabVIEW (same frames) | 520 | 4.8e-7 / 1.6e-7 | 3.5e-6 | pass |
| Frame-to-frame state (own output fed back), frames 0–299 and the last 60 | 1 800 | within tolerance on good beads | | pass |

Slice index and the bead-good flag agree with LabVIEW on every compared bead-frame, except the two items below.

**Known differences (for the owner to decide):**
1. **Frame 1937, bead 5: a near tie in the calibration-slice fit.** The SSD of slices 25 and 26 differs by only 3e-5
   (relative). LabVIEW picks 26 and the port picks 25, so z differs by 4.7e-3 um on that one bead-frame. The cause is
   the radial profile's single-precision rounding order in LabVIEW, which is not emulated (accepted at ~1e-4 z on
   2026-09-07). An exact fix needs that order read from the VI. MT_LabVIEW has known about this frame since 2026-09-07.
2. **Beads flagged bad (defocused, z at the top of the stack, 5.9 um) at the end of the recording:** x, y differ by up to
   3.1e-5 px. The correlation peak is almost flat (the 5 fitted points are within 0.5 % of each other), so the
   parabola fit amplifies rounding. z is exact (the stack-edge rule `index + 2 >= S -> z = index` reproduces 5.9) and
   the bad flags and the -1 pattern match exactly. The test holds these beads to 1e-4 px.

Edge rules taken from MT_LabVIEW's CUDA v3 kernel and confirmed here by the recording: the neighbourhood start is
clamped at slice 0; at the upper stack edge z = slice index; bead-good bounds z in [2, S - 3] slices and x, y at least
h = 72 px from the image border.

## 2. Speed (`tools/bench_speed.py`, 1 000 recorded frames)
Tracking only (no acquisition or saving). The 5 recorded beads are repeated to make N beads. Per-frame time in ms:

| Beads | 1 thread p50 / p99 / max | 4 threads p50 / p99 / max | 12 threads p50 / p99 / max |
|---|---|---|---|
| 5 | 0.85 / 1.07 / 1.37 | 0.36 / 0.59 / 0.80 | 0.32 / 0.56 / 1.55 |
| 10 | 1.66 / 2.55 / 2.86 | 0.53 / 0.88 / 1.04 | 0.32 / 0.73 / 1.16 |
| 20 | 3.28 / 4.26 / 5.13 | 1.29 / 1.57 / 1.66 | 0.66 / 1.21 / 1.64 |
| 40 | 6.52 / 8.34 / 9.89 | 2.37 / 3.54 / 9.84 | 1.59 / 2.59 / 4.30 |
| 80 | 13.37 / 18.88 / 44.91 | 3.80 / 5.81 / 6.60 | 3.18 / 4.02 / 4.60 |

For comparison, the plain NumPy reference port takes about 1.9 ms per bead (5 beads: about 9.6 ms per frame).

**Result:** with 12 threads, up to 80 beads stay under 6 ms even in the worst frame. The benchmark ran while another
replay test was using the CPU, so these numbers are conservative. Limits of this check: tracking only, so acquisition
and saving are not loaded at the same time (phase 5 / 6), and the 5 beads are repeated rather than 80 different beads.

## Not covered yet
- The calibration cluster (cosine band-pass, amplitudes, corkscrews) is taken from LabVIEW's own capture. Building it
  from a `.cal` file is phase 4.
- The MATLAB readers (`matlab/read_tra.m`, `read_cal.m`) have not been run: MATLAB is not installed on the rig PC.
- A start position closer than h = 72 px to the image border makes the sub-image smaller than the kernel expects. The
  bounds flag normally stops this one frame earlier; what LabVIEW does if a bead jumps there in one frame is unknown.
