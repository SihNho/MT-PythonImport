# Reference beads tracked repeatedly with every tracker, on the rig (2026-10-31)

Owner's instruction (evening, 2026-10-31): a dry channel with reference and magnetic beads is mounted and in focus
("고립된 bead는 reference bead로 보임"; "무엇보다, 해당 채널은 물이 다 말라 있는 상태"); track the same reference bead
several times, check every method, the piezo coupling, frame loss and accuracy; the EMCCD is powered.
Everything ran through the program's own API with the program holding the rig lock (decision 0026), MT-TIRF mode,
backend `real-motors`: [tools/rig_refbead_track.py](../../tools/rig_refbead_track.py) (session) and
[tools/rig_refbead_analyze.py](../../tools/rig_refbead_analyze.py) (offline). Raw data: `G:\l2s_rig_data\2026-10-31_refbead_track\`
(19 HDF5 runs, `cal_refbead`, `frame.npy` / `frame.png`, `report.json`, `analysis.json`); the analysis is copied to
[2026-10-31-refbead-track.json](2026-10-31-refbead-track.json). Motion: focus only (a +-3 um scan and +-1 um steps). The
magnet and the stage did not move.

## Session
| step | result |
|---|---|
| Connect (MT-TIRF, 8 devices) | 20.3 s, 8 / 8 connected; iXon found at 14 C, cooler off (powered on by the owner, never cooled) |
| bead finding | the V6 bead-map finder found 0 isolated beads: it expects a dark disk, and this dry channel's beads are ring patterns (`frame.png`). 4 isolated single beads were picked by hand from the averaged frame, far from the magnetic clusters, centres refined by the tracker's XY stage: (760.4, 268.7), (984.4, 623.9), (373.4, 853.7), (372.4, 297.0) px. Bead 1 is "the" reference bead; 2-4 are controls |
| z scan | 60 slices x 100 nm, 10 frames averaged per slice, 8 s; focus back at 0.000 um; `.cal` with (LOW, HIGH, forget) = (0, 40, 10) |
| tracking runs | 6 trackers (Z `current` / `spline` / `phase_spline`, each on numba and on the CUDA kernel) x 3 repeats x 20 s at 90 Hz = 18 runs, recorded; then one 45 s run with piezo steps |
| Disconnect | clean in 2.0 s (iXon warm: no warm-up wait); rig lock holder null after |

A first attempt 2 minutes earlier (same connect / disconnect, 24 s / 1.5 s) ended in the z scan: the finder's empty
list was scanned and `write_cal` crashed on a (0, 2) array. `gui/zscan.run` now refuses an empty pick list before any
focus move (test `test_zscan_refuses_an_empty_pick_list`).

## Frames and timing (all 19 runs)
- **No frame lost:** camera gaps 0, pipeline drops 0, tracking errors 0, sink failures 0 in every run; 1799-1800 frames
  per 20 s run, 4086 in the piezo run; measured rate 89.97 Hz.
- Tracking time per frame, 4 beads (p50 / worst p99 over the 3 repeats):

| tracker | numba p50 / p99 (ms) | CUDA p50 / p99 (ms) |
|---|---|---|
| current (band-pass + 5-slice phase fit) | 0.35 / 5.4 | 1.99 / 3.0 |
| spline | 0.34 / 1.1 | 2.01 / 2.6 |
| phase_spline | 0.46 / 4.8 | 2.18 / 2.6 |

  The CUDA kernel's p50 is 6x the numba one for 4 beads (launch overhead; its p99 is tighter). Both are far below the
  11 ms frame period. Same picture as the offline benchmark (decision 0024: numba stays the default).

## Noise and repeatability (203 nm / px, decision pending; z from the LUT)
Differential noise = std of the difference of two beads / sqrt 2 per run (common motion removed), median over the 6
pairs and 3 repeats. Spread = std over the 3 repeats of bead 1's 20 s mean position.

| tracker | dx / dy / dz noise (nm) | bead 1 z mean per run (um) | spread of the run means x / y / z (nm) |
|---|---|---|---|
| current numba | 5.0 / 7.8 / 11.8 | 3.115, 2.994, 2.993 | 33 / 17 / 57 |
| current CUDA | 5.0 / 7.9 / 12.1 | 2.989, 2.976, 3.023 | 10 / 7 / 20 |
| spline numba | 4.9 / 7.7 / 11.4 | 3.077, 3.012, 3.050 | 7 / 7 / 27 |
| spline CUDA | 5.0 / 8.1 / 12.4 | 2.975, 3.011, 2.922 | 38 / 17 / 36 |
| phase_spline numba | 5.1 / 7.7 / 12.0 | 2.974, 2.964, 2.977 | 2 / 24 / 6 |
| phase_spline CUDA | 5.7 / 10.3 / 12.7 | 2.979, 2.965, 2.872 | 42 / 21 / 48 |

- **The six trackers agree:** 5 nm in x, 8 nm in y, 12 nm in z per frame on this dry sample for every method
  (phase_spline on CUDA is slightly worse in y). The 2026-10-26 wet sample gave 2.5-3 nm in xy; the dry channel's ring
  patterns have less contrast (local mean 80-90 of 255 grey levels, ring 7 grey levels above background).
- **The run-to-run spread (up to 57 nm in z, 40 nm in x) is drift of the sample, not the tracker:** the whole field
  moved by 2.7 px (0.55 um) in x between the first run (23:27) and the piezo run (23:33), and z drifts 50-60 nm per
  45 s (below). Repeats of one method were 20 s apart, different methods minutes apart, so the spread follows the
  clock, not the method.
- No bead was lost in any run (lost count 0 for every bead).

## Piezo coupling (run `piezo_current_numba`, tracker `current` on numba)
Focus steps of 0, +0.5, +1, +0.5, 0, -0.5, -1, -0.5, 0, then +0.1 ... +0.5 and 0 um, 3 s each; the ASI read back
every target exactly. Mean tracked z of each 3 s hold (first 0.8 s dropped), bead 1:

| commanded (um) | 0 | +0.5 | +1.0 | +0.5 | 0 | -0.5 | -1.0 | -0.5 | 0 | +0.1 | +0.2 | +0.3 | +0.4 | +0.5 | 0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tracked z (um) | 2.877 | 3.363 | 3.949 | 3.337 | 2.820 | 2.247 | 1.774 | 2.285 | 2.826 | 2.920 | 3.068 | 3.111 | 3.208 | 3.224 | 2.734 |

- **Tracking follows the piezo:** linear fit slope 1.04-1.06 for the four beads, rms residual 49-55 nm; the 1 um steps
  come out as 1.07 (up) and 1.05 (down) um.
- **Zero drift:** the five returns to 0 scatter by 51-57 nm (std) over 45 s, monotonic downward (2.877 -> 2.734 um):
  about 60-70 nm/min of focus drift, more than the 30-46 nm/min of 2026-10-26.
- **The 100 nm steps are irregular:** +43, +148, +43, +97, +16 nm between consecutive holds. Drift accounts for about
  -5 nm per hold only. Either the piezo's small steps are irregular (the 2026-10-26 report already suspected this)
  or the LUT is uneven at this scale.
- **Why the slope is above 1:** the LUT was scanned at 8 s for 60 slices (10 frames = 0.11 s per slice, no settle
  time), while the 2026-10-26 scan (0.2 s hold) gave slope 1.000 in its self-check. If the focus had not fully
  arrived when the frames were averaged, the LUT's slices are effectively closer than 100 nm and tracked z reads
  about 5 % too large. **Proposal:** a settle time per slice in `gui/zscan.run` (the GUI's default of 20 frames
  already gives 0.22 s) and a check of the piezo step against the LUT with a slower scan. **Done 2026-11-01** (owner
  "0.2초로 넣어"): `zscan.run(settle_s=0.2)` default, a Calibrate field; the slope check with a new LUT is still to run.

## iXon (item 2 of the owner's list)
Open found the camera at 13-14 C with the cooler off (as the owner left it after powering on); nothing was adopted as
a set point, `found_at_open` recorded. Close took 1.5-2.0 s: sensor warm, so no warm-up wait, CoolerOFF + ShutDown.
The open-cold / warm-up path of 2026-10-30/31 was not exercised today (the camera was never cooled); a connect that
sets a cold set point and then disconnects is the remaining check.

## What this does not show
- Absolute accuracy: no independent length standard; z is LUT-defined, xy in px (203 nm / px assumed).
- The wet-sample noise floor (2.5-3 nm); this channel is dry.
- The XY stage alternative (`qi`) and the radial-profile alternatives run only offline (`tools/track_bench.py`).
- Bead finding on a ring-shaped (dry) bead image: the V6 finder does not work here; the GUI's click-to-pick does.
