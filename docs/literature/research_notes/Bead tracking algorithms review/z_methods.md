# Axial (Z) position estimators for magnetic-tweezers bead tracking (brightfield diffraction rings)

Research date 2026-10-22. Verification levels used below:
- **[V-full]** read in the full text (PMC/arXiv/PDF text extraction)
- **[V-abs]** abstract or publisher/repository landing page only
- **[UNVERIFIED]** from background knowledge or a search snippet; the primary text was NOT read. Do not cite as fact without checking.

Our setup, for the suitability notes: 60 LUT slices x 0.1 um per bead (6 um range), cross 120 px, radial profile ~60 px, 8-bit CMOS at 90-150 Hz.

---

## Q1. Gosse & Croquette 2002: radial profile, band-pass, calibration stack, phase-based sub-slice interpolation

### Takeaway
The paper is Gosse C, Croquette V, "Magnetic tweezers: micromanipulation and force measurement at the molecular level", Biophys J 82(6):3314-3329 (2002), DOI 10.1016/S0006-3495(02)75672-5. I could NOT get its full text (PMC served only the abstract; the PDF was blocked behind a browser check), so the details of its Z algorithm below are **unverified**. The Croquette lab's later published Fourier-phase-shift localization (Rieu et al., SDI) is verified and shows the same idea: fit a line to the phase difference of Fourier modes against a reference profile and read the shift from the slope.

