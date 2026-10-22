# Current tracker: what the extra XY passes buy, pixel bias, XY-Z crosstalk, Z interpolation (2026-10-22)

Owner request 2026-10-22: "A와 B부터" (A = bias and Z linearity of the current method on synthetic images, B = 1 vs 2
vs 3 parabola passes on recorded frames). Offline only; no device opened. Script: `tools/xy_passes_bench.py`;
raw summaries: [2026-10-22-xy-passes/](2026-10-22-xy-passes/). Background: the
[literature survey](../literature/reports/Bead%20tracking%20algorithms%20review.md) recommended measuring these before
porting any alternative.

## Method
- **Variants of the XY step** (decision 0003): `passes=1` result = P1; `passes=2` adds the first phase-shifted pass;
  `passes=3` adds the second = the current method. Check: `passes=3` equals `track.find_avg_profile_center` exactly
  (difference 0 on frame 4, all beads), and on all 10 043 recorded frames it matches LabVIEW's `.tra` within
  4.2e-6 px; z within 4.7e-3 µm (the known frame-1937 slice tie only).
- **B, recorded data:** fixture `20260906 ... test` (5 beads, 90 Hz, 50x; bead 1 = reference bead,
  [rig-facts.md](../rig-facts.md)). Each variant feeds its own output to the next frame, like the program.
- **A, synthetic images:** each bead image is rendered from the fixture's own raw calibration profile (`cal002`
  stack; its prepared form equals the tracker's look-up table to 5e-14). Rendering then re-binning blurs a profile
  (a 57 nm z offset if ignored), so the source profile is pre-compensated at sub-pixel offset (0.3, 0.6) until
  re-binning reproduces the calibration profile (worst residual 0.075 grey levels). 3 x 3 samples per pixel, 8-bit
  rounding. Profiles 1 (reference bead) and 2 (tethered bead).
  - S1/S2: slice 30, sub-pixel offsets 0-0.95 px in x and y (20 x 20), no noise.
  - S3: z from slice 3 to 56 in 0.05-slice (5 nm) steps at offset (0.3, 0.6). **Model assumption:** a profile between
    two slices is the linear blend of the two; real profiles between slices are not measured.
  - S4: noise sigma 1.66 grey levels (measured on the reference bead's patch over 36 frames), 200 images per point.

## Results

**1. The extra passes change almost nothing on real data.**

| Bead (recorded) | frame-to-frame x, 1 / 3 passes | frame-to-frame z, 1 / 3 passes | 1 vs 3 passes, rms difference |
|---|---|---|---|
| 1 (reference) | 0.0082 / 0.0085 px | 4.13 / 4.13 nm | 0.0037 px x, 0.36 nm z |
| 2-4 (tethered) | 0.105-0.109 px (same for all variants) | 12.1-12.9 nm (same) | 0.004-0.005 px, 0.4-0.6 nm |

Allan deviation of the reference bead is the same for all variants: minimum about 0.0038 px in x and 2.4 nm in z at
τ = 8 frames (89 ms), rising after that (drift).

**2. Pixel bias is small (synthetic, no noise).** Peak-to-peak x error over sub-pixel positions:

| Profile | 1 pass | 2 passes | 3 passes |
|---|---|---|---|
| bead 1 | 0.016 px | 0.009 px | 0.008 px |
| bead 2 | 0.017 px | 0.014 px | 0.015 px |

The second pass halves the bias for one profile; the third adds nothing. At the nominal 200 nm/px this is about 3 nm
→ 2-3 nm, below the per-frame noise (0.0085 px ≈ 1.7 nm is the reference bead's frame-to-frame noise; the bias is a
systematic error, the noise is random).

**3. XY→Z crosstalk is the largest systematic error found.** At one fixed height, moving the bead within one pixel
changes z by **6.3 nm (bead 1) and 7.6 nm (bead 2) peak-to-peak**, the same for all XY variants. It comes from the
radial profile depending on the sub-pixel centre. A tethered bead moving 0.1 px per frame carries this into its z.

**4. Z interpolation with 100 nm slices shows no per-slice pattern (under the linear-blend model).** Error averaged by
position within a slice is flat within about 1 nm; overall rms 2.0-2.4 nm, worst 8-10 nm, larger in the middle and
upper part of the range than the lower third. The linear-blend model may favour the current phase interpolation, so
this does not replace a real piezo scan of a stuck bead.

**5. The noise model matches reality.** With sigma 1.66 grey levels the synthetic reference profile gives x sd
0.007-0.009 px and z sd 3.5-4.5 nm; the recorded reference bead gives 0.0085 px and 4.1 nm.

**Not concluded:** sub-pixel histograms of the tethered beads are not flat (max/min bin ratio 1.7-4.4), but successive
positions are strongly correlated and the beads drift with the magnet ramp, so this does not show pixel locking.

## What this means
- **Keep the three passes as they are** (rule: numbers stay identical). They cost little in Python and the second one
  does reduce bias; there is nothing to gain by removing them, and nothing to gain by adding more.
- **Porting quadrant interpolation for XY precision is low priority**: the current XY bias (≤ 0.015 px) is below the
  noise. QI may still matter for robustness (neighbours, defocus), which was not tested here.
- **The next target is the XY→Z crosstalk (6-8 nm).** Candidates: a radial profile less sensitive to the sub-pixel
  centre (QI-style polar resampling with bilinear interpolation), or a look-up table that accounts for the sub-pixel
  position. Each would change results, so each needs its own decision (0003).
- **Z slice step:** no evidence yet that 100 nm is too coarse; confirm with a slow piezo scan of a reference bead on
  the rig before changing the calibration.

## Limits
- One recording, one optical setup (50x, binning 2); pixel size nominal.
- Synthetic beads are perfectly round, on a flat background, with Gaussian noise; no neighbours, no illumination
  gradient, no defocus beyond the stack.
- The pre-compensation is computed at one sub-pixel offset, so part of the crosstalk in S2 may come from that choice;
  the real calibration was also recorded at one (unknown) sub-pixel offset, so the effect is of the same kind.
