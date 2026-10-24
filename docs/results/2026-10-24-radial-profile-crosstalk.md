# Radial profile stage vs XY->Z crosstalk (2026-10-24)

Owner request 2026-10-24: test whether a different radial-profile stage reduces the XY->Z crosstalk found on
2026-10-22 ([2026-10-22-xy-passes-and-synthetic.md](2026-10-22-xy-passes-and-synthetic.md)). Offline only; no device,
no LabVIEW. Script: `tools/radial_profile_bench.py` (modes `synthetic`, `s2float`, `s2noise`, `replay`); raw summaries:
[2026-10-24-radial-profile/](2026-10-24-radial-profile/). Nothing in `src/mtpy` was changed.

## Short answer
- The two-bin split is the main source of the radial stage's sub-pixel sensitivity. **Pixel-area weighting
  (`area4`) cuts the crosstalk about 4x and QI-style polar resampling at 1/3 px (`polar3`) about 3x**, with no change
  in z noise or z interpolation error. Polar resampling at 1 px (`polar1`) is no better than the current stage.
- **The 6.3 / 7.6 nm figure of 2026-10-22 overstates the crosstalk a real bead sees.** It was measured on noise-free
  images rounded to 8 bits; the rounding pattern then moves with the sub-pixel position and adds its own crosstalk.
  Real images carry 1.66 grey levels of noise, which averages the rounding out. With that noise the current stage's
  systematic crosstalk is about **1.0-1.3 nm sd (p2p of a 5 x 5 grid 3.5-6.5 nm)**; `area4` 0.2-0.3 nm sd.
- On the recorded reference bead (bead 1) nothing changes: frame-to-frame z noise 4.13 nm (current) vs 4.13-4.17 nm
  (variants). That bead barely moves (0.008 px per frame), so crosstalk cannot show there; the noise is camera noise.
- The gain is therefore real but small (about 1 nm sd of systematic z error, relevant for beads that move across
  pixels, i.e. tethered beads). Adopting a variant changes results and is the owner's decision (0003).

## Variants (same signature as `track.radial_current`, swapped in with `dataclasses.replace(T.CURRENT, radial=...)`)
| Name | What it does |
|---|---|
| `current` | The program's stage: each pixel's value goes to the two bins around its centre's radius, linear split. |
| `polar1` | QI-style: rings r = 0, 1, ..., 59 px, angles spaced <= 0.5 px of arc, bilinear interpolation, ring mean. |
| `polar3` | Same with rings every 1/3 px, reduced to the 60 integer bins with the same triangular (two-bin) weights. |
| `area4` | Pixel-area weighting: each pixel split into 4 x 4 sub-samples, each sub-sample's radius split over two bins. |

XY stage and Z stage (`z_phase`, phase interpolation, 60 slices x 100 nm) unchanged.

## Method
- **Images** as on 2026-10-22: rendered from the fixture's `cal002` raw radial profiles (beads 1 and 2), 3 x 3 samples
  per pixel, source profiles pre-compensated at sub-pixel offset (0.3, 0.6) so that the current stage reproduces the
  calibration profile (worst residual 0.075 grey levels; now done for all 60 slices).
- **Fair look-up tables.** The program's LUT was built with the current stage, so each variant gets its own: the 60
  calibration slices are rendered at offset (0.3, 0.6), profiled with the variant, mirrored and prepared with
  `calib.prep_bead` using the bead's own (LOW, HIGH, forget). The current stage with this rendered LUT matches the
  program's LUT to 1e-4 and gives the same numbers, so it is the control. `current_origLUT` (the program's LUT)
  reproduces the 2026-10-22 crosstalk exactly: 6.35 / 7.59 nm.
- S2 crosstalk: slices 15, 30, 45, 20 x 20 sub-pixel grid, noise-free 8-bit images (the 2026-10-22 test). Then two
  checks at slice 30: the same grid without 8-bit rounding (`s2float`), and a 5 x 5 grid with noise sigma 1.66, 100
  images per point, z averaged per point (`s2noise`; `sd_corr` removes the noise left in the means, whose standard
  error is about 0.4 nm).
- S3 interpolation: slice 3-56 in 0.05-slice steps at the LUT offset (0.3, 0.6), and in 0.1-slice steps at (0.8, 0.1);
  profiles between slices are the linear blend of the two neighbours (a model).
- S4 noise: slice 30, sigma 1.66, 200 images at offsets 0, 0.25, 0.5 px; the same noisy images for every variant.
- Replay: bead 1 of the recorded fixture (all 10,044 image files = the 10,043 tracked frames plus the last file,
  `img11825`, which is not in the LabVIEW trace), each variant with a LUT rendered from cal002's bead-1 profiles.

## Results

**S2 crosstalk, z p2p over sub-pixel positions (nm)**