### Cited Findings
- Bibliographic record, abstract only: electromagnet tweezers with digital feedback; trap stiffness ~1e-7 N/m; forces 50 fN-20 pN; force calibration from viscous drag or Brownian fluctuations. The abstract says nothing about the Z algorithm. [V-abs] — [PubMed/PMC1302119, DOI 10.1016/S0006-3495(02)75672-5](https://doi.org/10.1016/S0006-3495(02)75672-5)
- A US patent from this line of work cites Gosse & Croquette 2002 for reading Z from the ring pattern. Its method: build a reference set by stepping the objective in **200 nm** increments over **5-10 um**; find a brightness-weighted centre; bin pixel intensities by radius. It also describes a "Hilbert transformation scheme" that it says avoids slow optimisation and runs at ~20 Hz. [V-abs: search snippet of the patent] — [USPTO 7474184](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7474184)
- Croquette-lab Fourier-phase localization, verified in the SDI supplement (Rieu et al., arXiv 2008.02898, 2020; published later as Stereo Darkfield Interferometry). Steps: (1) apply a Blackman-Nuttall window, 128 px wide; (2) take the DFT; (3) a translation dx shifts each mode k's phase by 2*pi*k*dx; (4) compute the phase difference to a fixed reference profile, unwrap it, fit a line over the modes of interest, and get dx from the slope. Errors on each phase are weighted by 1/|Fourier modulus|. [V-full] — [arXiv 2008.02898](https://arxiv.org/pdf/2008.02898)
- SDI precision at full camera well depth: photon-noise frame-to-frame error **0.2 nm in y and z, 0.1 nm in x**. Z range up to **6 um** with 40x/100x objectives. Z is linear in the fringe separation, so **no LUT** is needed. This needs special optics (Fourier-plane slits and darkfield), so it is not a brightfield-ring method. [V-full] — [arXiv 2008.02898](https://arxiv.org/pdf/2008.02898)
- [UNVERIFIED, background knowledge] The commonly described Gosse-Croquette Z method works like this. The radial profile I(r) is band-pass filtered in Fourier space and turned into a complex (analytic, Hilbert-type) profile, the so-called "corkscrew". Its phase phi(r) is compared with the phases of the calibration profiles. The phase difference to the two neighbouring calibration slices changes smoothly and roughly linearly with z, so z between slices comes from interpolating that phase difference rather than from a least-squares minimum. The reported Z resolution was nm-scale at video rate. The exact numbers, slice spacing and filter band could not be confirmed.

### Inferences
- How this differs from plain least-squares LUT + parabola. Least squares returns a chi-square curve over slices and needs a fit (parabola or polynomial) near its minimum. The vertex of that fit is biased when the curve is not parabolic or when slices are coarse (Kovari 2019 calls quadratic fitting unreliable near the minimum with noise; see Q3). The phase approach turns the sub-slice problem into reading a quantity that is nearly linear in z between two neighbours, so its interpolation error should depend less on slice spacing. This is inferred from the method's principle and the SDI analogue, not from a measured comparison.
- The phase approach depends on the band-pass choice: only the ring spatial frequencies carry phase information. This is the same reason 3DPT (Q2) uses one spatial frequency.

### Gaps
- Gosse 2002 Appendix/Methods text: exact filter band, calibration slice spacing and range, interpolation formula, and reported Z precision. Not read because the full text was blocked. Next step: read the PDF from the publisher or Europe PMC by hand.
- No published head-to-head (same data) of phase interpolation against least-squares + parabola was found.

---

## Q2. FFT-phasor algorithm (PMC7202940)

### Takeaway
Brouwer TB, Hermans N, van Noort J, "Multiplexed Nanometric 3D Tracking of Microbeads Using an FFT-Phasor Algorithm", **Biophys J 118(9):2245-2257 (2020)**, DOI **10.1016/j.bpj.2020.01.015** (PMID 32053775; bioRxiv 10.1101/763706). It cross-correlates the ROI with computer-generated single-spatial-frequency complex reference images. The phase at the bead centre grows roughly linearly with height, so there is no radial profile and no LUT, only a polynomial phase-to-z calibration. Under ideal imaging it is 2-5x slower than LUT tracking and the authors say LUT can then be more accurate. It is more robust to noise and image artifacts.

### Cited Findings (all [V-full] — [PMC7202940, DOI 10.1016/j.bpj.2020.01.015](https://doi.org/10.1016/j.bpj.2020.01.015))
- Principle: the reference image is a complex radial wave with a single period P (pixels), spatially filtered. Cross-correlation is done by 2D FFT with a frequency-domain band-pass. The amplitude peak gives x,y; multiplying the amplitudes of two periods sharpens the peak, then a 2D polynomial gives sub-pixel position. The phase at the peak (amplitude-weighted mean over a 10-px ROI) gives z.
- Phase vs z: phase increases about linearly with height far from focus, with a calibration factor set by magnification and immersion index; it deviates near focus and for larger P. Phase wrapping is resolved with two or more periods (multi-frequency unwrapping).
- Calibration: still needed, but only a phase-vs-z curve. They fitted a polynomial (5th order over 10 um) and inverted it. Simulations used "15 polynomials and 15 reference periods". The factor "did not change between experiments or bead sizes", per the paper.
- Precision (fixed bead, PSD plateau): P = 7 px gives **2 nm/sqrt(Hz)**; P = 16 px gives 4 nm/sqrt(Hz); x,y about 0.07-0.09 nm/sqrt(Hz). The paper puts this at about **10 nm z at 30 Hz with one reference**. With 5 reference images z converged to **0.2 nm/sqrt(Hz)**, which is **2.4 nm at 30 Hz, or 1 nm at 5 Hz**.
- Accuracy over range: polynomial-fit residual SD **< 15 nm over 10 um**, lowest at P = 10 px. P < 7 px gave no distinct correlation peaks.
- Experimental: 10 immobilised 2.8 um beads with drift removed gave SD 0.3 nm (x,y) and **1.6 nm (z)** at 30 Hz.
- Noise sensitivity (LMST simulation, 8-bit): z accuracy fell from 0.05 to 10 nm/sqrt(Hz) as Poisson noise rose from 0 to 20 grey levels. A typical ~3 grey levels gave **~1 nm/sqrt(Hz)**.
- Robustness: insensitive to interlacing; tolerated astigmatism up to ~15%; unaffected until the bead was more than 30% out of the ROI; light gradients degraded z. In the same simulations, LUT tracking showed systematic z error and a few-percent fraction of outliers under Poisson noise; 3DPT had none.
- Speed: up to **10,000 ROIs/s** (100x100 px, 10-core 2.8 GHz Xeon, LabVIEW 2014). Under 3 ms/ROI for 64-128 px ROIs with 5 references. Cost grows linearly with the number of references; (n+1) FFTs per frame. Overall **2-5x slower than LUT**.
- Their own LUT baseline: sum the central 5 lines, mirror-correlate with a quadratic peak fit, take a radial profile of half the ROI, find the **RMS-difference minimum over 64 profiles spanning 0-15 um, refined by a quadratic fit**.
- The authors' own caveat: "when imaging conditions can be optimized" LUT tracking is faster and appears more accurate. A 2D cross-correlation with *measured* reference images was rejected because its phase is ill-defined.
- Setup: 40x NA 1.3 oil objective; 25 Mpix CMOS at 30 fps; 112 nm/px; 645 nm LED; 1.0 um and 2.8 um Dynabeads.
- Code: "available on Github" (LabVIEW). The repository URL was lost in the text extraction. [UNVERIFIED: repository name]
- Lorenz-Mie fitting in the same paper: several seconds per 100x100 ROI. For paramagnetic beads, systematic z errors were "hundreds of nanometers" over the range, put down to inhomogeneous bead composition. The range was >10 um for 1 um beads and ~5 um for 2.8 um beads.

### Inferences
- For a fixed rig with stable illumination, a per-bead LUT should stay at least as precise. 3DPT's advantage is robustness and calibration that carries over between beads, not precision.
- At our 8-bit, 90-150 Hz conditions, 1-2 nm/sqrt(Hz) means roughly **10-25 nm per frame**, by scaling the PSD plateau with sqrt(fs/2). This is an inference and was not measured.

### Gaps
- No experimental (non-simulated) head-to-head z-precision comparison against a well-implemented QI-LUT on the same beads.

---

## Q3. Cnossen et al. 2014 and other LUT variants (QI, van Loenhout, Kovari, Lansdorp, Carlucci)

### Takeaway
Cnossen JP, Dulin D, Dekker NH, "An optimized software framework for real-time, high-throughput tracking of spherical beads", Rev Sci Instrum 85(10):103712 (2014). The DOI is **10.1063/1.4898178**, not the article number. It is a CUDA implementation of Quadrant Interpolation with a radial-profile LUT. Tracking scatter is close to the Cramér-Rao bound; 228 beads tracked at 58 Hz with ~1 nm SD; it reports a previously unreported **bias along the optical axis**. I could not read its Z interpolation details. Kovari 2019 gives a verified and better-documented sub-step interpolator (spline plus Gauss-Newton, better than 0.05 step).

### Cited Findings
- Cnossen 2014: open-source CUDA framework with QI; scatter near the CRLB; trade-offs between speed, ROI size and bias; a z bias "not previously reported"; 228 DNA-tethered beads at 58 Hz with ~1 nm SD. [V-abs] — [VU repository, DOI 10.1063/1.4898178](https://research.vu.nl/en/publications/an-optimized-software-framework-for-real-time-high-throughput-tra/)
- [UNVERIFIED] Cnossen 2014's Z interpolation (I believe a quadratic/parabolic fit around the LUT-error minimum, plus LUT radial profiles built with QI sampling) and the size of its z bias. The full text was not read.
- van Loenhout MTJ, Kerssemakers JWJ, De Vlaminck I, Dekker C, "Non-bias-limited tracking of spherical particles, enabling nanometer resolution at low magnification", Biophys J 102(10):2362-2371 (2012). Quadrant Interpolation: the image is interpolated on a circular grid to remove pixel bias in x, y and z. Resolution improves "up to an order of magnitude in three dimensions" over centre-of-mass and cross-correlation. It shows that **x,y errors can seriously affect z** if interpolation is not used (XY-Z crosstalk). 107 DNA tethers were tracked in one experiment. [V-abs] — [DOI 10.1016/j.bpj.2012.03.073](https://doi.org/10.1016/j.bpj.2012.03.073)
- Kovari DT, Dunlap D, Weeks ER, Finzi L, "Model-free 3D localization with precision estimates for brightfield-imaged particles", Opt Express 27(21):29875-29895 (2019). Everything below is [V-full] — [PMC6825595, DOI 10.1364/OE.27.029875](https://doi.org/10.1364/OE.27.029875):
  - Each radial profile is compared with all LUT rows by summed squared residual, then refined.
  - The LUT is turned into continuous functions: Reinsch smoothing splines, reduced to piecewise cubic Hermite splines. Smoothing weight p = (1 + (dz/(Zmax-Zmin))^3)^-1.
  - The sub-step z is found by **Gauss-Newton minimisation** of the residual. The authors argue a quadratic fit is unreliable near the minimum with noise. In simulation Gauss-Newton beat discrete and quadratic at every noise level, and converged to zero error without noise.
  - It returns a per-frame sigma_z from the Jacobian.
  - Interpolation accuracy is **better than 0.05 step**. A discrete match alone is limited to half a step (10 nm for a 20 nm step).
  - LUT used: **~20 nm steps, 3 images per step, 10 um range**.
  - **Wrong-bead LUT** error: ±0.1 um (1.04 um beads, compared with 5-10 nm using the bead's own LUT) and ±0.2 um (2.8 um beads). A per-particle LUT is needed for accurate work.
  - Speed: Z solver in real time up to ~1 kHz.
  - Code: [figshare 8317136](https://figshare.com/articles/Radial_Symmetry_LUT_Tracking_Code/8317136) and [github dkovari/ExtrasToolbox](https://github.com/dkovari/ExtrasToolbox) (MATLAB).
- Lansdorp BM, Tabrizi SJ, Dittmore A, Saleh OA, "A high-speed magnetic tweezer beyond 10,000 frames per second", Rev Sci Instrum 84:044301 (2013), DOI 10.1063/1.4802678. [V-full] — [PDF](https://labs.materials.ucsb.edu/saleh/omar/sites/labs.materials.ucsb.edu.saleh.omar/files/pubs/lansdorp2013_highspeedmagnetictweezer.pdf)
  - x,y from mirror cross-correlation of line profiles with a 2nd-degree polynomial peak fit.
  - z from a radial profile compared with a LUT taken in **100 nm steps** by a piezo stage, "interpolated using least squares with polynomial fitting".
  - SLD illumination at 680 nm, 100x NA 1.4.
  - GPU CUDA code published.
  - Resolves position "within 1 Å at 100 Hz" (stuck bead, reference-subtracted) and 1566 bp DNA extension with 1 nm precision at 100 Hz.
- Carlucci LA, Thomas WE, "Modification to axial tracking for mobile magnetic microspheres", Biophys Rep (2021), [ScienceDirect S2667074721000318](https://www.sciencedirect.com/science/article/pii/S2667074721000318). [V-full via the NSF PAR PDF](https://par.nsf.gov/servlets/purl/10350879)
  - QI-based tracking (after van Loenhout).
  - LUT = average of the 5 best-matching calibration beads, 2 um steps over 200 um, 20x objective, ~8 um beads.
  - RMSE minimum plus **cubic-spline** interpolation.
  - Errors for **moving** beads were about an order of magnitude larger than for stuck beads: within-dwell SD 0.52 um and 0.80 um at the floor and ceiling. Excluding the central region of the ring pattern reduced this error.
  - This is a low-magnification, large-bead regime, so the numbers do not transfer to us. The direction of the effect does.

### Inferences
- Discretization bias scales with slice spacing times the interpolator's fractional error. With Kovari-type interpolation (<0.05 step), a 100 nm step leaves under ~5 nm bias, under their conditions. A parabola on a coarse grid can leave larger, periodic (z mod step) errors. That periodicity is a useful diagnostic: scan a stuck bead with the piezo and look at the residual against the commanded z.
- A per-bead LUT, as we use, avoids the 100-200 nm wrong-bead errors.

### Gaps
- Cnossen 2014: the size of the z bias, the interpolation details, and the recommended LUT spacing. Next step: read the AIP full text or the QTrk source code.

---

## Q4. Other approaches: Huhle 2015 kHz, Lorenz-Mie, deep learning, LUT-free phase

### Takeaway
High-end camera-based LUT methods reach Å-level Z under good conditions, at kHz rates and with high photon budgets: Huhle 2015 used 25 nm LUT steps; Dulin 2015 used a laser at 6-8 kHz. Lorenz-Mie fitting needs no calibration but is slow, and it is inaccurate for inhomogeneous paramagnetic beads. LUT-free linear methods (3DPT phase, SDI stereo) exist. I found **no peer-reviewed deep-learning Z regressor validated on magnetic-tweezers beads**; the nearest is a 2023 ResNet for trapped microspheres in optical tweezers.

### Cited Findings
- Huhle A, Klaue D, Brutzer H, Daldrop P, Joo S, Otto O, Keyser UF, Seidel R, "Camera-based three-dimensional real-time particle tracking at kHz rates and Ångström accuracy", Nat Commun 6:5885 (2015), DOI 10.1038/ncomms6885. [V-full] — [PMC4338538](https://pmc.ncbi.nlm.nih.gov/articles/PMC4338538/)
  - Z from the overfocus diffraction rings. The radial profile is computed on the GPU and compared "in an automated fashion" with a calibration table of the same particle at increasing overfocus, **step typically 25 nm**.
  - Per-pixel 3-parameter non-linear flat-field/FPN correction.
  - Pipelined x,y (CPU), radial profiles (GPU) and z (CPU).
  - Fixed 3 um PS beads at 2500 Hz: raw RMS 1.3 Å lateral, **1.8 Å axial**; 0.1 Å after 10-100 ms smoothing; 3 Å axial steps resolved.
  - DNA-tethered 1 um beads at 2800 Hz: Allan deviation minimum ~1 Å over 0.1-1 s; 5 Å steps discernible.
  - 26 beads at 420 Hz.
  - Illumination: Hg arc lamp (550/100 nm) or 625 nm LED.
  - The sub-step interpolation formula and any refractive-index correction are **not described** in the main text, and no shot-noise formula is given. The authors only say camera tracking is "severely limited by shot-noise" (~1e10 photons at 100 Hz for 100x100 px with ~1e4 e- wells).
- Dulin D, Cui TJ, Cnossen J, Docter MW, Lipfert J, Dekker NH, "High Spatiotemporal-Resolution Magnetic Tweezers: Calibration and Applications for DNA Dynamics", Biophys J 109(10):2113-2125 (2015), DOI 10.1016/j.bpj.2015.10.018. [V-full, first 100k characters] — [PMC4656881](https://pmc.ncbi.nlm.nih.gov/articles/PMC4656881/)
  - Uses the Cnossen 2014 GPU tracker, adapted to real time at 8 kHz.
  - 100x NA 1.49 objective, ~70 nm/px.
  - Z Allan deviations: 0.1 nm at 10 ms for a stuck M270 bead; 0.4 nm at 10 ms for MyOne; 0.23 nm at 8 ms for dsDNA with a laser at 8 kHz, against 0.5 nm with an LED at 500 Hz.
  - Tracking noise scales roughly as 1/sqrt(I) until saturation; contrast loss at saturation limits resolution; larger beads track better.
  - No refractive-index factor or LUT step given in the part that was read.
- Lorenz-Mie fitting: calibration-free; also fits radius and index. In Brouwer 2020 it took seconds per ROI. For Dynabeads the residuals were systematic and z errors were "hundreds of nanometers". [V-full] — [DOI 10.1016/j.bpj.2020.01.015](https://doi.org/10.1016/j.bpj.2020.01.015)
- Deep learning:
  - "Deep learning for precise axial localization of trapped microspheres in reflective optical systems" (2023): a residual network with a data-acquisition strategy; it reports better axial precision in reflective and transmission illumination optical tweezers. [V-abs: search snippet] — [PubMed 37157400](https://pubmed.ncbi.nlm.nih.gov/37157400/)
  - Vilnius group (Naudžiūnas, Perminaitė, Treigys, 2025 conference paper): CNN plus reinforcement learning on MT diffraction-ring images. Whether z is the regressed target, and its accuracy, were not confirmed. [V-abs: snippet] — [epublications.vu.lt](https://epublications.vu.lt/object/elaba:270379885/270379885.pdf)
- LUT-free phase:
  - 3DPT (Q2): a polynomial phase-to-z map, transferable between beads.
  - SDI (Q1): a linear stereo-interferometric z with no calibration stack; 0.2 nm z photon-noise floor; needs a Fourier-plane mask.
  - Lansdorp 2013 notes this lab's LUT code is freely available; the same holds for the Kovari and Brouwer code (see above).

### Inferences
- The gap between our expected precision (nm-scale at 90-150 Hz, 8-bit) and the Å results comes mostly from photon budget, bit depth and frame rate, not from the estimator. Huhle and Dulin used high-well-depth sensors, kHz rates and pixel-level corrections.
- Deep-learning Z for MT is not mature in the peer-reviewed literature, as far as these searches found.

### Gaps
- No verified deep-learning MT z paper with nm-level numbers.
- No verified shot-noise (CRLB) formula specific to ring-LUT z. The general photon-limited bound form appears in the SDI paper, Eq. 1 ([arXiv 2008.02898](https://arxiv.org/pdf/2008.02898)), and Cnossen 2014 compares against the CRLB (abstract only).

---

## Q5. Refractive-index mismatch (focal shift ~0.88) and LUT step choice

### Takeaway
Moving an oil-immersion objective by dz moves the focal plane in water by about n_water/n_oil x dz, roughly 0.88 dz. MT papers apply 0.88 as a fixed factor. Measurements with high-NA objectives near the surface give a much smaller factor, so 0.88 is an approximation. LUT steps in the literature run from 20 to 200 nm; finer steps reduce interpolation bias.

### Cited Findings
- "A force calibration standard for magnetic tweezers", Rev Sci Instrum 85:123114 (2014), set the "focal shift axial scaling factor" to **0.88** for an oil objective, from 1.33/1.51. [V-abs: search snippet] — [AIP](https://pubs.aip.org/aip/rsi/article/85/12/123114/109223/A-force-calibration-standard-for-magnetic-tweezers) [UNVERIFIED: author list, believed to be Yu Z, Dulin D, ..., Lipfert J, Dekker NH]
- Measured apparent focal shift for a 1.49 NA objective: **0.57 ± 0.02** over 0-1.5 um into water, "significantly smaller" than the n2/n1 = 0.88 approximation. [V-abs: search snippet; author names not verified] — [Princeton record: "Simple experimental methods for determining the apparent focal shift..."](https://collaborate.princeton.edu/en/publications/simple-experimental-methods-for-determining-the-apparent-focal-sh/)
- Optical-trap context: a 0.01 change in immersion-oil index shifts the optimal trapping depth by ~3-3.5 um in water. [V-abs: snippet] — [Opt Express 19:14794](https://opg.optica.org/oe/fulltext.cfm?uri=oe-19-16-14794&id=220408)
- Huhle 2015, Kovari 2019, Lansdorp 2013 and Dulin 2015 (part read) do not describe any refractive-index correction. Kovari relies on recording the LUT with the same optics. [V-full] — sources above
- 3DPT's phase-to-z factor depends on magnification and immersion index; a polynomial calibration absorbs it. [V-full] — [DOI 10.1016/j.bpj.2020.01.015](https://doi.org/10.1016/j.bpj.2020.01.015)
- LUT step choices reported:

  | Source | Step | Range | Verification |
  |---|---|---|---|
  | Kovari 2019 | 20 nm | 10 um | V-full |
  | Huhle 2015 | 25 nm | not stated | V-full |
  | Lansdorp 2013 | 100 nm | not stated | V-full |
  | Brouwer 2020 LUT baseline | 64 profiles (~234 nm) | 15 um | V-full |
  | Patent (Gosse lineage) | 200 nm | 5-10 um | snippet |
  | Carlucci 2021 (20x, 8 um beads) | 2 um | 200 um | V-full |

- Step effect: discrete matching alone is limited to half a step; spline + Gauss-Newton reaches below 0.05 step; quadratic fitting is unreliable near the minimum under noise. [V-full] — [Kovari 2019](https://doi.org/10.1364/OE.27.029875)

### Inferences
- **Suitability note for our calibration (60 x 0.1 um, cross 120 px, profile ~60 px, 8-bit, 90-150 Hz).**
  - The 100 nm step matches Lansdorp (100 nm, least squares + polynomial). It is 4-5x coarser than Huhle and Kovari (20-25 nm).
  - With a parabolic minimum fit, expect possible periodic bias with a 100 nm period. With spline/Gauss-Newton or phase interpolation, residual bias should be under ~5 nm (Kovari's under-0.05-step result; not measured on our rig).
  - The 6 um range is comparable to typical DNA tether extensions. 3DPT showed accuracy over 10 um with one polynomial.
  - Our 120 px ROI sits inside Brouwer's tested 64-256 px range, where ROI size "hardly affected accuracy".
  - 8-bit depth with ~3 grey-level noise corresponds in Brouwer's simulation to ~1 nm/sqrt(Hz) z (3DPT). For LUT, Poisson noise added systematic z error in their simulations.
- Whether 0.88 applies to us depends on whether our heights are measured relative to the piezo/objective move (then a factor is needed) or are used only as differences against a LUT recorded with the same optics. The LUT itself carries the scaling: LUT z is objective travel, not true bead travel in water. Absolute extensions therefore need a factor. The literature value ranges from 0.88 (paraxial) to about 0.57-0.8 (high-NA, measured); it should be measured for our objective, for example from known DNA contour lengths.

### Gaps
- Primary full texts of the RSI 85:123114 force-standard paper and the Bratton/Shaevitz focal-shift paper were not read; their authors and exact conditions are unverified.
- No paper found that quantifies Z bias against LUT step size experimentally for 100 nm vs 25 nm steps on the same bead.
