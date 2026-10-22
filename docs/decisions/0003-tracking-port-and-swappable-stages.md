# 0003 — Port the current tracking first; make each stage swappable

**Decided:** 2026-10-21

## The current algorithm
It is a classic Gosse & Croquette (2002) style tracker. The code lineage appears to come from the Saleh lab LabVIEW code.

Per bead, per frame:
1. **Cut a square around the previous position** (cross size 120).
2. **XY:**
   - average a horizontal and a vertical band through the centre into two 1D profiles;
   - remove the baseline and apply a window;
   - autocorrelate each profile with its mirror image via FFT;
   - fit a parabola to the peak;
   - remove the pixel-discretization bias in two more passes: shift the spectrum's phase by the fractional peak
     offset, inverse FFT and fit the parabola again (so per axis: 3 inverse FFTs, 3 parabola fits, 2 phase shifts;
     the original VI's 3-frame stacked sequence). *Corrected 2026-10-22: first written as "three phase-shift
     iterations".*
3. **Radial profile I(r)** around the new XY centre (each pixel split between two radius bins).
4. **Z:**
   - mirror I(r) and apply a cosine band-pass via FFT to get a complex ("corkscrew") signal;
   - pick the closest slice of the bead's calibration stack (least squares; 60 slices of 0.1 µm);
   - refine with a weighted quadratic fit of the phase differences to the 5 neighbouring slices.

**Quirks** of the original that are reproduced exactly:
- some steps are computed in single precision;
- one baseline index reads out of range, which adds a 0;
- LabVIEW rounds half to even;
- -1.0 marks a lost bead.

## Decision
1. **First implement the current algorithm exactly**, starting from the existing NumPy reference, and accept it numerically (decision 0004).
2. **Make each stage a swappable slot with a fixed input/output contract:** XY estimator, radial profile, Z estimator, precision mode, executor (NumPy / numba / CUDA). The combination is chosen in configuration and recorded in each data file.
3. **Compare alternatives one stage at a time against the current method.** Candidates:
   - quadrant interpolation for XY;
   - FFT-phasor for Z;
   - a double-precision clean-up;
   - methods found in a literature survey, e.g. MagTrack/MagScope (bioRxiv 2025).
4. **Compare on the CPU first.** The existing CUDA kernel fuses the whole current algorithm into one launch and cannot swap stages. Only the winning combination is rewritten as a fused CUDA kernel.
5. **Adopt an alternative only if** it is clearly better and nothing else gets worse. Since it changes results, adopting it is a separate recorded decision, with experimental validation.

## How alternatives are compared
| Data | Measures |
|---|---|
| Simulated bead images (known truth) | accuracy and bias, XY–Z crosstalk, pixel-grid bias, behaviour at the ends of the Z range |
| Recorded rig data | precision (reference-bead noise, Allan deviation), lost-bead rate, robustness to neighbours and defocus |
| Both | time per bead, fit in the 150 Hz budget |

## Later notes (not changes to the decision)
- **2026-10-22 literature survey:** [Bead tracking algorithms review](../literature/reports/Bead%20tracking%20algorithms%20review.md)
  (notes in `docs/literature/research_notes/`). It ranks quadrant interpolation first for XY and a better sub-slice
  interpolation on the existing look-up table (smoothing spline + Gauss-Newton, Kovari et al. 2019) first for Z;
  FFT-phasor (Brouwer et al. 2020) is a robustness option; MagTrack is GPL-3.0, so only an outside numeric check.
  Suggested first measurement: pixel bias and Z linearity of the current method, including how much the two extra
  phase-shift passes contribute, before porting anything.
- **Baseline for the recorded data:** bead 1 of the fixture is the reference bead ([rig-facts.md](../rig-facts.md)).
