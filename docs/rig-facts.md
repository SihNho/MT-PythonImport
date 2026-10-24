# Rig facts from the owner

Facts about the rig and the samples that the code cannot tell us. Each line gives its source and date. When a fact
changes, add the new line with its date and keep the old one marked "superseded".

## Optics and camera

| Fact | Value | Source |
|---|---|---|
| Camera | JAI SP-5000M-USB (USB3 Vision, via NI-IMAQdx `cam1`), 1280 x 1024 used (binning 2) | owner 2026-10-22; V6 `docs/instrument-libraries.md` |
| Sensor pixel | 5.0 x 5.0 µm (2560 x 2048, Lince5M) | JAI product page, accessed 2026-10-22 |
| Microscope / JAI position | Olympus **IX73**; the JAI sits at the turret position directly below the objective (owner 2026-10-24: "현재 JAI 위치는 IX73 현미경 시스템 상에서 렌즈 바로 밑에 위치한 터렛."). Its own tube lens and focal length: not yet recorded | owner 2026-10-24 |
| Objective | **50x oil immersion** since the field of view was widened; **100x oil** before | owner 2026-10-22 |
| Image pixel, nominal | 5.0 µm x 2 (binning) / 50 ≈ **200 nm/px** (assumes the objective's matching tube lens) | computed 2026-10-22, not measured |
| `pixel distance (nm)` in the calibration file | **84 nm/px** (last DBL of the `cal002` tail; also the panel default) — stale, from the 100x objective | `cal002`; `spec/3-calibration.md` F3.01; owner 2026-10-22 |

**84 nm/px is a value left from the 100x objective** (owner 2026-10-22: "예전 렌즈 사용할 때 기록인듯. (100X)"), so it
is stale for 50x data. Note: 100x with binning 2 is 100 nm/px nominally, not 84; if 84 was measured, the real
magnification is about 1.19x the nominal one, and the same ratio would put 50x at about **168 nm/px** rather than 200.
Both figures are inferences; **measure the 50x pixel size** (stage micrometer, or move the ASI stage by a known
distance and track a stuck bead) before converting pixels to nm. **LabVIEW does not use this number**: tracking
works in pixels, and analysis is done in MATLAB with its own parameters (owner 2026-10-22, Q3.07).

## Samples

| Fact | Value | Source |
|---|---|---|
| Reference beads | Every measurement includes **non-paramagnetic streptavidin polystyrene beads** stuck to the surface, used as the reference | owner 2026-10-22 |
| Magnetic beads | **M-270 amine** (Dynabeads, 2.8 µm diameter) | owner 2026-10-22 |
| Sample | nucleosomes (owner's current work); extension varies by condition, about 800-1400 nm | owner 2026-10-22 |
| Focal-shift (refractive-index) factor | 0.88 in use, believed to be the oil-to-water correction; source (assumed or measured) not recorded | owner 2026-10-22 |
| "16X" in data folder names | the **DNA construct's name**, not a magnification | owner 2026-10-22 |

## Calibration (z look-up table)

| Fact | Value | Source |
|---|---|---|
| Slice step | 100 nm | owner 2026-10-22; `cal002` (0.1 µm) |
| Range used | about 6 µm (60 slices) | owner 2026-10-22; `cal002` |

## The recorded fixture (`G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch\test`)

Taken with the **50x** objective (owner 2026-10-22). From the original program's own output `tra002-000`
(10 043 frames at 90 Hz; frame-to-frame noise = standard deviation of successive differences / √2; computed
2026-10-22):

| Bead | z range | x noise per frame | z noise per frame | Reading |
|---|---|---|---|---|
| 1 | 0.21 µm | 0.0085 px | 4.1 nm | **reference bead** (does not follow the magnet; the 0.21 µm is drift over ~112 s) |
| 2, 3, 4 | 2.0-2.2 µm, follows the magnet (r = 0.93) | ~0.10 px | ~12 nm | DNA-tethered |
| 5 | 3.7 µm | 0.067 px | 14.8 nm | tethered; leaves the stack range at the end |

Bead 1 is identified from the data (it does not follow the magnet ramp), not from the click order.
