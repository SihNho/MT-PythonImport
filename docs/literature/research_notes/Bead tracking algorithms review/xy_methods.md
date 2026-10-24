# Lateral (XY) position estimators for magnetic-tweezers bead tracking (brightfield diffraction-ring images)

Research notes, 2026-10-22. Scope: the XY step only. Z (lookup-table) results are mentioned only where they show XY-Z crosstalk.
Verification level: van Loenhout 2012, Brouwer 2020, Huhle 2015, Dulin 2015, Ribeck 2008, Lansdorp 2013, Carlucci & Thomas were read in full text (or the relevant sections). Gosse & Croquette 2002, Cnossen 2014, Parthasarathy 2012 and Cheezum 2001 were read as abstract or secondary description only: their PDFs could not be retrieved (PMC serves 2002-era PDFs behind a browser check, which was not bypassed).

## 1. Gosse & Croquette 2002: the mirrored-profile XY method

### Takeaway
Gosse & Croquette (Biophys J 82:3314-3329, 2002, DOI 10.1016/S0006-3495(02)75672-5) is the root reference for the classic MT XY method. Three later primary papers that cite it describe the same principle: take a line intensity profile through the bead along X (and along Y), correlate it with its own mirror image, and fit the correlation peak with a low-order polynomial for the sub-pixel position. **I could not read the 2002 full text.** The specific details in the brief are therefore UNVERIFIED from the primary source: the number of averaged lines, the FFT implementation, the parabola fit, and the removal of discretization bias by phase-shift iterations. So is the XY precision Gosse & Croquette reported.