| Variant | noise-free 8-bit, b1 s15 / s30 / s45 | b2 s15 / s30 / s45 | no rounding, s30 b1 / b2 | with noise, sd b1 / b2 (p2p 5x5) |
|---|---|---|---|---|
| current (program LUT) | 10.8 / 6.3 / 10.2 | 8.0 / 7.6 / 7.1 | 3.4 / 6.4 | 1.05 / 1.29 (3.6 / 6.5) |
| current (rendered LUT) | same | same | same | same |
| polar1 | 9.0 / 7.5 / 11.5 | 6.8 / 6.7 / 8.2 | 4.6 / 5.1 | 1.11 / 1.37 (4.9 / 5.9) |
| polar3 | 5.2 / 4.7 / 5.5 | 3.8 / 6.5 / 6.1 | 1.0 / 1.1 | 0.41 / 0.40 (2.3 / 2.4) |
| area4 | 5.8 / 3.8 / 6.4 | 3.8 / 6.0 / 5.3 | 0.5 / 0.7 | 0.21 / 0.32 (1.7 / 1.9) |

The p2p of the noisy 5 x 5 grid includes about 1.5-2 nm from the remaining noise of the means; the `sd` column is
the clean measure. The noise-free 8-bit column is mostly the rounding pattern for `polar3` and `area4`.

**S3 interpolation, z rms (nm)** (b1 / b2 at the LUT offset; b1 / b2 at (0.8, 0.1))

| current | polar1 | polar3 | area4 |
|---|---|---|---|
| 1.98 / 2.36; 2.23 / 2.36 | 1.97 / 2.36; 2.34 / 2.34 | 2.01 / 2.42; 2.22 / 2.81 | 2.00 / 2.39; 1.87 / 2.25 |

Worst single error 6-10 nm for all. The interpolation error does not come from the radial stage.

**S4 noise, z sd (nm), sigma 1.66, mean over 3 offsets:** current 3.67 (b1) / 4.35 (b2); polar1 3.66 / 4.34;
polar3 3.70 / 4.39; area4 3.69 / 4.37. The mean z of the 200 images at offsets 0 / 0.25 / 0.5 spreads 1.7 / 6.4 nm
(b1 / b2) for current, 0.4 / 0.7 for polar3, 0.5 / 0.7 for area4 (the same crosstalk seen another way; each mean
has about 0.3 nm standard error).

**Time per call (numpy, this PC):**

| | current | polar1 | polar3 | area4 |
|---|---|---|---|---|
| radial stage | 0.5 ms | 1.1 ms | 3.9 ms | 13.9 ms |
| whole bead | 1.5 ms | 2.2 ms | 5.1 ms | 14.7 ms |

`area4` is slow in numpy because it builds 240 000 sub-sample radii per call; a numba loop (as in `fast.py`) should
bring it near the current stage's cost, since the work is the same loop with 16 times more points. Not measured.

**Replay, recorded bead 1 (reference bead), 10,044 image files (see Method)**

| Variant | frame-to-frame z | z vs program, mean / rms about mean |
|---|---|---|
| current (program LUT) | 4.13 nm | - |
| current (rendered LUT) | 4.13 nm | 0.0 / 0.00002 nm |
| polar1 | 4.13 nm | -0.8 / 0.57 nm |
| polar3 | 4.17 nm | -0.7 / 0.70 nm |
| area4 | 4.15 nm | -0.4 / 0.61 nm |

The variants' LUTs are rendered from bead 1's recorded profiles, not built from calibration images (the fixture keeps
only the profiles, computed with the current stage). For a stuck bead this is enough to compare noise; it is not a
test of accuracy on real images.

## What adopting a variant would require
1. Owner decision (0003): results change (here by 0.4-0.8 nm on bead 1; more on moving beads).
2. A new calibration: the LUT must be built with the same radial stage from real calibration images, so `.cal` files
   made by LabVIEW cannot be reused for the new stage (they store current-stage profiles only).
3. A numba version of `area4` (or `polar3`) and its speed check in the 90 Hz loop.
4. A rig check: a slow lateral scan (or XY piezo steps) of a stuck reference bead, comparing z with the current stage.

## Limits
- Synthetic beads are round, on a flat background, Gaussian noise; the rendering itself uses 3 x 3 samples per pixel,
  so `area4` (4 x 4 sub-samples) is close to the model that made the images and may look better here than on real
  images. `polar3` does not share that model and also improved 3x.
- Each LUT was built at one sub-pixel offset; the real calibration was recorded at one unknown offset too.
- Between-slice profiles are a linear blend (S3).
- The noisy crosstalk check uses a 5 x 5 grid and 100 images per point; its sd has roughly +-0.1 nm uncertainty.
- One recording, one optical setup (50x, binning 2, nominal 200 nm/px), two calibration profiles.
