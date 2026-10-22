# Fair benchmarking of magnetic-tweezers bead trackers: a comparison protocol (simulated + recorded frames)

Researcher notes, 2026-10-22. 17 web tool calls. "Verified" means the claim was read on the cited page during this session
(full text or a tool summary of it). Items marked **[UNVERIFIED]** come from general knowledge or abstracts only and should be
checked before being relied on. Where a page could not be opened (Dulin 2015 BPJ full text, van Loenhout 2012 full text,
Gosse 2002 full text, Cnossen 2014 full text), it is said so.

## Allan deviation / Allan variance: separating tracking noise, Brownian motion and drift; typical floors

### Takeaway
The Allan deviation (AD) of a trace is the standard time-domain tool for MT resolution: on a surface-stuck bead it falls as
1/sqrt(tau) while white tracking noise dominates, then turns up when drift takes over; the minimum is the usable resolution.
Published floors range from ~1 nm (single bead, 100 Hz) down to 0.01-0.1 nm after reference-bead subtraction and long averaging.
For a tethered bead the AD also contains a Brownian bump peaking near tau ~ 1.89 x (drag/stiffness), so tracking-noise
comparisons between algorithms must be done on stuck beads (or on simulated stationary beads), not on tethered ones.

### Cited Findings
- Lansdorp & Saleh 2012 (Rev Sci Instrum 83:025115) introduce power-spectrum and Allan-variance methods to extract drag and
  stiffness from video-tracked traces and state they apply to any video-tracking instrument. — [PMC3306435](https://pmc.ncbi.nlm.nih.gov/articles/PMC3306435)
- Their recommended estimator: fully overlapping AV, octave-sampled bin sizes m = 1, 2, 4, ... up to N/2; shape factor
  eta(m) = N/(2m) - 1; fit with a maximum-likelihood cost because AV estimates are Gamma-distributed (least squares is biased);
  octave sampling cut drag error ~3x versus all-tau AV. — [PMC3306435](https://pmc.ncbi.nlm.nih.gov/articles/PMC3306435)
- Equation 18 (overlapping AV) of the 2012 paper was corrected by an erratum in 2014; implementers should use the corrected form. — [PMC3979167](https://pmc.ncbi.nlm.nih.gov/articles/PMC3979167)
- Harmonic-trap AV regimes: short tau (tau << alpha/kappa) sigma^2 ~ 2kBT tau/(3 alpha) (rising); long tau sigma^2 ~
  2kBT alpha/(kappa^2 tau) (falling); peak at tau_max ~ 1.89 alpha/kappa. The camera shutter acts as a boxcar average that the
  AV definition already matches, so no extra instrument correction is needed (unlike the PSD, which needs aliasing/blur/leakage
  corrections). — [PMC3306435](https://pmc.ncbi.nlm.nih.gov/articles/PMC3306435)
- The 2012 paper itself does not give a noise floor in nm, nor treat tracking noise or drift explicitly. — [PMC3306435](https://pmc.ncbi.nlm.nih.gov/articles/PMC3306435)
- Tweezepy (Morgan & Saleh 2021) adds a white tracking-noise term to the AV model: sigma^2_AV(tau) = thermal term + eps^2 tau_s/tau
  (eps = per-frame Gaussian tracking error, tau_s = sampling time); tracking error is "most apparent at short observation times";
  drift appears as power-law noise at long tau, and the package lets the user set cutoffs to exclude drift-dominated tau; for
  non-modelable parasitic noise it recommends subtracting a reference or band-pass filtering; PSD is better for high-frequency
  coherent noise, AV better for low-frequency drift. — [Tweezepy, PMC8719779](https://pmc.ncbi.nlm.nih.gov/articles/PMC8719779/)
- Ostrofet, Papini & Dulin (2020, Data in Brief): AD defined as half the mean difference of adjacent-interval averages; "The AD
  decreases as 1/sqrt(tau) until it increases at longer tau"; computed as overlapping AD with Python AllanTools 2019.9. — [PMC7103768](https://pmc.ncbi.nlm.nih.gov/articles/PMC7103768)
- Floors reported there: surface-stuck 3 um polystyrene bead, z, no subtraction: AD plateau ~0.07 nm, independent of 58 vs 500 Hz
  and 50x vs 100x; with reference subtraction ~0.01 nm (500 Hz, 100x). — [PMC7103768](https://pmc.ncbi.nlm.nih.gov/articles/PMC7103768)
- Huhle et al. 2015 (Nat Commun 6:5885, CMOS 1280x1024, 2.5 kHz, GPU): fixed 3 um bead pair, raw differential RMS 1.3 A lateral,
  1.8 A axial; lateral AD minimum 0.1-0.2 A between 100 ms and a few s; axial < 0.1 A for tau > 100 ms; single absolute bead AD < 1 A
  at 0.1-1 s; DNA-tethered bead (12 pN) AD minimum ~1 A at 0.1-1 s; 26 beads at 420 Hz "significantly below 1 A" from ~0.1 s;
  3 A steps resolved on fixed beads. — [PMC4338538](https://pmc.ncbi.nlm.nih.gov/articles/PMC4338538)
- Dulin et al. 2015 (Biophys J 109:2113): systematic resolution characterisation across light sources (incoherent vs coherent),
  bead types/sizes and tether lengths; with a coherent laser at 6 kHz, 3 A steps (1 s period) on surface-melted beads and 5 A on
  dsDNA-tethered beads. Full-text AD figures not read. — [VU research portal](https://research.vu.nl/en/publications/high-spatiotemporal-resolution-magnetic-tweezers-calibration-and-)
- London et al. 2025 (bioRxiv, Python MT framework "MagTrack/MagScope"): fixed beads at 100 Hz, 256x256 ROI: ~1 nm from the AD of a
  single track, ~0.1 nm after subtracting a second fixed bead. — [bioRxiv 10.1101/2025.10.31.685671](https://www.biorxiv.org/content/10.1101/2025.10.31.685671v1.full)
- Wong & Halvorsen 2006 (Opt Express 14:12517): finite camera integration time biases (not merely adds noise to) fluctuation
  measurements; they give blur-corrected equipartition/PSD expressions. — [arXiv physics/0607156](https://arxiv.org/abs/physics/0607156)
- te Velthuis et al. 2010 (Biophys J 99:1292) built an MT simulator validated against experiment to give quantitative guidelines
  for spectral force calibration; body text not read here. — [te Velthuis lab page](https://tevelthuislab.scholar.princeton.edu/publications/quantitative-guidelines-force-calibration-through-spectral-analysis)

### Inferences
- Slope reading (AD, i.e. sqrt of AV, on log-log): white per-frame tracking noise -> slope -1/2 (from eps^2 tau_s/tau in Tweezepy
  and the Ostrofet "1/sqrt(tau)" statement); trapped Brownian motion -> +1/2 rising then -1/2 falling with a bump at ~1.89 tau_c.
  **[UNVERIFIED in a fetched source]** standard AV theory: random-walk drift -> +1/2, linear drift -> +1.
- The AD at tau = one frame on a stuck bead approximates the per-frame tracking error eps (plus stage vibration); a tracker
  comparison should report AD(tau_frame) and the AD minimum (value and tau) for x, y, z separately.
- Because AD(tau_frame) on real stuck beads mixes tracking noise with mechanical vibration, two trackers run on the SAME frames
  can be compared directly (vibration is common), but absolute values cannot be compared across labs.
- Floors from 400-6000 Hz instruments are not targets for a 90 Hz, 8-bit, LED system; the relevant comparison is the candidate
  tracker vs the current tracker on identical frames.

### Gaps
- Dulin 2015 full text (reference-bead AD curves, light-source dependence numbers) could not be opened (Augsburg repository refused
  connection).
- No fetched source gives the explicit AD slopes for linear vs random-walk drift (stated above as unverified standard theory).
- te Velthuis 2010 details (blur/aliasing guidelines) not read.

## Reference (surface-stuck) beads for drift subtraction and as a noise floor: practice and pitfalls

### Takeaway
Labs fix polystyrene beads to the surface (e.g. heat-melting) and subtract their trace from each tethered bead; this removes common
drift and stage vibration and is how sub-nm floors are reached, but it does not remove all drift, adds the reference's own tracking
noise, and works less well the farther the reference is.

### Cited Findings
- Ostrofet 2020: 3 um polystyrene references fixed by heating the coverslip ~150 C for 3 min; tethered minus reference position. — [PMC7103768](https://pmc.ncbi.nlm.nih.gov/articles/PMC7103768)
- Pitfalls reported there: drift 0.36-16.65 nm/min across recordings; "Reference bead position subtraction does not completely
  correct for the mechanical drift"; the worst-drifting recordings stayed worst after correction; small correlation of residual AD at
  tau = 180 s with bead-bead distance (0.0009 nm/um); x/y high-frequency piezo noise is removed by subtraction. — [PMC7103768](https://pmc.ncbi.nlm.nih.gov/articles/PMC7103768)
- Huhle 2015 reports every bead as a difference coordinate to a firmly attached reference; ruled out focus drift with feedback; no
  relative drift between 1 um magnetic and 3 um reference fixed beads; for DNA tethers they attribute remaining 5-10 A drift to
  magnetic-bead orientation instability, not focus. — [PMC4338538](https://pmc.ncbi.nlm.nih.gov/articles/PMC4338538)
- Brouwer et al. 2020 (FFT-phasor): averaging several references improves z: sigma_z^2/f converged to 0.2 nm^2/Hz for n = 5 references
  ("2.4 nm accuracy for 30 Hz imaging"); for calibration they averaged 10 beads and low-passed at 1 Hz. — [PMC7202940](https://pmc.ncbi.nlm.nih.gov/articles/PMC7202940/)
- London 2025: fixed-bead AD ~1 nm single track -> ~0.1 nm after subtracting a second fixed bead. — [bioRxiv](https://www.biorxiv.org/content/10.1101/2025.10.31.685671v1.full)

### Inferences
- Subtracting one reference adds its tracking noise: for two independent equal-noise beads the difference has sqrt(2) x per-bead
  noise at short tau (simple variance addition; inference). So per-tracker noise from a stuck-bead PAIR difference = AD_diff / sqrt(2).
- For tracker comparison, a stuck-bead pair is ideal: subtracting removes vibration/drift common to both, leaving (mostly) tracking
  noise, which is exactly the quantity that differs between algorithms.
- Identifying a stuck bead when unknown: the stuck bead should show no Brownian bump in AD, the smallest lateral/axial spread, and
  near-zero AD at tau = 1 frame relative to tethered beads; pairwise difference traces between all bead pairs can confirm which two
  move together. (Inference from the AD regimes above; no source describes a blind identification procedure.)

### Gaps
- No source found with a formal blind test for "which bead is stuck".

## Shot-noise / camera-limited precision bounds; 8-bit quantization and exposure

### Takeaway
Camera tracking of ring patterns is ultimately photon (shot-noise) limited; good trackers (QI on GPU) were reported to reach near
the Cramer-Rao lower bound (CRLB). No fetched source quantifies 8-bit quantization specifically; exposure (motion blur) biases
fluctuation-based quantities and must be held equal between trackers.

### Cited Findings
- Huhle 2015: camera tracking is "severely limited by shot-noise"; the bead image is set to fill about half the pixel well depth;
  per-pixel nonlinear response corrected in software; more pixels per bead improve accuracy and reduce pixelation bias; no explicit
  CRLB formula given. — [PMC4338538](https://pmc.ncbi.nlm.nih.gov/articles/PMC4338538)
- Cnossen, Dulin & Dekker 2014 (Rev Sci Instrum 85:103712): CUDA Quadrant Interpolation tracks hundreds of beads in real time;
  scatter "close to the theoretical optimum defined by the Cramer-Rao Lower Bound"; explores trade-offs between speed, ROI size and
  tracking bias; reports a previously unreported bias along the optical axis; ~1 nm SD for 228 tethered beads at 58 Hz. Abstract
  level only. — [VU research portal](https://research.vu.nl/en/publications/an-optimized-software-framework-for-real-time-high-throughput-tra/)
- Brouwer 2020 simulations: z error rose from 0.05 to 10 nm^2/Hz as Poisson noise increased from 0 to 20 grey units (~1 nm^2/Hz at
  ~3 units); x, y roughly unaffected - z is the noise-sensitive axis. — [PMC7202940](https://pmc.ncbi.nlm.nih.gov/articles/PMC7202940/)
- Motion blur from integration time biases (not only adds noise to) fluctuation measurements. — [Wong & Halvorsen, arXiv physics/0607156](https://arxiv.org/abs/physics/0607156)

### Inferences
- 8-bit images: if the read/shot noise is well above 1 grey level (Brouwer's ~3 grey units "typical"), quantization acts mostly as
  small extra uniform noise (variance 1/12 LSB^2, standard result **[UNVERIFIED in fetched source]**); if illumination is set low
  (few grey levels of modulation in the rings), quantization can create z-staircase/locking. Test by simulating with and without
  rounding to 8 bit.
- A practical CRLB for a given recording can be estimated numerically from the calibration stack: Fisher information for z from the
  derivative of the expected image w.r.t. z (finite differences between adjacent stack slices) divided by the per-pixel variance
  (Poisson + read). **[UNVERIFIED method sketch - no source fetched gives this recipe for MT]**.

### Gaps
- Cnossen 2014 full text (exact CRLB derivation, simulation settings, axial-bias size) not read.
- van Loenhout 2012 (QI paper; bias at low magnification) full text not read.
- No source found quantifying 8-bit vs 12-bit tracking precision in MT.

## Simulating realistic brightfield bead images

### Takeaway
Two routes exist: (1) physics-based Lorenz-Mie holograms (holopy, pylorenzmie) with known x, y, z plus added Poisson noise and
artefacts, as done by Brouwer 2020; (2) empirical images built from a recorded calibration stack with sub-pixel shifts and noise. Route
1 avoids the "tracker evaluated on its own LUT" circularity; route 2 matches the real optics better.

### Cited Findings
- Brouwer 2020 Lorenz-Mie benchmark: 1.0 um bead, a = 0.5 um, n_p = 1.9, n_m = 1.33, lambda = 645 nm; 3600 holograms 150x150 px with
  dx, dy = 0 +/- 5 nm and dz = 12,000 +/- 5 nm (= 120 s at 30 Hz); added Poisson noise, interlacing, light gradients, astigmatism, ROI
  shift (typical: ~3 grey units Poisson, ~15% gradient, ~2% astigmatism, ~5% shift); a LUT comparison used 256 frames over a 4-7 um z
  ramp, Poisson 5 grey units, positions ~N(0, 100 nm), compared as input-minus-output. — [PMC7202940](https://pmc.ncbi.nlm.nih.gov/articles/PMC7202940/)
- holopy computes the hologram as interference of the Mie-scattered field with the unscattered reference; example parameters:
  sphere n = 1.59, r = 0.5 um, center (x, y, z), medium_index 1.33, illum_wavelen 0.660 um, polarization (1, 0), detector_grid of
  100x100 px at 0.1 um spacing; no noise function on that page (noise must be added by the user). — [holopy calc tutorial](https://holopy.readthedocs.io/en/latest/tutorial/calc_tutorial.html)
- pylorenzmie: Python package fitting/generating in-line holograms with a Lorenz-Mie generative model (instrument + sphere + position),
  with normalisation by background or median. — [pylorenzmie docs](https://pylorenzmie.readthedocs.io/)
- London 2025 built an image simulator from pixel size and known bead x, y, z to test "accuracy and speed", without stating a noise
  model. — [bioRxiv](https://www.biorxiv.org/content/10.1101/2025.10.31.685671v1.full)
- te Velthuis 2010 used a simulator of MT bead dynamics (trajectories, not images, as far as the abstract shows) validated against
  experiment. — [te Velthuis lab page](https://tevelthuislab.scholar.princeton.edu/publications/quantitative-guidelines-force-calibration-through-spectral-analysis)

### Inferences
- Lorenz-Mie in-line holography models a coherent plane wave; an LED/brightfield MT image is partially coherent, so Mie images will
  match ring spacing but not exact contrast/envelope; use them for relative tests (bias vs sub-pixel position, crosstalk, noise
  scaling), not for absolute z calibration.
- Empirical route from the 60-slice stack: Fourier/sinc sub-pixel shift of a slice (exact for band-limited images), interpolate in z
  only between neighbouring slices, scale to the recording's grey level, add Poisson (gain-calibrated) + Gaussian read noise, round to
  8 bit. To avoid circularity, build the tracker's LUT from a different set of slices (e.g. even slices) than the test images (odd
  slices), or from a second stack.

### Gaps
- Could not confirm what van Loenhout 2012, Cnossen 2014 or Gosse 2002 used for simulated images (full texts not opened). Their use
  of simulated images is **[UNVERIFIED]**.

## Metrics: pixel-locking bias, XY-Z crosstalk, Z linearity, lost-bead rate, neighbour robustness, runtime

### Takeaway
Use known-truth simulations for bias-type metrics (bias vs sub-pixel position, crosstalk, linearity) and recorded frames for
noise-type metrics (AD on stuck beads, agreement with the current tracker, failure rate), always on identical inputs.

### Cited Findings
- Pixel locking = estimated positions concentrating at favoured sub-pixel locations; test: histogram of the fractional part of
  estimated positions (SPIFF), which should be flat; biases can reach up to half a pixel for small/noisy/crowded particles; SPIFF can
  correct even black-box trackers. — [Burov et al., PMC5707392](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5707392/); [Feng, Goree & Liu, arXiv 1104.3776](https://arxiv.org/pdf/1104.3776)
- QI (van Loenhout 2012) uses the circular symmetry of the diffraction pattern and quadrant radial profiles with bilinear interpolation to
  suppress bias. — [arXiv 1605.03328 description](https://arxiv.org/pdf/1605.03328)
- Cnossen 2014 reports a trade-off between speed, ROI size and bias and an axial (z) bias. — [VU portal](https://research.vu.nl/en/publications/an-optimized-software-framework-for-real-time-high-throughput-tra/)
- Brouwer 2020: z linearity as residual SD of polynomial fit over a 10 um range (< 15 nm); crosstalk only discussed qualitatively;
  runtime: up to 10,000 ROIs/s at 100x100 px; < 3 ms per ROI for 64-128 px ROIs; LUT tracking "several times faster". — [PMC7202940](https://pmc.ncbi.nlm.nih.gov/articles/PMC7202940/)
- London 2025 reports throughput (images/s) vs ROI size (16, 64, 256 px) and batch size on stated CPU/GPU; per-bead runtime not given;
  QC rejected 625/1000 traces in a flow-stretch assay (375 passed). — [bioRxiv](https://www.biorxiv.org/content/10.1101/2025.10.31.685671v1.full)

### Inferences (proposed protocol)
A. Simulated, known truth (Mie and/or stack-based, same noise for all trackers):
  1. Bias map: grid of sub-pixel offsets (e.g. 0-1 px in 0.05 px steps in x and y) x several z; metric = mean(est - true) per offset
     (systematic) and SD (random); report max |bias| and the SPIFF flatness on a random-offset set.
  2. XY->Z and Z->XY crosstalk: shift x at fixed z, record dz/dx (nm per nm); step z at fixed x, y, record dx/dz.
  3. Z linearity: z ramp across the LUT range; residual of est vs true after linear fit; mark range edges where error grows.
  4. Noise scaling: repeat at several photon levels and with/without 8-bit rounding; compare SD with a numerical CRLB.
  5. Neighbours: second bead at decreasing distance (e.g. 1.5-5 diameters); report bias onset distance.
  6. Lost-bead rate: fraction of frames with error > a threshold (e.g. 1 px or 200 nm) or NaN.
B. Recorded frames (identical frames to every tracker):
  1. Per bead, per axis: AD at tau = 1 frame and AD minimum (value, tau); stuck-pair difference / sqrt(2).
  2. Agreement with the current tracker: per-frame difference (mean offset, SD, AD of the difference) - the AD of the difference shows
     whether disagreement is white (noise) or slow (bias/drift handling).
  3. Failure/jump count (frame-to-frame step > threshold), runtime per bead per frame on the stated hardware.
C. Report with confidence intervals (AV is Gamma-distributed; with N frames, octave points ~ log2 N; few points at large tau).

### Gaps
- No single paper found that runs all of these metrics on several MT trackers in one benchmark; Brouwer 2020 compares only LUT vs
  FFT-phasor and explicitly does not report pixel bias or CRLB.

### Applicability note (our recording: 5 beads, 10,043 frames at 90 Hz, 1280x1024 8-bit, 60 x 0.1 um stack, original XY/Z output)
- Length 10,043 / 90 Hz = 111.6 s; overlapping AD usable to tau ~ N/2 ~ 55 s, ~13 octave points (log2 10,043 ~ 13.3), with few
  degrees of freedom above ~10 s - floors near the 0.07 nm (Ostrofet) or sub-A (Huhle) regime are not expected and not needed;
  comparisons should be relative (candidate vs original on the same frames). (Arithmetic plus inference.)
- The stuck bead can be found from the AD shapes (no Brownian bump, lowest short-tau AD) and from pairwise difference traces; if no bead
  is stuck, tracking noise must come from simulations only.
- The 6 um, 0.1 um-step stack supports the empirical simulator with held-out slices (even/odd split) so the tracker under test is not
  scored on its own LUT images; the original program's XY/Z output provides the agreement baseline required by the numerical-acceptance
  rule (same inputs -> same numbers).
