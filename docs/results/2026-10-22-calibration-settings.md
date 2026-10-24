# Calibration settings (band-pass, forget radius): offline sweep and a survey of past recordings (2026-10-22)

The owner suspected that z noise grew after the switch from the 100x to the 50x objective, and that the two settings
chosen at calibration time (band-pass range, forget radius) are not tuned for 50x.

## Phase 4a: the cluster is built from the `.cal` file
`mtpy/calib.py` builds what LabVIEW's loader hands the kernel (windows, cosine band-pass, real / amplitude /
corkscrew per slice) from the `.cal` alone. It is ported from MT_LabVIEW's CUDA v3 loader. Against LabVIEW's own
cluster for `cal002`, the arrays differ by up to 6.7e-7 (the same as the CUDA port). Tracking with this cluster
matches LabVIEW within 4.9e-7 px and 3.5e-6 um on 520 bead-frames (`tests/test_calib.py`).

The `.cal` stores three integers per bead: (LOW, HIGH, forget). LOW and HIGH are the band-pass range in frequency bins
of the 119-point mirrored profile; forget is in pixels. The raw radial-profile stack is stored before the band-pass,
so both settings can be changed offline. Cross size cannot: the stack is built for 120 px.

## Sweep on the recorded fixture (`tools/sweep_calib.py`)
Input: the first 5 000 frames of the 50x fixture (`...\test`, 90 Hz), re-tracked with the main VI's frame-to-frame
rule. 511 settings: LOW 0-6, HIGH 13-49, forget 4-31 (the same setting for every bead). Measures:
- **reference-bead z noise:** std of successive differences / sqrt(2), bead 1;
- **interpolation test:** the cluster is built from the even slices and each odd slice is looked up (true z halfway);
  this uses no images.

| Setting (LOW, HIGH, forget) | Ref. bead z noise | Tethered beads 2-5 | Interpolation RMS / max |
|---|---|---|---|
| stored in the file (0, 25, 23) | **4.26 nm** | 17.1 / 18.1 / 16.8 / 10.5 nm | 5.2 / 17.4 nm |
| (0, 46, 10) | 3.57 nm | 15.9 / 17.0 / 15.7 / 8.8 nm | 4.7 / 16.5 nm |
| (0, 34, 19) | 3.57 nm | 16.0 / 17.2 / 15.8 / 9.0 nm | 4.8 / 15.8 nm |

- **HIGH 25 is too low for 50x.** Noise falls as HIGH rises and is flat from about 28-31 on (best per HIGH: 19 -> 4.38,
  22 -> 3.85, 25 -> 3.64, >= 31 -> about 3.57 nm).
- **forget about 10 or about 19 is best;** 25 and above is worse (28 -> 4.47, 31 -> 5.54 nm).
- **LOW 0-4 makes no difference.**
- No setting in the good region lost a bead. The interpolation test barely changes (RMS 4.7-5.2 nm), so the gain is
  noise rejection on real images, not better interpolation between slices.

## Survey of past recordings
Read-only, about 900 dated recordings under `G:\Data\SiHyeong` (file `-000` of each series, the first 20 000 rows; the
reference bead taken as the bead with the smallest z noise). Per-day medians:

| Period | Ref. bead z noise per frame | Ref. bead x noise | HIGH | forget |
|---|---|---|---|---|
| 2025-03 to 2025-09 (100x, inferred) | mostly 1.0-1.8 nm | about 0.013 px (about 1.1 nm at 84 nm/px) | 25 | about 35-42 |
| from 2025-09-26 (50x) | mostly 3-6 nm | about 0.010 px (about 1.7-2 nm at 168-200 nm/px) | 25 | about 17-24 |

- The step at about 2025-09-26 matches the lens change (a file of 2025-09-29 records 200 nm/px).
- forget was halved at the change (the same physical radius); HIGH was kept at 25.
- **The tuning above recovers about 16 %; the 3-4x step is mostly physical** (fewer pixels per bead, depth of field),
  consistent with the XY noise in nm also growing 1.5-2x.

## Limits
- The sweep uses one 50x recording with one reference bead; the best setting may be specific to it.
- The survey compares runs with different samples, frame rates and exposures; "reference bead" is inferred per file.
- Untested levers that need a new calibration on the rig: cross size (120 px at 50x covers twice the area of 100x),
  z step, illumination and exposure.
- An improvement must be confirmed on the rig: the same sample calibrated with the stored and the new settings,
  alternating.