### Cited Findings
- The abstract of Gosse & Croquette 2002 says only that electromagnets are coupled to "a microscope-based particle tracking system through a digital feedback loop". It describes the trap stiffness (~1e-7 N/m), manipulation at ~10 um/s, rotation at 10 Hz, and forces of 50 fN-20 pN. No XY precision appears in the abstract. — [PMC1302119 abstract page](https://pmc.ncbi.nlm.nih.gov/articles/PMC1302119/), DOI [10.1016/S0006-3495(02)75672-5](https://doi.org/10.1016/S0006-3495(02)75672-5)
- Lansdorp et al. 2013 (Saleh lab) describe the algorithm "frequently used in magnetic-tweezer instruments" (refs incl. Gosse & Croquette). The in-plane position comes from the linear intensity profile along the horizontal and vertical axes near the bead centre. The profile is cross-correlated with its mirror image to get a first guess, and the cross-correlation is fitted to a second-degree polynomial near the central point for sub-pixel accuracy. The same in-plane algorithm is used to build the Z lookup table (100 nm steps). — [Lansdorp et al., Rev Sci Instrum 84:044301 (2013), DOI 10.1063/1.4802678](https://labs.materials.ucsb.edu/saleh/omar/sites/labs.materials.ucsb.edu.saleh.omar/files/pubs/lansdorp2013_highspeedmagnetictweezer.pdf)
- Ribeck & Saleh 2008 use a LabVIEW routine "similar to that developed by Gosse and Croquette". They measure I(x) from pixels running through the bead centre found in the previous frame; the maximum of the self-convolution of I(x) gives the x shift, and the same is done in y. Window size is typically 64-128 px. Conditions: Dynal MyOne (1.05 um mean) or M280 (2.8 um), 50x-150x. Up to 34 beads tracked at 60 Hz with ~1.5 nm resolution (abstract; this is the overall tracking resolution, mainly after reference-bead subtraction). Position error (z std of fixed beads) was inversely proportional to magnification between 50x and 150x. — [Ribeck & Saleh, Rev Sci Instrum 79:094301 (2008), DOI 10.1063/1.2981687](https://labs.materials.ucsb.edu/saleh/omar/sites/labs.materials.ucsb.edu.saleh.omar/files/pubs/ribeck2008_multiplexedsinglemolecule.pdf)
- Huhle et al. 2015 compute lateral (x,y) on the CPU "by correlating linear bead intensity profiles with their mirror profiles" (citing the classic method). Their results:
  - 3 um polystyrene beads fixed to the surface, 63 nm/px, 160x160 px ROI, 2500 Hz, mercury-lamp illumination filling about half the pixel well: RMS 1.3 A lateral, 1.8 A axial for the difference coordinate of two fixed beads.
  - Lateral Allan deviation minimum of 0.1-0.2 A between 100 ms and a few seconds.
  - 3 A lateral steps resolved at 1 s intervals.
  - Multi-bead mode: 141 nm/px, 72x72 px ROI, up to 500 Hz, 625 nm LED, all processing on GPU.
  - Camera 1280x1024 CMOS.
  — [Huhle et al., Nat Commun 6:5885 (2015), DOI 10.1038/ncomms6885](https://pmc.ncbi.nlm.nih.gov/articles/PMC4338538/)

### Inferences
- The mirror-symmetry trick is self-referencing: no template is needed and the result is insensitive to the exact ring shape (defocus). It only assumes the pattern is symmetric about its centre. The secondary descriptions agree on: 1D line profiles, correlation with the mirror, and a 2nd-order polynomial peak fit.
- Huhle 2015 shows that this 1D mirrored-profile method can reach sub-Angstrom-to-Angstrom lateral noise at high magnification (63 nm/px) and high photon counts. Its known weakness, pixel bias at low magnification, is documented by van Loenhout 2012 (Section 2).

### Gaps
- Not verified from the primary text: the number of averaged lines and the band width of the cross profiles, the windowing, the FFT implementation, the exact peak-fit order, the bias-removal procedure ("phase-shift iterations"), and the XY precision numbers Gosse & Croquette reported, with their conditions. The PMC PDF (PMC1302119, 441.5 KB, scanned) sits behind a browser verification page. Recommended: the user downloads it manually, or reads the methods of Strick/Allemand/Croquette-lab papers or the Xvin/PicoTwist documentation.

## 2. Quadrant interpolation (QI) — van Loenhout, Kerssemakers, De Vlaminck, Dekker 2012

### Takeaway
QI resamples the bead image on a polar grid around a ~1-px-accurate first guess, using bilinear interpolation with radial step δr of about 1/3 px. It then builds four quadrant radial profiles, concatenates left/right (top/bottom) into one profile, cross-correlates that profile with its mirror via FFT, and fits the peak with a 5-point parabola. In simulations at SNR 30 its XY bias stays far below its scatter, unlike centre of mass (COM) and 1D cross-correlation (XCOR). It reaches sub-1-nm XY at 30x magnification (7.4 um camera pixels, ~247 nm/px). The 2012 paper describes a single correction pass. Iterating QI (feeding the output back as the next centre) appears in later implementations, but I found no iteration count in the 2012 text.

### Cited Findings
- **Algorithm**, from van Loenhout et al. 2012, Biophys J 102:2362-2371, DOI [10.1016/j.bpj.2012.03.073](https://doi.org/10.1016/j.bpj.2012.03.073) — [PMC3353059](https://pmc.ncbi.nlm.nih.gov/articles/PMC3353059/):
  - (1) Rough centre from a background-corrected COM followed by a 1D XCOR. Any method accurate to ~1 px will do.
  - (2) Radial profiles per quadrant (TL, TR, BR, BL) on a circular grid (δr, δθ), using bilinear interpolation of the 4 nearest pixels.
  - (3) Ix(r) = qL(-r) || qR(r), with qR = qTR+qBR and qL = qTL+qBL. It is cross-correlated with its mirror by FFT: X = IFFT(FFT(Ix)·conj(FFT(Ix(-r)))). The peak sits at twice the shift. Y is analogous, from qT and qB.
  - (4) Five-point parabolic fit of the peak. Geometric correction δx = δr/(π/2), valid for corrections smaller than 1 px. x = x_est − δx.
- **Grid parameters**: resolution stops improving once δr < ~1/3 px. δθ is chosen so that δθ·r_max = 1 px, and it can be increased considerably (trading accuracy for speed). — same source.
- **Speed (2012)**: ~0.01 s per 128x128-px image on a 2-GHz Intel Core2 CPU, in a LabVIEW implementation. — same source.
- **Simulation conditions**: the reference pattern was built from real images of a 2.8 um M270 bead at 75x (Nikon 50x oil, NA 0.9, 300 mm tube lens; Dalsa Falcon 1.4M100XDR, 8 bit, 7.4 um pixels; green LED). The bead was 10 um above focus. Poisson noise was added, and the pattern was moved 2 px in 40 steps with 250 noise realisations per step. Scatter and bias were evaluated separately, and resolution σ_total = sqrt(σ_bias² + σ_scatter²). The default SNR was 30, which the authors estimate is the practical maximum for an 8-bit camera; SNR = S/(4σ) − 1. — same source.
- **XY results** (simulations, SNR 30). Numbers are read from the text; the figure values are not tabulated.
  - Scatter is nearly the same for COM, XCOR and QI. It rises below 20x for XCOR/QI (undersampling).
  - Bias falls fast with magnification for QI, entering a low-bias region above 50x. COM and XCOR bias falls slowly and "never reaches" QI. For COM and XCOR, bias exceeds scatter at most magnifications, so it limits their resolution.
  - QI is "not bias-limited" from 30x up.
  - "At 30x magnification, a sub-1-nm resolution for x,y-direction and a sub-10-nm resolution for the z-direction are possible", only with QI.
  - The abstract states up to an order-of-magnitude improvement in 3D over the conventional methods.
  — same source.
- **SNR dependence** (75x, SNR 2-100). Scatter falls monotonically for all methods. At low SNR QI beats XCOR, because QI samples all pixels whereas XCOR samples a subset. COM and QI bias falls with SNR; XCOR bias is independent of SNR. QI bias is "well below scatter for all SNRs". — same source.
- **XY-Z crosstalk**:
  - Z error is dominated by propagated XY error. Feeding QI's xy into the COM/XCOR z-trackers brings them to QI-level z performance.
  - The non-interpolating COM radial profile (1-px bins) is more than an order of magnitude worse in z under x-motion. Radial-profile interpolation is the key, whatever XY algorithm is used.
  - x-error caused by z-motion is small compared with that from in-plane motion.
  - Crosstalk is invisible when tracking fixed beads and appears with Brownian beads.
  — same source.
- **Experiments**:
  - On real fixed M270 beads at 75x, the COM experimental z-resolution was markedly worse than simulated, attributed to COM's sensitivity to uneven background illumination and bead asymmetry.
  - Multiplexed MT at 25x with 1 um beads: 245 beads in a 300x400 um field. QI yielded 107 fittable DNA tethers, XCOR 51, COM 0. XCOR showed "large discrete steps" in the tracked position (a pixel-locking-type artefact) and overestimated the end-to-end length: 2.42±0.14 um vs 2.33±0.18 um for QI, with 2.26 um expected.
  — same source.
- **Sampling limits**: all trackers degrade sharply below 20x, when the fringe spacing (~1.3 um between the main and second fringe) nears the pixel size (12x limit). Nyquist for the Airy pattern at NA 0.9 and 520 nm corresponded to 42x; QI bias does not improve beyond 50x. — same source.
- **Robustness**: QI is "robust to such deformations of the circular geometry if these remain well below the fringe spacing" (non-spherical particles). Not modelled: camera nonlinearity, vibration, uneven illumination. — same source.
- **GPU QI**: Cnossen, Dulin & Dekker 2014 implemented QI in CUDA and reported:
  - scatter close to the Cramér-Rao lower bound;
  - trade-offs between speed, ROI size and tracking bias, including a previously unreported bias along the optical axis;
  - 228 DNA-tethered beads tracked at 58 Hz with ~1 nm standard deviation on consumer hardware.
  — [Cnossen et al., Rev Sci Instrum 85:103712 (2014), DOI 10.1063/1.4898178](https://doi.org/10.1063/1.4898178) (PubMed abstract via NCBI E-utilities, PMID 25362408)
- **Iterated QI in software**: MagTrack's `qi()` "can be iterated, with each pass taking the previous output as its input". The example uses 3 passes; no default count is documented. Its XY chain is: center_of_mass (median background subtraction by default) → auto_conv → auto_conv_sub_pixel → QI. Every function runs on NumPy (CPU) or CuPy (GPU). — [MagTrack user guide v0.7.7](https://magtrack.readthedocs.io/en/v0.7.7/user_guide.html)
- **QI in later instruments**: Dulin et al. 2015 used the Delft framework (Cnossen co-author) with 8-bit CMOS (Mikrotron MC1362), ~70 nm/px, 100x100 px ROI at 8 kHz, GTX 580 GPU, MyOne 1 um and M270 2.8 um beads. Their reported numbers are axial (Allan deviation): M270 0.1 nm at 0.01 s; MyOne 0.4 nm at 0.01 s. Resolution scales roughly with bead radius and is shot-noise limited (1/sqrt(I)). — [Dulin et al., Biophys J 109:2113 (2015), DOI 10.1016/j.bpj.2015.10.018](https://pmc.ncbi.nlm.nih.gov/articles/PMC4656881/)
- **QI with moving beads**: Carlucci & Thomas used a QI-based tracker (MATLAB; FFT alignment of the cutout with its 90°-rotated copy for the initial estimate). Tracking error for mobile magnetic beads rose by almost an order of magnitude over stationary beads (axial). Excluding the central region of the ring pattern from the radial profile reduced it; the modifications were applied to z only, not to xy. Conditions: ~8 um beads, 20x objective. — [Carlucci & Thomas, "Modification to axial tracking for mobile magnetic microspheres" (NSF PAR accepted manuscript)](https://par.nsf.gov/servlets/purl/10350879)

### Inferences
- The XY "iterations" in QI practice mean re-running steps 2-4 around the updated centre (MagTrack example: 3). The 2012 paper's δx = δr/(π/2) is a small-shift linearisation, which is why iterating helps when the first guess is off by about 1 px.
- At comparable sampling (≥ ~30x with 7.4 um pixels, i.e. ≤ ~250 nm/px), QI is the published method with demonstrated low pixel bias for ring patterns. The COM-vs-XCOR-vs-QI ordering was shown both in simulation and on real low-magnification multiplexed data.

### Gaps
- No tabulated XY bias/scatter values in nm per magnification could be extracted from the text (they are in Fig. 3/5). The iteration count and convergence studies for QI (Cnossen 2014 full text) were not read; RSI is not open access here.

## 3. Radial symmetry centre — Parthasarathy 2012

### Takeaway
An analytic, non-iterative estimate. It computes intensity gradients at pixel-edge midpoints and returns the point that minimises the weighted distance to the lines along those gradients. It claims accuracy near theoretical limits (similar to Gaussian fit and MLE) at orders of magnitude higher speed, and lower sensitivity to nearby particles. It is stated to apply to "any radially symmetric intensity profile", but I found no published validation on defocused MT ring patterns or comparison with QI.

### Cited Findings
- Abstract and author page:
  - "analytic, non-iterative calculation of the best-fit radial symmetry center";
  - accuracies "near theoretical limits, similar to nonlinear Gaussian fitting and maximum likelihood estimation", with "orders of magnitude faster execution time";
  - "lower sensitivity to nearby particles";
  - "applicable to any radially symmetric intensity profile";
  - tested on simulated data and on real images (colloidal assemblies, single fluorescent proteins);
  - ~10 µs per image on a laptop for small (e.g. 9x9 px) images;
  - the author warns that intensity-centroid methods "can be dangerously inaccurate, especially at low signal-to-noise ratios".
  — [Parthasarathy lab page](https://pages.uoregon.edu/raghu/particle_tracking.html); Nature Methods 9:724-726 (2012), DOI [10.1038/nmeth.2071](https://doi.org/10.1038/nmeth.2071)
- An APS March Meeting 2012 abstract states execution "over two orders of magnitude faster". — [APS abstract](https://archive.aps.org/mar/2012/b49/11)

### Inferences
- For a defocused bead (bright and dark concentric rings), gradient directions on alternate fringes still point radially, toward or away from the centre. Since lines, not vectors, are used, the method should in principle still find the centre. However, its weighting (gradient magnitude squared, distance to centroid) was designed for a single compact spot. This is an inference, not a published result for MT ring images.
- Speed per ROI for 120x120 px would be higher than the quoted 9x9 figure; the cost is O(N²).

### Gaps
- No primary-source numbers on radial symmetry for 1-3 um beads in brightfield MT at 10+ um defocus. No pixel-bias study versus QI. Leahy et al. 2018 (arXiv 1801.03581) analyse biases of centroid and Gaussian fit but do not cover radial symmetry. — [Leahy et al. 2018](https://arxiv.org/abs/1801.03581)

## 4. Centroid/COM, 2D Gaussian fit, template cross-correlation, and newer methods (2015-2026)

### Takeaway
COM is the cheapest estimator and is used everywhere as the first guess. It is the most biased and the most sensitive to background gradients and neighbours. 2D Gaussian fitting suits diffraction-limited spots, not ring patterns. Cross-correlation (mirror or template) is best for large particles but keeps pixel bias. Newer options with published MT data:
- 3D phasor tracking (Brouwer 2020): FFT cross-correlation with a synthetic single-spatial-frequency reference, sub-nm XY, robust to noise and illumination gradients.
- Holographic reconstruction (HoloMiP 2022): tolerates overlapping patterns.
- Deep-learning localisation (CenterNet, 2024): tens of nm horizontally, much worse than classical methods.

### Cited Findings
- **Cheezum et al. 2001** compared cross-correlation, sum-absolute-difference, centroid and direct Gaussian fit on simulated images with known sub-pixel shifts, for objects from point sources to 5 um:
  - cross-correlation was most accurate for large particles;
  - Gaussian fit was best for point sources and the most robust at low SNR;
  - all four fail as SNR approaches 4.
  — [Cheezum, Walker & Guilford, Biophys J 81:2378 (2001), DOI 10.1016/S0006-3495(01)75884-5](https://pmc.ncbi.nlm.nih.gov/articles/PMC1301708/)
- **Bias mechanism**: pixel bias is periodic in the pixel grid. The centroid of the sampled image differs from the true centroid when the image has spatial frequencies above half the sampling frequency. Kernel-based methods suffer similarly through the sub-pixel peak-fit step. Gaussian fitting achieves the theoretical minimum only when the profile is Gaussian, which fails for d > λ or for defocused objects. — [van Loenhout et al. 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3353059/)
- **Centroid/Gaussian bias even on simple images**: both "produce considerable biases even on unrealistically simple images", per a generative-model (PERI) comparison. — [Leahy et al. 2018](https://arxiv.org/abs/1801.03581)
- **3D phasor tracking (3DPT)**, Brouwer, Hermans & van Noort, Biophys J 118:2245-2257 (2020), DOI [10.1016/j.bpj.2020.01.015](https://doi.org/10.1016/j.bpj.2020.01.015) — [PMC7202940](https://pmc.ncbi.nlm.nih.gov/articles/PMC7202940/):
  - Method: the ROI is cross-correlated by FFT with complex reference images I_n(r) = f_s(r)·exp(i2πr/k_n) (single spatial frequency, raised-cosine window), with a Gaussian band-pass in k-space. The amplitude images for two periods (k = 7 and 16 px) are multiplied to sharpen the peak. XY comes from 2D polynomial sub-pixel interpolation of the peak. Z comes from the phase at the peak.
  - Experimental XY PSD plateau: 0.7e-3 nm²/Hz (x) and 0.9e-3 nm²/Hz (y), i.e. ~0.2 nm XY at 30 Hz. Fixed beads gave σ_xy = 0.6 nm (σ_z = 1.6 nm).
  - Up to 10,000 ROIs/s for 100x100 px ROIs, and 100+ beads tracked in real time on a generic CPU. The paper also states <3 ms/ROI for 64-128 px ROIs with five references, and 2-5x slower than LUT tracking. Of the two speed statements, the first is for fewer references.
  - Simulated 1.0 um paramagnetic beads 12 um above focus (Lorenz-Mie):
    - XY accuracy was "hardly affected" by Poisson noise (constant at 0.5 nm²/Hz; it decreased only 2x at 20 grey levels of noise in 8-bit images);
    - illumination gradients up to 20% only slightly affected the gradient direction, with no correlation peak above 70%;
    - astigmatism degraded all three axes;
    - tracking held until the bead was shifted ~30% out of the ROI and was lost beyond ~40%;
    - ROI size from 64 to 256 px "hardly affected accuracy";
    - the reference frequencies must be retuned when magnification (pixel size) changes.
  - Camera: 25 Mpix CMOS, 0.5x0.5 mm² field of view.
- **Classic three-stage pipeline** (COM or 1D/2D cross-correlation with mirrored profile or kernel → radial profile → LUT): QI "minimized cross talk between the x, y, and z coordinates". — [Brouwer et al. 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7202940/)
- **Lorenz-Mie fitting**: nm accuracy, but "several seconds" per 100x100 ROI on a CPU, so not real-time. Z systematic errors were hundreds of nm for their paramagnetic beads. — [Brouwer et al. 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7202940/)
- **HoloMiP** (digital holographic reconstruction plus 3D parabolic masking): needs no LUT. The authors say the LUT cross-correlation approach "depends on symmetry and fails when diffraction patterns overlap", whereas HoloMiP "can also localize particles even if their diffraction patterns overlap". They claim it outperforms existing methods in precision, speed, simplicity and tolerance to crowding; I did not extract numeric XY precision. — [HoloMiP, Biophys J 2022, PMC9300656](https://pmc.ncbi.nlm.nih.gov/articles/PMC9300656/)
- **Deep learning**: a CenterNet-based 3D network trained on synthetic data built from calibrated images of 1 and 2 um polystyrene beads (wide-field illumination). It reached a horizontal error of 0.0478 um (~48 nm) and z error of 0.199 um, near focus. — [Sensors 2024, PMID 38676200, PMC11054292](https://pmc.ncbi.nlm.nih.gov/articles/PMC11054292/)
- **Gap in DL for MT**: no peer-reviewed deep-learning XY localiser specific to MT ring images with nm precision was found. A 2024 Vilnius conference poster states there is "a notable gap" in such algorithms (poster content not read). — [search result: mii.lt DAMSS 2024 poster](https://mii.lt/damss/files/posters_2024/id_III-10.pdf)
- **GPU tracking in MT**: Lansdorp 2013 used a CUDA implementation of the mirrored-profile/LUT tracker for >10,000 fps offline analysis. Huhle 2015 split the work: XY on CPU, radial profiles on GPU, z on CPU, pipelined across frames. — [Lansdorp 2013](https://labs.materials.ucsb.edu/saleh/omar/sites/labs.materials.ucsb.edu.saleh.omar/files/pubs/lansdorp2013_highspeedmagnetictweezer.pdf); [Huhle 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4338538/)

### Inferences
- **Ranking for MT ring images**, from the evidence above:
  - Accuracy (bias): QI ≈ 3DPT (both sub-nm, demonstrated) > 1D mirrored XCOR (precise, but pixel-biased at low magnification) > COM (biased, background-sensitive).
  - Speed: COM > 1D XCOR > QI > 3DPT (3DPT is 2-5x slower than LUT/QI-class pipelines).
  - Radial symmetry is untested for MT rings. Deep learning is currently ~2 orders of magnitude less precise.
- 2D Gaussian fitting is not appropriate for defocused ring patterns. This is stated by van Loenhout and consistent with Cheezum's finding that cross-correlation wins for large objects.

### Gaps
- No primary head-to-head of QI vs 3DPT vs radial symmetry on the same MT images. No pixel-locking histograms published for 3DPT. Fourier/phase-based XY bias as a function of pixel size has not been quantified beyond "retune k_n".

## 5. Robustness to defocus and neighbouring beads

### Takeaway
All symmetry-based methods (mirrored XCOR, QI, 3DPT, radial symmetry) assume one circularly symmetric pattern per ROI. In practice they fail once the innermost rings of neighbouring beads overlap; Ribeck found ~5-8 um spacing necessary for 1 um beads. Within that limit, the published robustness evidence is:
- QI: lowest bias and crosstalk, works at 25-30x.
- 3DPT: tolerant to noise, illumination gradients and off-centre beads up to ~30% of the ROI.
- Radial symmetry: claimed lower neighbour sensitivity, but not tested on rings.
- Holographic reconstruction (HoloMiP): explicitly handles overlapping patterns.
- COM: the least robust.

### Cited Findings
- **Bead spacing**: the bright innermost interference ring dominates both lateral and vertical tracking, so higher-order ring overlap does not measurably affect accuracy. Once the innermost rings overlap, the pattern is no longer symmetric and "tracking ability is lost completely". This requires 5-8 um spacing between 1 um beads on ~2 um DNA tethers. — [Ribeck & Saleh 2008](https://labs.materials.ucsb.edu/saleh/omar/sites/labs.materials.ucsb.edu.saleh.omar/files/pubs/ribeck2008_multiplexedsinglemolecule.pdf)
- **COM sensitivity**: COM is "very sensitive to disturbances such as uneven background illumination or asymmetries in the tracked beads", and was worse experimentally than in simulation. — [van Loenhout 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3353059/)
- **Defocus**: QI's evaluations were performed at 10 um defocus, mid-lookup-table. Lateral crosstalk from z motion is small for QI and XCOR except at very low magnification. — [van Loenhout 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3353059/)
- **3DPT robustness** (simulated 1 um beads at 12 um above focus): robust to Poisson noise, interlacing, light gradients up to 20%, and ROI-centre offsets up to 30%. Sensitive to astigmatism above ~15-30%. — [Brouwer 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7202940/)
- **Overlap**: LUT/cross-correlation methods "fail when diffraction patterns overlap"; HoloMiP localises overlapping patterns. — [HoloMiP 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9300656/)
- **Neighbours under radial symmetry**: "lower sensitivity to nearby particles" (abstract claim, fluorescence/colloid context). — [Parthasarathy 2012](https://pages.uoregon.edu/raghu/particle_tracking.html)
- **Moving beads**: error is ~10x larger than for fixed beads (axial). Fixed-bead tests hide bias and crosstalk. — [Carlucci & Thomas](https://par.nsf.gov/servlets/purl/10350879); [van Loenhout 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3353059/)

### Inferences (short suitability note for our rig, unverified against our images)
Our rig: JAI CMOS 1280x1024, 8-bit, 90-150 Hz, ROI 120 px, 1-um-class beads, 5-80 beads, CPU (numba) or RTX 2060.
- **SNR**: 8-bit puts us near van Loenhout's SNR ≈ 30 ceiling, where QI's bias is already below its scatter. COM/XCOR bias would dominate unless the pixel size is ≤ ~100 nm.
- **Pixel size**: unknown here. The main QI number (sub-1 nm at 30x) used a 7.4 um camera pixel, ~247 nm/px. Compute ours from the camera pixel pitch and magnification before transferring that number.
- **Load**: 80 beads x 150 Hz = 12,000 ROIs/s. The 2012 CPU QI figure (0.01 s per 128² ROI on a 2-GHz Core2, LabVIEW) would be far too slow single-threaded. The GPU QI (Cnossen: 228 beads at 58 Hz ≈ 13,000 ROIs/s on 2014 consumer GPUs) and the 3DPT CPU figure (up to 10,000 ROIs/s at 100² px) are in the right range. A numba-parallel or RTX 2060 implementation of QI is plausible, but this is not measured.
- **Recommended XY chain** from the literature: COM (background-subtracted) → 1D mirrored XCOR → QI with 2-3 iterations, δr ≈ 1/3 px. Then validate with a simulated sub-pixel displacement scan, as van Loenhout did, not with fixed beads alone.
- **Neighbours**: keep the inner rings of neighbouring beads out of each 120-px ROI (≥ ~5-8 um spacing for 1 um beads).

### Gaps
- No published XY bias study specifically for MyOne-class (1 um) beads at ~100-250 nm/px with 8-bit CMOS. Robustness of QI to a partially overlapping neighbour has not been quantified in any source found. Radial-symmetry performance on MT rings is unpublished as far as found.
