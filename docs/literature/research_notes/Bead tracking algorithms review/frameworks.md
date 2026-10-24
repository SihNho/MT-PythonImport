# Software implementations and frameworks for magnetic-tweezers bead tracking

Checked 2026-10-22. Repository facts (license, dates, file lists, source excerpts) came straight from the GitHub API (`gh api repos/...`) and PyPI JSON on that date. Paper facts come from PMC full text, abstracts, or lab pages, as cited. Anything not confirmed directly is marked UNVERIFIED.

Target: a Python tracker (NumPy/numba, optional CUDA on an RTX 2060).

## Inventory table (summary)

| Name | Lab / authors | Algorithms (XY / Z) | Language | CPU/GPU | Reported throughput | License | Repo | Last activity | Use for our Python tracker |
|---|---|---|---|---|---|---|---|---|---|
| GPU-Accelerated-Magnetic-Tweezer-Tracking-CUDA | Tabrizi / Lansdorp, Saleh lab (UCSB) | Mirror-profile correlation via cuFFT, 3-point quadratic peak fit / radial profile, then LUT or phase (Z part UNVERIFIED) | CUDA C (VS2008 project) | GPU | Paper: >10 kfps camera, analysed offline; the student report gives about 5,000 beads/s in 3D | MIT | github.com/shawntabrizi/GPU-Accelerated-Magnetic-Tweezer-Tracking-CUDA | last commit 2019-05-07 (code from 2012) | Algorithm reference only; old CUDA 4.2, not a drop-in |
| QTrk (qtrk) | Cnossen, Dulin, Dekker (TU Delft) | COM, then XCor1D, then QI (quadrant interpolation) / radial-profile ZLUT | C++ / CUDA, LabVIEW plugin, .NET wrapper | CPU + GPU | 228 beads at 58 Hz, about 1 nm SD (abstract) | MIT | github.com/jcnossen/qtrk | last commit 2021-05-24 | Best algorithm reference (QI, ZLUT bias study); could be wrapped via its C API (DLL) but Windows/VS + old CUDA build |
| BeadTracker | Cnossen / Dekker lab | Uses qtrk | LabVIEW | CPU + GPU via qtrk | not stated | none in repo (no LICENSE detected) | github.com/jcnossen/BeadTracker | last push 2016-02-19 | LabVIEW reference only; unlicensed, so do not copy code |
| Huhle et al. 2015 tracker | Seidel lab (Leipzig/Münster) | Mirror-profile correlation of line profiles (CPU) / radial profile vs calibration table (GPU) | CUDA C DLL + LabVIEW 2010 | GPU (GTX 480) | up to 3 kHz for 2 beads (150 MB/s); 26 beads at 420 Hz | not stated | none found; offline version "on author's webpage" | 2015 | Paper reference for kHz real-time; no code found |
| Dulin lab MT software (Ostrofet 2018) | Dulin (FAU Erlangen / VU Amsterdam) | Cites Cnossen 2014 (QTrk), CPU or GPU | LabVIEW 2016 | GPU GTX 1080 | 10 Hz default, 1720 Hz validation, hundreds of beads possible | no release | none | 2018 | Shows QTrk in a production multiplexed rig |
| MagTrack | London, ..., Fishel (Ohio State) | COM, auto-conv (mirror correlation), multiline auto-conv sub-pixel, "qi" (= quadratic interpolation, NOT quadrant interpolation), FFT profile / radial profile + lookup_z | Python (NumPy, SciPy, CuPy) | CPU or GPU, same code path | per-function timings on RTX 3070 / i7-13700 in repo (see below) | GPL-3.0 | github.com/7jameslondon/MagTrack (PyPI `magtrack`) | v1.0.0 released 2026-09-15 | Closest drop-in for a Python pipeline; GPL-3.0 constrains reuse |
| MagScope | same group | Live acquisition GUI using MagTrack; XY- and Z-lock | Python (PyQt6, multiprocessing, h5py) | CPU or GPU | not found | GPL-3.0 | github.com/7jameslondon/MagScope (PyPI `magscope`) | v1.0.0 released 2026-09-15 | Architecture reference (multiprocessing live pipeline) |
| brauchilab/MagneticTweezers | Brauchi lab | UNVERIFIED (not inspected) | C++ | UNVERIFIED | not stated | MIT | github.com/brauchilab/MagneticTweezers | last push 2022-03-17 | Unexamined |
| Tweezepy | Ian L. Morgan | Force calibration (Allan variance / PSD), not image tracking | Python | CPU | n/a | GPL-3.0 | github.com/ianlmorgan/tweezepy (PyPI 1.2.7, 2024-02-22) | repo updated 2026-04-13 | Downstream calibration only, not a tracking stage |

