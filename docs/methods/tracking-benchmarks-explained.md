# How the tracker works and what the 2026-10 benchmarks showed

Written 2026-10-24 at the owner's request ("각 방법이 뭔지, 결과가 뭔지 설명까지 더해서 문서화 한 이후 doc에 넣어줘.
Reference도 같이 있으면 좋겠음"). Korean version: [tracking-benchmarks-explained.ko.md](tracking-benchmarks-explained.ko.md).

This document explains, in plain words, (1) how the current tracking algorithm works, (2) which alternatives were
tested and what each one does, (3) how they were tested, (4) what came out, and (5) what it means. The raw reports are
[2026-10-22-xy-passes-and-synthetic.md](../results/2026-10-22-xy-passes-and-synthetic.md) and
[2026-10-24-radial-profile-crosstalk.md](../results/2026-10-24-radial-profile-crosstalk.md); the literature survey is
[Bead tracking algorithms review](../literature/reports/Bead%20tracking%20algorithms%20review.md). Numbers in [n] point
to the references at the end.

## 1. Summary
- The current tracker (the LabVIEW algorithm, reproduced exactly in Python) is a sound, standard method [1, 6, 7].
- **XY:** its extra "phase-shift" passes halve the pixel bias on synthetic images, but on real data 1 and 3 passes give
  the same noise. The remaining XY bias (≤ 0.015 px, about 3 nm at the nominal 200 nm/px) is below the per-frame noise.
- **Z:** the dominant error is random noise, about **4 nm per frame** on the reference bead. The systematic error from
  the bead's sub-pixel position (XY→Z crosstalk) is about **1.0-1.3 nm sd** with realistic noise. (An earlier figure of
  6-8 nm was an artefact of noise-free test images; corrected.)
- Two alternative radial-profile methods cut that crosstalk 3-4x, to 0.2-0.4 nm, without changing the noise. The gain
  is real but small (about 1 nm). **Recommendation: keep the current method for now**; revisit if an experiment needs
  z accuracy at the 1 nm level.
- Z interpolation between the 100 nm calibration slices showed no slice-periodic error in simulation (rms about 2 nm),
  to be confirmed by a piezo scan on the rig.

## 2. How the current tracker works
For every bead and every frame (decision 0003; code `src/mtpy/track.py`):

1. **Cut a window:** a 144 × 144 px window with 120 px cross profiles, around the bead's previous position.
2. **XY - mirrored profile correlation** [1, 6, 7]. A bead image is round, so it is symmetric about its centre. The
   program averages a horizontal and a vertical band (10 px wide, 120 px long: the cross profiles) through the window into two 1-D profiles, removes
   the baseline and multiplies by a window function. Correlating a profile with its own mirror image (done with an
   FFT) gives a peak whose position is twice the distance from the window centre to the bead centre.
3. **Sub-pixel peak - parabola fit.** A parabola through the 5 points around the peak gives the peak to a fraction of
   a pixel.
4. **Discretisation-bias removal - two more passes.** A parabola fit is slightly biased by where the true peak falls
   between pixels ("pixel bias" or "pixel locking" [2, 20]). The program shifts the spectrum's phase so the peak lands
   on a whole pixel, fits again, and repeats once more: **3 inverse FFTs and 3 parabola fits per axis, 2 phase shifts**.
   (The idea is attributed to Gosse & Croquette [1]; the full paper was not read.)
5. **Radial profile I(r).** Around the new centre, the average brightness at each radius r = 0…59 px. Each pixel's
   value is shared between the two radius bins next to its distance from the centre (the "two-bin split").
6. **Z - compare with the calibration stack.** Before the experiment, a z scan records each bead's radial profile at
   60 heights, 100 nm apart (the look-up table, LUT). The live profile is band-pass filtered into a complex
   ("corkscrew") signal, the closest slice is found by least squares, and the position between slices is refined from
   the **phase differences** to the 5 neighbouring slices with a weighted quadratic fit. z = slice position × 100 nm.

## 3. What was tested and why

