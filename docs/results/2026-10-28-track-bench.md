# Tracking alternatives on the reference-bead z-scan (2026-10-28, offline; decision 0023 item 4, phase 10b)

Every method ran on the **same frames**: the 2026-10-26 z-scan (8 fixed beads, 101 slices of 100 nm over +-5 um,
30 frames per slice at 150 Hz, 160 px crops). Each method built its own LUT from the first half of every slice's
frames and was tested on the second half. `current` is the LabVIEW method (the phase-3 port). Numbers from
`tools/track_bench.py`; full table in `2026-10-28-track-bench.json`. 203 nm / px.

Measures: **xy / z noise** = per-slice scatter of the difference of two beads / sqrt 2 (common motion removed), median
over the 28 pairs and 101 slices; **z error** = rms of the slice-mean z against the commanded z over +-4 um, offset
removed; **time** = per bead and frame, numpy (the current method's production figure is its numba version).

## XY stage and radial-profile stage

| XY | radial | xy noise x / y (nm) | t_xy (ms) | t_rad (ms) |
|---|---|---|---|---|
| **current** | **current** | **2.76 / 2.90** | 0.80 | 0.71 |
| current | polar3 | 2.76 / 2.90 | 0.88 | 5.18 |
| current | area4 | 2.76 / 2.90 | 0.93 | 13.09 |
| qi | current | 2.60 / 2.92 | 2.50 | 0.59 |

- **QI** changes the xy noise within the scatter (x -6 %, y +1 %) and costs 3x the time. On fixed beads it buys
  nothing. Its known strength (pixel bias on moving beads) is not visible in this test.
- **polar3 / area4** change neither the xy nor the z noise (next table), as in the 2026-10-24 synthetic test, and cost
  7x / 18x the time.

## Z stage (all with LOW 0 / HIGH 40 / forget 10 unless stated)

| XY + radial | Z | z noise (nm) | z error (nm) | slope | t_z (ms) |
|---|---|---|---|---|---|
| current + current | **LabVIEW panel LUT 0 / 25 / 20** | 7.26 | 8.4 | 1.0001 | 0.12 |
| current + current | current | 4.76 | 7.7 | 1.0001 | 0.12 |
| current + current | **spline** | **4.47** | **4.9** | 1.0000 | 0.73 |
| current + current | phase_spline (2026-10-29) | 4.66 | 4.9 | 1.0000 | 0.98 |
| current + current | phasor | 9.57 | 129 | 1.0000 | 0.06 |
| current + polar3 | current / spline | 4.74 / 4.48 | 7.7 / 4.9 | 1.000 | |
| current + area4 | current / spline | 4.71 / 4.47 | 7.7 / 4.9 | 1.000 | |
| qi + current | current / spline | 4.72 / 4.53 | 27.1 / 14.8 | 1.000 | |

- **The biggest single gain is still the LUT setting of decision 0022:** 7.26 -> 4.76 nm noise with the same
  method.
- **`spline` z (continuous LUT, SSD minimised; Kovari 2019 in spirit)** keeps the noise (4.47 vs 4.76 nm) and cuts
  the **z error from 7.7 to 4.9 nm**: the bias between the 100 nm slices is smaller than with the 5-slice phase fit.
  Nothing else gets worse except the numpy time (0.73 vs 0.12 ms per bead), which a numba version removes. It is
  the one candidate that meets 0023 item 4 on this data.
- **`phase_spline`** (added 2026-10-29, owner's question: is the gain the interpolation or the SSD criterion?) keeps
  the current method's phase criterion but interpolates the complex LUT along z and brings the weighted phase
  difference to zero by bisection instead of the 5-point quadratic fit. Its z error is the same as `spline`'s
  (4.9 nm) and its noise sits between the two (4.66 nm). So the bias of the current method comes from the
  5-point quadratic root finding, not from the phase criterion; the continuous LUT removes it either way, and the
  SSD fit is slightly quieter and cheaper (0.74 vs 0.98 ms numpy).
- **`phasor`** (one frequency's phase) is far worse (9.6 nm, 129 nm error): the current method already uses the
  whole band's phase, and a single frequency is not monotonic over +-5 um.
- **QI + any Z** gives 3-4x the z error (27 nm) at the same noise: the QI centre moves with defocus relative to the
  current method's centre, and the radial profile follows it. Not diagnosed further; QI is not a candidate for z here.

## What this means
- Keep the current XY and radial stages.
- `spline` z is worth a numba port and a test on tethered beads (the prepared `tether` plan,
  [rig/tethered-calibration-protocol.md](../rig/tethered-calibration-protocol.md)) before any decision to adopt it.
- One recording, one sample, fixed beads only. Moving beads (pixel bias, XY -> Z crosstalk) are the open case, and
  the one where QI and polar3 were expected to help.