## Lansdorp et al. 2013 and the Tabrizi CUDA code

### Takeaway
Lansdorp, Tabrizi, Dittmore and Saleh (RSI 84:044301, 2013) built a >10 kfps magnetic tweezer using SLD light, a high-speed camera and GPU-accelerated tracking of recorded video, so tracking was offline. The public CUDA code (MIT, 2012-era) uses a Gosse–Croquette-style XY method: correlate an averaged cross profile with its mirror image using cuFFT, take a 3-point quadratic peak, and halve the shift. It then bins a radial profile with linear weighting. I could not read the paper's full text, so its exact precision numbers and stated changes versus Gosse–Croquette are not confirmed.

### Cited Findings
- Citation and design: superluminescent diode illumination, a high-speed camera, and GPU-accelerated particle tracking used "to analyze the video files", which means offline analysis — [Saleh lab PDF / search abstract](https://labs.materials.ucsb.edu/saleh/omar/sites/labs.materials.ucsb.edu.saleh.omar/files/pubs/lansdorp2013_highspeedmagnetictweezer.pdf). DOI 10.1063/1.4802678, from the PDF metadata.
- The Saleh lab code page lists GPU Tracking Demo V1–V4. V2 "fixes a discretization error in lateral tracking"; V3 and V4 are 64-bit builds. No language or license is stated on that page — [Saleh lab code page](https://labs.materials.ucsb.edu/saleh/omar/research/code)
- The UCSB undergraduate (RISE 2012) report by Shawn Tabrizi says a GPU with CUDA tracked nearly 5,000 beads/s in 3D — [UCSB MRL RISE page](https://mrlweb.mrl.ucsb.edu/education/undergrad/rise/2012/shawn-tabrizi). This is a precursor, not the paper's figure.
- GitHub repo checked by API: license MIT, created 2012-11-05, last commit 2019-05-07, 3 stars, not archived. It holds a Visual Studio project with `main.cu` and kernels `avgxcrossandprep.h`, `avgycrossandprep.h`, `calculateradialprofile1/2.h`, `finddelta.h`, `fitprepandphase.h`, `quadfit.h`, `rotate.h`, and ships CUDA 4.2 runtime DLLs (`cudart64_42_9.dll`) — [GitHub repo](https://github.com/shawntabrizi/GPU-Accelerated-Magnetic-Tweezer-Tracking-CUDA)
- Source excerpt, `finddelta.h`: takes the argmax of the averaged X profile (stored as `cufftComplex`, which suggests an FFT correlation), fits a 3-point quadratic (`QuadFit(size=3)`), and sets x = x0 + (vertex − cross/2)/2. The factor 1/2 is the signature of a mirror (auto-)correlation shift — [finddelta.h](https://github.com/shawntabrizi/GPU-Accelerated-Magnetic-Tweezer-Tracking-CUDA/blob/master/GPU%20Tracking/finddelta.h)
- Source excerpt, `calculateradialprofile1.h`: one thread per (image, bead, row). Each pixel inside radius cross/2 is split linearly between bins floor(r) and floor(r)+1 with `atomicAdd`. The code comments flag an unresolved "discrepancy in the last values" and no bounds check — [calculateradialprofile1.h](https://github.com/shawntabrizi/GPU-Accelerated-Magnetic-Tweezer-Tracking-CUDA/blob/master/GPU%20Tracking/calculateradialprofile1.h)
- `config.h` hard-codes `threadsPerBlock(16, 2)` over a grid of images by beads, so a batch of frames is processed at once, which fits offline use — [config.h](https://github.com/shawntabrizi/GPU-Accelerated-Magnetic-Tweezer-Tracking-CUDA/blob/master/GPU%20Tracking/config.h)
- Lansdorp's UCSB thesis reports pushing MT resolution toward the Ångström scale with a camera above 10 kHz — [UCSB Alexandria](https://alexandria.ucsb.edu/lib/ark:/48907/f3fq9wf2)

### Inferences
- XY is the classic Gosse–Croquette mirror-profile method moved onto a GPU batch. The `fitprepandphase.h` name hints at a phase-based Z or sub-pixel step, but I did not read that file.
- It is useful as an algorithm cross-check (quadratic peak and halving) but not as a drop-in: it needs CUDA 4.2, VS2008, `unsigned char` images and hard-coded sizes.

### Gaps
- Paper precision (nm at what bandwidth), bead count, fps and algorithm changes versus Gosse–Croquette: I could not extract the paper text. The PDF downloaded, but text extraction was blocked because installing a PDF library is barred while the rig is in experiment state. UNVERIFIED.
- The Z method in the CUDA code (LUT correlation or phase) is UNVERIFIED; I did not read `fitprepandphase.h` or `main.cu`.

## Cnossen et al. 2014: QTrk

### Takeaway
QTrk (Cnossen, Dulin, Dekker, RSI 85:103712, 2014) is the reference open framework. It runs a C++/CUDA queued tracker of COM, then 1D cross-correlation, then Quadrant Interpolation for XY, plus a radial-profile Z lookup table, with a LabVIEW plugin. It is MIT-licensed on GitHub, last commit May 2021. The paper reports 228 beads at 58 Hz with about 1 nm SD and precision near the Cramér–Rao bound. It also reported a previously unknown Z bias.

### Cited Findings
- The abstract describes a scalable, open-source CUDA framework. QI lets it track hundreds of beads in real time on consumer hardware, with scatter near the Cramér–Rao lower bound. It studies the trade-off between speed, ROI size and bias, and reports a previously unreported bias along the optical axis. The demo tracked 228 DNA-tethered beads at 58 Hz with about 1 nm SD — [VU research portal abstract](https://research.vu.nl/en/publications/an-optimized-software-framework-for-real-time-high-throughput-tra/)
- Repo `jcnossen/qtrk`: README "Fast spherical bead localization using C++/CUDA, Labview plugin provided. License: MIT". Created 2014-08-18, last commit 2021-05-24. Top-level folders: `cputrack`, `cudatrack` (with `QueuedCUDATracker.cu`, `QI.h`, `QI_impl.h`, `cudafft`), `lv`, `QTrkDotNet`, `RTTracker`, `OfflineTracker`, `TraceViewer`, `qtrk-pub` — [GitHub qtrk](https://github.com/jcnossen/qtrk)
- Companion repo `jcnossen/BeadTracker`: "Complete magnetic tweezers setup code in LabView as used in the Nynke Dekker Lab ... using qtrk". No license file detected by the API; last push 2016-02-19 — [GitHub BeadTracker](https://github.com/jcnossen/BeadTracker)
- A later Leiden phasor paper describes QI as minimising x/y/z cross-talk but computationally heavy — [bioRxiv 763706](https://www.biorxiv.org/content/10.1101/763706.full.pdf) (search snippet only, not read in full)

### Inferences
- QTrk is the most complete open reference for QI, the ZLUT and the GPU queue design. It is MIT-licensed, so porting its algorithms to numba/CUDA is legally clean with attribution.
- Using it as a drop-in stage from Python would mean building its DLL (MSVC + CUDA) and calling it through ctypes. That is possible but carries build risk, since the code dates from 2014–2021. An RTX 2060 (Turing, sm_75) needs a recent CUDA toolkit, and the old vcxproj files would need updating (UNVERIFIED).

### Gaps
- Per-ROI CPU vs GPU throughput tables and the size of the Z bias: the Dekker lab PDF host refused connection (ECONNREFUSED). UNVERIFIED.
- The 228 beads x 58 Hz figure was camera-limited, not the tracker's maximum; I could not confirm the tracker's peak beads/s.

## Huhle et al. 2015 (Seidel lab), Dulin lab / Ostrofet 2018

### Takeaway
Huhle et al. (Nat Commun 6:5885, 2015) did real-time kHz tracking with XY from mirror-profile correlation on the CPU and Z from a radial-profile calibration table on a GTX 480. It reached up to 3 kHz for 2 beads and 26 beads at 420 Hz. The code is CUDA C + LabVIEW with no public repository. The Dulin lab (Ostrofet, Papini, Dulin, Sci Rep 2018) uses custom LabVIEW software built on the Cnossen 2014/QTrk framework, with CPU or GPU (GTX 1080). No code was released.

### Cited Findings
- Huhle 2015: XY by "correlating linear bead intensity profiles with their mirror profiles" (CPU); Z by comparing the radial profile to "a pre-recorded profile calibration table"; GPU GeForce GTX 480 in a Dell T7500 with 2x6-core CPUs; Mikrotron EoSens CL MC1362 at 1280x1024, 500 Hz; ROI 160x160 (high-resolution mode) or 72x72 (multi-bead mode); 26 beads at 420 Hz; up to 3 kHz for two particles, equal to 150 MB/s; GPU code in CUDA C as a DLL, acquisition in LabVIEW 2010 64-bit; an offline tracker is downloadable from the author's webpage, with no license or URL given — [PMC4338538](https://pmc.ncbi.nlm.nih.gov/articles/PMC4338538)
- Huhle 2015 abstract: 3 Å steps resolved at 10 Hz on fixed particles, 5 Å at 1 Hz on DNA-tethered particles, 20 particles in parallel — [doi 10.1038/ncomms6885](https://www.doi.org/10.1038/NCOMMS6885)
- Ostrofet 2018: "custom software (LabView 2016)", citing Cnossen 2014; CPU or GPU 3D tracking; GPU GeForce GTX 1080; Dalsa Falcon2 4096x3072 camera with a PCIe-1433 frame grabber; 10 Hz default, 1720 Hz in some validation runs; data available on request, no code release — [PMC6206022](https://pmc.ncbi.nlm.nih.gov/articles/PMC6206022)
- Ostrofet 2018 correction: the shutter time should be at most 1/4 of the bead's characteristic time — [PMC6287096](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6287096/)

### Inferences
- The Seidel design (XY on CPU, Z on GPU, LabVIEW host) is close to the current Kim lab LabVIEW structure and is a published precedent for splitting work between CPU and GPU.
- Latency is not reported by either group. Only throughput is.

### Gaps
- No public code was found for the Seidel or Dulin lab software. The Seidel "author's webpage" download was not located. I found no software release from the Depken lab (theory group).
- The Leiden FFT-phasor tracker (bioRxiv 763706) was only seen as a search result; its code and license are UNVERIFIED.

## MagTrack and MagScope (London ... Fishel, bioRxiv 2025)

### Takeaway
MagTrack is a GPL-3.0 Python library (NumPy/SciPy, optional CuPy) that runs the same code on CPU or GPU. Its default pipeline is COM, then auto-conv, then 5 iterations of multiline auto-conv sub-pixel, then radial profile and LUT `lookup_z`. MagScope is a PyQt6 multiprocessing acquisition app built on it. Both reached v1.0.0 on 2026-09-15 and are actively maintained. MagTrack's `qi` is quadratic interpolation, not QTrk's quadrant interpolation.

### Cited Findings
- Preprint "A Python framework for magnetic tweezers real-time image processing and microscope control" (the PDF title reads "An Accessible Python Framework for Real-Time Magnetic Tweezers Microscope Control and Image Processing"). Authors James A. London, Abhishek K. Singh, Teague C. Svendsen, Naciye Esma Tirtom, Zachary A. Root, Richard Fishel (corresponding), Ohio State University Wexner Medical Center. Posted 2025-11-03, doi 10.1101/2025.10.31.685671. The preprint itself is CC-BY-NC-ND 4.0 — [bioRxiv](https://www.biorxiv.org/content/10.1101/2025.10.31.685671v1)
- A search snippet says the preprint was "published in 2026"; I did not identify the journal (UNVERIFIED) — [search result: hebis record](https://ubmr.hds.hebis.de/EdsRecord/cmedm%252C41279331)
- MagTrack repo: GPL-3.0, created 2025-03-11, release v1.0.0 2026-09-15, 4 stars. README: sub-pixel XYZ, optional GPU, "Only depends on NumPy, SciPy, and CuPy", Windows/macOS/Linux — [GitHub MagTrack](https://github.com/7jameslondon/MagTrack)
- PyPI `magtrack` 1.0.0 (uploaded 2026-09-15): requires numpy>=1.26 and scipy>=1.11.1, with extras `cu11` / `cu12` / `cu13` pulling cupy-cuda11x/12x/13x — [PyPI magtrack](https://pypi.org/project/magtrack/)
- `magtrack/core.py` functions: `center_of_mass`, `auto_conv`, `auto_conv_sub_pixel`, `auto_conv_multiline`, `auto_conv_multiline_sub_pixel`, `qi` ("Refine centers using quadratic interpolation along x and y axes"), `radial_profile`, `fft_profile`, `fft_profile_with_center`, `lookup_z` (best-matching LUT column, then a local fit of n_local=7 points), `stack_to_xyzp`. The docstrings say the code follows whichever device the input array is on. The `stack_to_xyzp` docstring gives the default pipeline as COM, then auto_conv, then 5 iterations of auto_conv_multiline_sub_pixel, then radial_profile, then lookup_z — [core.py](https://github.com/7jameslondon/MagTrack/blob/master/magtrack/core.py)
- The repo's speed benchmark (`benchmarks/speed/logs/windows-13th_gen_intel_i7_13700-nvidia_geforce_rtx_3070/20251121T213429Z/results.json`) reports mean time per call (100 repeats), CPU vs GPU: center_of_mass 306 vs 49 ms; auto_conv 9.0 vs 4.3 ms; auto_conv_multiline_sub_pixel 42.8 vs 12.3 ms; auto_conv_sub_pixel 9.4 vs 16.3 ms; qi 1654 vs 39.5 ms; radial_profile 2728 vs 17.8 ms; fft_profile 1809 vs 21.1 ms; lookup_z 0.14 vs 8.6 ms — [results.json](https://github.com/7jameslondon/MagTrack/tree/master/benchmarks/speed/logs). The workload (n_images, size_px) comes from the benchmark config and I did not read it, so these cannot be turned into beads/s.
- Other benchmark logs exist for an Apple M4, an i5-1250P (no GPU) and an i5-6600K + GTX 1080 — same folder. The repo also has `benchmarks/language/` (center-of-mass in C, C++, Rust, MATLAB, Python) and an accuracy sweep on simulated beads (`benchmarks/accuracy/`).
- MagScope repo: GPL-3.0, created 2025-03-11, v1.0.0 2026-09-15. GUI, demo with simulated camera, scripted automation, XY- and Z-lock, CPU or GPU tracking via MagTrack. PyPI deps: PyQt6, h5py, tifffile, magtrack>=0.7, optional cupy-cuda12x/13x>=14 and `microscope` (python-microscope) — [GitHub MagScope](https://github.com/7jameslondon/MagScope); [PyPI magscope](https://pypi.org/project/magscope/)
- The bioRxiv landing page has no quantitative benchmark and no comparison with QTrk/LabVIEW. It says most labs automate acquisition in LabVIEW and that no open, general-purpose framework existed — [bioRxiv](https://www.biorxiv.org/content/10.1101/2025.10.31.685671v1)
- Name clash: `bam-lab/magtrack` (Apache-2.0, 2019, cell-analysis scripts, last commit 2019-09-11) is unrelated — [GitHub bam-lab/magtrack](https://github.com/bam-lab/magtrack)

### Inferences
- MagTrack is the nearest existing Python stage for our design: array-API style, batch (n_px, n_px, n_images) stacks, CuPy on the GPU. An RTX 2060 would use `cupy-cuda12x`. Small kernels like `lookup_z` are slower on the GPU (8.6 vs 0.14 ms), so per-call overhead matters for low-latency live use. A numba or a fused-kernel design could beat it.
- GPL-3.0 means that importing MagTrack and distributing the result makes our tracker GPL. Using it as a numeric reference or a test oracle (comparing X/Y/Z on the same frames) does not carry that obligation.
- The XY method (auto-convolution = mirror correlation) matches Gosse–Croquette and the reference LabVIEW VI family. It may be close to our original's computation, but this is unverified and must be checked numerically under rule 1a.

### Gaps
- Paper benchmarks (beads x fps, latency, precision vs simulation): the full-text PDF fetch hit HTTP 429 twice. UNVERIFIED.
- The benchmark workload size was not read, so the per-call times are not normalised to beads/s.

## Other tools (pyMT, TweezPal, Xvin/PicoTwist, Micro-Manager, others)

### Takeaway
Apart from the above, I found no maintained open-source MT image-tracking package. Tweezepy is calibration only. Xvin (Croquette lab / PicoTwist) and TweezPal turned up no public repository in GitHub search, and "pyMT" returned nothing. Several small lab repos exist, mostly unlicensed analysis scripts.

### Cited Findings
- Tweezepy: "Single-molecule force spectroscopy calibration", GPL-3.0, repo updated 2026-04-13, PyPI 1.2.7 (2024-02-22), deps autograd/numpy/scipy — [GitHub tweezepy](https://github.com/ianlmorgan/tweezepy)
- `gh search repos` for "xvin", "tweezpal", "pymagtweezers", "quadrant interpolation", "phasor bead tracking" and "magnetic tweezers tracking cuda" returned no relevant repos (checked 2026-10-22). A web search on Xvin/PicoTwist also found nothing — [search session; no URL]
- Other GitHub "magnetic tweezers" repos: `ShonLab/Magnetic-Tweezers` (MATLAB, no license, updated 2026-05-05); `brauchilab/MagneticTweezers` (C++, MIT, last push 2022-03-17); `RTR-Lab/Magnetic_Tweezers_Acquisition_Software_v1.0_2026` (C++, no license, 2026-01-21); `ursaursic/magnetic_tweezers_brugueslab` (notebooks, MIT); `svandersmagt/MT-Force-Calibration` (MATLAB, 2017); `tyyoonlab-snu/Magnetic-Tweezers-*` (MATLAB analysis, SNU Yoon lab, no license) — [GitHub search "magnetic tweezers"](https://github.com/search?q=magnetic+tweezers&type=repositories)
- `dnbornl/beadtracking`: a MATLAB toolbox for fluorescent microbead tracking, not MT diffraction-ring tracking — [GitHub](https://github.com/dnbornl/beadtracking)

### Inferences
- The realistic options for our Python tracker are: (a) port the algorithms from QTrk (MIT) and from the reference LabVIEW VI; (b) use MagTrack (GPL) as an independent numeric cross-check; (c) borrow MagScope's multiprocessing architecture as a design pattern.

### Gaps
- Xvin (Croquette, ENS/LPS) is believed from memory to be a C program for PicoTwist instruments, but I found no public repository or license. UNVERIFIED.
- TweezPal and "pyMT": no source found. Micro-Manager MT plugins: not searched (out of tool budget).
- brauchilab/MagneticTweezers and RTR-Lab: algorithms not inspected.