### 3.1 XY: number of parabola passes (2026-10-22)
| Variant | What it does |
|---|---|
| 1 pass | Only the first parabola fit (no bias removal). |
| 2 passes | First fit + one phase-shifted refit. |
| 3 passes | First fit + two refits = **the current program** (checked identical: difference 0). |

Why: the 3 passes were not known to the owner; the question was whether they buy anything.

### 3.2 Radial profile stage (2026-10-24)
The 2026-10-22 test found that z changes with the bead's sub-pixel position (XY→Z crosstalk). The radial profile is
where the sub-pixel centre enters z, so four ways of building it were compared:

| Variant | What it does | Origin |
|---|---|---|
| `current` | Each pixel's value goes to the two radius bins around its distance (linear split). | the LabVIEW program |
| `polar1` | Sample the image on circles r = 0, 1, …, 59 px at many angles, with bilinear interpolation between pixels; each ring's mean = the profile value. | quadrant-interpolation style [2, 3] |
| `polar3` | The same with circles every 1/3 px, then reduced to the 60 integer bins with two-bin weights. | the 1/3 px step used by QI [2] |
| `area4` | Each pixel is split into 4 × 4 sub-pixels; each sub-pixel's own distance is used for the two-bin split. Approximates the true pixel area at each radius. | our variant (no specific reference) |

The XY step and the Z step were left unchanged, so only the radial profile differs.

## 4. How it was tested

### 4.1 Recorded data (replay)
The fixture recording (2026-09-06, 50x, 90 Hz, 10,043 tracked frames (10,044 image files; the last file, `img11825`, is not in
the LabVIEW trace), 5 beads) was tracked again with each variant; each
variant feeds its own result to the next frame, as the program does. **Bead 1 is the reference bead** (stuck to the
surface; it does not follow the magnet). Measures:
- **Frame-to-frame noise**: standard deviation of the differences between successive frames, divided by √2. For a
  stuck bead this is the tracking noise.
- **Allan deviation** [17]: how the noise falls when averaging over longer times (τ = 1, 2, 4, … frames); its minimum is
  the best precision reachable before drift takes over.
- **Agreement**: the difference between a variant's output and the current program's.

### 4.2 Synthetic images (known truth)
Real data cannot say where the bead *really* is, so test images with a known position were made:
- **Source**: the fixture's own calibration profiles (`cal002`), drawn as round beads at chosen sub-pixel positions and
  heights, each pixel averaged over 3 × 3 sample points (a camera pixel integrates light), rounded to 8 bits.
- **Pre-compensation**: drawing a profile and measuring it again blurs it, which alone shifted z by 57 nm. The drawn
  profile was therefore adjusted (iteratively) until re-measuring it gives the calibration profile back.
- **Noise model**: Gaussian noise of 1.66 grey levels, measured on the reference bead's region of the real camera. With
  it, the synthetic z noise (3.5-4.5 nm) matches the real reference bead (4.1 nm), so the images are realistic in
  noise.
- **Fair look-up tables** (radial test): the program's LUT was built with the current stage, so each variant got its
  own LUT built the same way with that variant. The current stage with such a rebuilt LUT matches the program's LUT
  to 1e-4, which validates the procedure.

Tests on the synthetic images:
- **S1 pixel bias**: x error while the bead moves through one pixel in 0.05 px steps.
- **S2 XY→Z crosstalk**: z error at one fixed height while the bead moves over a grid of sub-pixel positions.
- **S3 Z interpolation**: z error at heights between calibration slices (a profile between two slices is modelled as
  the linear blend of the two).
- **S4 noise**: spread of x and z over 200 noisy images at the same position.

## 5. Results

### 5.1 XY passes (2026-10-22)
| | 1 pass | 2 passes | 3 passes (current) |
|---|---|---|---|
| Real reference bead, x noise per frame | 0.0082 px | 0.0085 px | 0.0085 px |
| Real reference bead, z noise per frame | 4.13 nm | 4.13 nm | 4.13 nm |
| Synthetic pixel bias, x p2p (profile 1 / 2) | 0.016 / 0.017 px | 0.009 / 0.014 px | 0.008 / 0.015 px |

The second pass halves the bias for one profile; the third adds nothing. On real data the difference is invisible.
1 vs 3 passes differ by 0.004 px rms (about 1 nm).

### 5.2 Radial profile (2026-10-24)
| | current | polar1 | polar3 | area4 |
|---|---|---|---|---|
| XY→Z crosstalk, realistic noise, sd (profile 1 / 2) | 1.05 / 1.29 nm | 1.11 / 1.37 nm | **0.41 / 0.40 nm** | **0.21 / 0.32 nm** |
| Same without 8-bit rounding, p2p | 3.4 / 6.4 nm | 4.6 / 5.1 nm | 1.0 / 1.1 nm | 0.5 / 0.7 nm |
| Z interpolation rms | 2.0-2.4 nm | same | same | same |
| Z noise per image | 3.7 / 4.4 nm | same | same | same |
| Real reference bead, z noise per frame | 4.13 nm | 4.13 nm | 4.17 nm | 4.15 nm |
| Time per bead (numpy, not optimised) | 1.5 ms | 2.2 ms | 5.1 ms | 14.7 ms |

**Correction of an earlier figure.** The 2026-10-22 report gave the crosstalk as 6.3 / 7.6 nm peak-to-peak. That was
measured on noise-free 8-bit images, where the rounding pattern itself moves with the bead and adds crosstalk. Real
images carry noise that averages the rounding out; with it the current method's crosstalk is about 1.0-1.3 nm sd.

### 5.3 Overall error budget of z (current method, this rig)
| Source | Size | Kind |
|---|---|---|
| Camera noise | ≈ 4 nm per frame | random; falls with averaging (Allan minimum ≈ 2.4 nm at 89 ms) |
| XY→Z crosstalk | ≈ 1.0-1.3 nm sd | systematic, depends on the sub-pixel position (moving beads) |
| Interpolation between 100 nm slices | ≈ 2 nm rms (model) | systematic, depends on height; to be checked on the rig |
| Drift | grows with time (0.21 µm over 112 s on the reference bead in the fixture) | removed with the reference bead |

## 6. What it means
- **XY:** nothing to change. QI [2, 3] would matter mainly for robustness (neighbours, defocus), not for precision here.
- **Z:** the radial-profile alternatives remove most of the crosstalk but the gain (about 1 nm) is small next to the
  4 nm noise. Adopting one would require: the owner's decision (results change, decision 0003); a **new calibration**
  built with the new method (LabVIEW `.cal` files hold current-method profiles only); a numba version and a speed check;
  and a rig check with a stuck bead moved sideways. Recommendation: **keep the current method**; `polar3` is the
  candidate if 1 nm z accuracy becomes important.
- **Slice spacing (100 nm):** the literature uses 20-25 nm in some setups [5, 8] and 100 nm in others [6]; with phase
  interpolation no slice-periodic error appeared in simulation. A slow piezo scan of a stuck bead on the rig would
  settle it before any change.

## 6a. Planned rig test (later): exposure time × tracking method
Owner 2026-10-24: "IR camera acquisition 시간(frame은 고정하더라도) 조절할 수 있는걸로 알고 있음. 지금은 말고 나중에 실제 비드
트래킹 노이즈 한번 비교하면 좋겠음. (Reference bead, magnetic bead 둘 다) 방법론도 마찬가지로". Not started.
- **Variable:** JAI exposure time at a fixed frame rate (e.g. 1, 2, 5, 10 ms; exposure must stay below the frame period).
- **Beads:** the reference bead (pure tracking noise) and tethered magnetic beads (real motion; motion blur matters).
- **Methods:** current, `polar3`, `area4` (and any later candidate), all run offline on the same recordings, so rig time
  scales only with the number of exposure settings.
- **Light level:** two series, (a) illumination unchanged (shorter exposure = fewer photons) and (b) mean image
  brightness kept constant with illumination or gain, to separate "less blur" from "fewer photons".
- **Measures:** frame-to-frame noise and Allan deviation [17] (reference bead, raw and drift-corrected); for tethered
  beads the x / y variance against the exposure-time correction of Wong & Halvorsen [21] (this also affects force
  calibration from fluctuations).
- **Design:** same field and beads; exposure settings in alternating order (A-B-B-A) to cancel drift; rig rules apply
  (assembled state, lock, camera only unless a force is needed).

## 7. Limits
- One recording and one optical setup (50x, binning 2, nominal 200 nm/px; pixel size not yet measured).
- Synthetic beads are perfectly round on a flat background with Gaussian noise; no neighbours, no illumination
  gradient.
- The images are drawn with 3 × 3 samples per pixel, which is close to `area4`'s own model and may favour it; `polar3`
  does not share that model and also improved about 3x.
- Each LUT was built at one sub-pixel offset; profiles between slices are a linear blend (a model).
- The reference bead hardly moves, so the replay compares noise, not crosstalk.

## References
1. Gosse C, Croquette V. Magnetic tweezers: micromanipulation and force measurement at the molecular level. Biophys J 82:3314-3329 (2002). https://doi.org/10.1016/S0006-3495(02)75672-5 (abstract only read)
2. van Loenhout MTJ, Kerssemakers JWJ, De Vlaminck I, Dekker C. Non-bias-limited tracking of spherical particles, enabling nanometer resolution at low magnification. Biophys J 102:2362-2371 (2012). https://doi.org/10.1016/j.bpj.2012.03.073
3. Cnossen JP, Dulin D, Dekker NH. An optimized software framework for real-time, high-throughput tracking of spherical beads. Rev Sci Instrum 85:103712 (2014). https://doi.org/10.1063/1.4898178
4. Brouwer TB, Hermans N, van Noort J. Multiplexed nanometric 3D tracking of microbeads using an FFT-phasor algorithm. Biophys J 118:2245-2257 (2020). https://doi.org/10.1016/j.bpj.2020.01.015
5. Kovari DT, Dunlap D, Weeks ER, Finzi L. Model-free 3D localization with precision estimates for brightfield-imaged particles. Opt Express 27:29875-29895 (2019). https://doi.org/10.1364/OE.27.029875
6. Lansdorp BM, Tabrizi SJ, Dittmore A, Saleh OA. A high-speed magnetic tweezer beyond 10,000 frames per second. Rev Sci Instrum 84:044301 (2013). https://doi.org/10.1063/1.4802678
7. Ribeck N, Saleh OA. Multiplexed single-molecule measurements with magnetic tweezers. Rev Sci Instrum 79:094301 (2008). https://doi.org/10.1063/1.2981687
8. Huhle A et al. Camera-based three-dimensional real-time particle tracking at kHz rates and Ångström accuracy. Nat Commun 6:5885 (2015). https://doi.org/10.1038/ncomms6885
9. Dulin D et al. High spatiotemporal-resolution magnetic tweezers: calibration and applications for DNA dynamics. Biophys J 109:2113-2125 (2015). https://doi.org/10.1016/j.bpj.2015.10.018
10. Parthasarathy R. Rapid, accurate particle tracking by calculation of radial symmetry centers. Nat Methods 9:724-726 (2012). https://doi.org/10.1038/nmeth.2071
17. Lansdorp BM, Saleh OA. Power spectrum and Allan variance methods for calibrating single-molecule video-tracking instruments. Rev Sci Instrum 83:025115 (2012). https://pmc.ncbi.nlm.nih.gov/articles/PMC3306435
20. Burov S et al. Single-pixel interior filling function (SPIFF) for pixel-locking correction. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5707392/
21. Wong WP, Halvorsen K. The effect of integration time on fluctuation measurements: calibrating an optical trap in the presence of motion blur. Opt Express 14:12517 (2006). https://arxiv.org/abs/physics/0607156

Numbering follows the literature survey's list. Project sources: decision 0003; `tools/xy_passes_bench.py`;
`tools/radial_profile_bench.py`; [rig-facts.md](../rig-facts.md) (optics, reference bead).
