# 2026-11-01 20:06-20:59: accuracy under motion x frame rate x bead count x z method x executor (script alone)

Owner: "now the accuracy test, per method, frame rate and bead count: frame loss and processing time, alone and
under the GUI; not standing still - step the piezo, compare each bead raw and after reference-bead correction, and
move the magnet too; test the maximum frame rate, and the maximum of a half-size ROI". Tool: `tools/rig_accuracy.py`
(script mode; `tools/gui_rig_isolate.py STEPS=1` is the GUI mode, not run tonight - owner 20:55: "do not run, list the
benchmarks first"). Data: `G:\l2s_rig_data\2026-11-01_accuracy{,150,_max,_roi}`.

## What one run is
The owner's four beads (1, 13, 11, 8 of the 15:02 frame; copies fill the count), a recorded run at the given rate
while the focus steps 0, +0.5, +1, 0, -1, 0 um (hold 2 s) and then the magnet moves 0, 10, 30, 0 mm (hold 2 s).
Per frame rate a fresh LUT (60 x 100 nm, 10 frames averaged, 0.2-s settle) made at that rate and exposure, after
re-finding the beads on the live frame (they drift: 15 px at 20:06, 22 px at 20:39 from the 15:02 positions, the
same shift for all four = stage drift about 15 px/h).
- **frames, gaps, drops, track ms** median / std / slowest 1 % / max: the pipeline status.
- **focus raw**: each bead's z change from the first hold against the commanded step; **focus ref**: the same after
  subtracting bead 1 (all beads move together, so the corrected change must be 0); median / max |error| in nm over
  beads 2-4 and the five holds. The first 0.5 s after the controller reports arrival is skipped.
- **magnet raw / ref**: the beads' z shift between the magnet holds (stuck beads: must be 0), raw and corrected.
- **noise**: median per-hold std of a bead's z. **lost**: frames in holds with a bead flagged lost / not good
  (beads 1-4). **follow**: time from the move's arrival report until the beads' median z is within 50 nm of the
  hold mean (piezo settle + tracking), median / max over the non-zero focus steps.

## Summary per frame rate (18 runs each: 5 / 10 / 20 beads x current / spline / phase_spline x numba / GPU)
| rate (ROI) | frames / run | drops (runs with drops) | track ms median, numba / GPU | p99 numba / GPU | focus raw / **ref** (median, nm) | magnet raw / **ref** | noise nm | follow ms |
|---|---|---|---|---|---|---|---|---|
| 90 Hz (full) | 2250 | **0** (0 / 18) | 0.40-0.91 / 2.07-2.44 | 3.2-13.6 / 3.2-4.5 | 5-89 / **1-7** (max 6-52) | 5-88 / **1-10** (max 6-27) | 6-21 | 68-184 |
| 150 Hz (full) | 3750 | **0** (0 / 18) | 0.36-0.91 / 2.09-2.34 | 0.6-2.7 / 3.2-3.7 | 10-119 / **2-33** (max 11-135) | 7-121 / **1-25** (max 10-57) | 4-33 | 67-210 |
| 248 Hz (full, the camera's cap) | 6165 | 40 (2 / 18: phase_spline numba 5 and 20 beads) | 0.34-0.92 / 1.96-2.20 | 0.6-1.9 / 2.5-3.4 | 22-159 / **1-18** (max 14-844, see bead 1) | 18-191 / **2-25** (max 9-86) | 15-35 | 90-266 |
| 555 Hz (640 x 512, the cap at that ROI; exposure 1.62 ms) | 13 850 | **1094** (16 / 18; 8-259 per run, 0.06-1.9 %) | 0.33-1.11 / 1.40-1.66 | 0.5-1.7 / 2.1-2.7 | 7-97 / **2-15** (max 17-130) | 11-105 / **2-9** (max 7-26) | 19-30 | 54-111 |

## Findings
1. **Accuracy after reference correction is a few nm at every rate and method**: focus-step error median 1-7 nm at
   90 Hz, 2-33 at 150, 1-18 at 248, 2-15 at 555; magnet-move shift 1-25 nm. The three z methods and the two
   executors are indistinguishable within the run-to-run scatter.
2. **The raw (uncorrected) error is 5-190 nm and is the rig, not the tracking**: it has the same size whatever the
   method, executor or rate; it disappears after reference correction; and z keeps moving inside a hold (-56..+18 nm
   between 0.5 s and 1.9 s after arrival at 90 Hz, up to +-120 nm at 150 Hz) in a direction that changes from hold
   to hold - drift / creep of the focus drive and the sample, plus the piezo's own step irregularity seen on
   10-31. Lowering the move speed would not remove this; a longer settle wait or the reference correction does.
3. **Overshoot / late correction right after arrival**: the beads' z differs by 10-47 nm between 0.1-0.3 s and
   0.5-0.8 s after the controller reports arrival; the median z enters the 50-nm band 55-270 ms after the report.
   (Owner 20:50: a slower move may shrink this; a speed dimension is on the list below.)
4. **A LUT must be made at the frame rate it is used at.** The 150-Hz block was first tracked with the 90-Hz LUT:
   z read 0.9 um low, noise 3 -> 15 nm, bead 1 flipped between two LUT matches at the -1 um hold (corrected max 290-
   2680 nm, 640-760 lost frames in 11 of 18 runs). Redone with a 150-Hz LUT: offset gone, no lost frames below 20
   beads. The auto exposure read back 1.909 ms at both rates, so the rate itself changes the ring image.
5. **Bead 1 is ambiguous about 1.4 um below the LUT centre**: at 248 Hz the start focus sat lower in the LUT and the
   -1 um hold landed there; bead 1 read ~800 nm high with std 280-450 nm in 7 of 18 runs while beads 2-4 agreed
   (the corrected max 560-844 nm in the table is this). At 90 Hz the same hold was 0.3 um deeper and fine. A
   per-bead LUT-quality check (unique match over the range) belongs in bead selection.
6. **Frame rate costs noise**: per-hold z std 6-21 nm at 90 Hz, 15-35 at 248, 19-30 at 555 (shorter exposure, the
   same light). Lost frames appear at 150 Hz with 20 beads (171-852, bead 4 flickering lost; spline / phase_spline)
   and at 555 Hz (0-777).
7. **Frame loss**: none at 90 / 150 Hz; at 248 Hz only phase_spline on numba drops (9 and 31 of 6165); at 555 Hz
   16 of 18 runs drop 0.06-1.9 % although the tracking median is 0.33-1.1 ms against a 1.8 ms budget and its max
   stays under the budget - the loss is per-frame overhead outside the kernel (frame hand-off, record, display
   copies), to be profiled before 555 Hz is offered.
8. **Processing time**: numba 0.33-0.4 ms at 5 beads, 0.6-1.1 at 20; GPU flat 2.0-2.4 ms (1.4-1.7 in the half ROI).
   Same as the afternoon's; the rate does not change it.
9. **The half ROI**: 640 x 512 at (344, 376) holds beads 2-4 only (the four span 643 px; the 120-px windows need
   72 px of margin), so bead 2 is the reference there; the camera's own cap at that ROI is 554.94 Hz (read from the
   driver, `JaiCamera.limits`), and the exposure had to drop to 1.62 ms to fit the 1.80 ms period. No stage move
   was needed (owner allowed one).
10. **Tooling incidents** (all recovered, rig at its initial condition each time): the first attempt failed because
    the beads had drifted 13 px and one Croquette pass left the radial window out of bounds (now iterated); at 20:32
    bead 2 locked onto a neighbour 31 px left (now: a bead whose shift disagrees with the others' median is retried
    from that median, refused if it still disagrees); the first 248-Hz run received 0 frames in 27 s right after
    the z scan's stop / start (the intermittent IMAQdx no-frame restart seen before; the tool now retries once);
    555 Hz was first refused because the 1.909 ms exposure exceeded the period (safety check worked; the tool now
    shortens the exposure to 0.9 x period for a "max" rate). Killing the 20:32 attempt from outside left the rig
    lock stale; released on the owner's words ("Yes, take it over") at 20:37.

## Not done
- GUI mode of the same matrix (`gui_rig_isolate.py STEPS=1 CLIENT=1 FPS=... COUNT_CALS=...`); the GUI has no ROI
  control and offers 90 / 150 Hz only, so the tool sets ROI and other rates through the API and says so.
- Bead counts 50 / 100, piezo speed (current, current / 10), piezo step sizes 20 / 50 / 100 nm, stage xy steps in
  the same run: the owner's list of 20:55-21:00, see [design/bench-matrix.md](../design/bench-matrix.md).
- The 555-Hz per-frame overhead, the bead-1 LUT ambiguity, the 150-Hz 20-bead lost flicker.

## All runs
`frames` tracked; `gaps / drops`; track ms median / std / p99 / max; nm columns median / max |error|; follow ms
median / max. The 150-Hz rows are the 150-Hz-LUT block (`2026-11-01_accuracy150`); the 555-Hz rows use beads 2-4.

| fps | beads | z method | exec | frames | gaps/drops | track ms med/std/p99/max | focus raw | focus ref | magnet raw | magnet ref | noise | lost | follow ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 90 | 5 | current | numba | 2251 | 0 / 0 | 0.40/1.94/4.31/44.39 | 50 / 129 | 3 / 10 | 14 / 67 | 3 / 20 | 8 | 0 | 141 / 229 |
| 90 | 5 | current | gpu | 2252 | 0 / 0 | 2.23/0.28/3.29/3.82 | 51 / 114 | 4 / 8 | 49 / 119 | 4 / 19 | 6 | 0 | 74 / 113 |
| 90 | 5 | spline | numba | 2254 | 0 / 0 | 0.40/2.28/5.26/55.01 | 34 / 50 | 2 / 6 | 5 / 25 | 5 / 18 | 8 | 0 | 85 / 115 |
| 90 | 5 | spline | gpu | 2252 | 0 / 0 | 2.28/0.70/4.45/19.65 | 16 / 62 | 1 / 6 | 46 / 122 | 6 / 21 | 9 | 0 | 90 / 200 |
| 90 | 5 | phase_spline | numba | 2253 | 0 / 0 | 0.52/1.84/6.70/42.92 | 50 / 105 | 3 / 7 | 13 / 22 | 7 / 20 | 7 | 0 | 123 / 128 |
| 90 | 5 | phase_spline | gpu | 2249 | 0 / 0 | 2.41/0.43/4.00/8.78 | 16 / 79 | 6 / 15 | 32 / 86 | 7 / 14 | 14 | 0 | 103 / 163 |
| 90 | 10 | current | numba | 2256 | 0 / 0 | 0.41/1.32/4.90/40.55 | 21 / 65 | 2 / 16 | 14 / 28 | 2 / 14 | 21 | 0 | 184 / 192 |
| 90 | 10 | current | gpu | 2255 | 0 / 0 | 2.21/0.29/3.32/6.37 | 37 / 78 | 1 / 13 | 32 / 48 | 4 / 9 | 16 | 0 | 113 / 115 |
| 90 | 10 | spline | numba | 2255 | 0 / 0 | 0.40/2.14/4.85/44.34 | 54 / 166 | 3 / 17 | 21 / 100 | 6 / 15 | 16 | 0 | 68 / 463 |
| 90 | 10 | spline | gpu | 2257 | 0 / 0 | 2.22/0.62/3.67/15.14 | 46 / 138 | 4 / 25 | 80 / 103 | 10 / 20 | 20 | 0 | 107 / 279 |
| 90 | 10 | phase_spline | numba | 2253 | 0 / 0 | 0.54/2.67/13.61/51.28 | 24 / 55 | 4 / 23 | 5 / 14 | 2 / 8 | 10 | 0 | 109 / 119 |
| 90 | 10 | phase_spline | gpu | 2258 | 0 / 0 | 2.44/0.37/3.95/8.34 | 32 / 162 | 2 / 17 | 31 / 94 | 2 / 6 | 12 | 0 | 81 / 235 |
| 90 | 20 | current | numba | 2256 | 0 / 0 | 0.70/1.49/6.19/27.40 | 23 / 102 | 3 / 19 | 12 / 56 | 2 / 10 | 12 | 0 | 80 / 165 |
| 90 | 20 | current | gpu | 2258 | 0 / 0 | 2.07/0.54/3.18/15.42 | 48 / 87 | 3 / 19 | 88 / 132 | 1 / 7 | 7 | 0 | 108 / 116 |
| 90 | 20 | spline | numba | 2250 | 0 / 0 | 0.66/1.15/3.17/31.77 | 37 / 89 | 7 / 29 | 30 / 76 | 6 / 16 | 10 | 0 | 86 / 130 |
| 90 | 20 | spline | gpu | 2256 | 0 / 0 | 2.11/0.42/3.25/13.92 | 5 / 26 | 3 / 33 | 17 / 34 | 8 / 20 | 11 | 0 | 96 / 112 |
| 90 | 20 | phase_spline | numba | 2254 | 0 / 0 | 0.91/1.47/4.12/42.68 | 29 / 78 | 2 / 28 | 28 / 44 | 3 / 15 | 13 | 0 | 107 / 134 |
| 90 | 20 | phase_spline | gpu | 2259 | 0 / 0 | 2.28/0.35/3.38/9.70 | 89 / 287 | 3 / 52 | 63 / 144 | 5 / 27 | 21 | 0 | 81 / 213 |
| 150 | 5 | current | numba | 3752 | 0 / 0 | 0.36/0.04/0.55/0.69 | 10 / 47 | 33 / 118 | 121 / 284 | 25 / 54 | 22 | 0 | 88 / 89 |
| 150 | 5 | current | gpu | 3749 | 0 / 0 | 2.11/0.29/3.22/7.46 | 59 / 203 | 5 / 27 | 107 / 164 | 9 / 50 | 26 | 0 | 81 / 612 |
| 150 | 5 | spline | numba | 3744 | 0 / 0 | 0.36/0.05/0.57/0.89 | 90 / 163 | 4 / 18 | 20 / 111 | 5 / 23 | 9 | 0 | 68 / 121 |
| 150 | 5 | spline | gpu | 3749 | 0 / 0 | 2.22/0.44/3.25/13.50 | 21 / 56 | 7 / 50 | 26 / 60 | 9 / 26 | 4 | 0 | 79 / 116 |
| 150 | 5 | phase_spline | numba | 3748 | 0 / 0 | 0.49/1.98/2.66/59.53 | 11 / 60 | 3 / 51 | 8 / 26 | 10 / 57 | 5 | 0 | 86 / 112 |
| 150 | 5 | phase_spline | gpu | 3746 | 0 / 0 | 2.34/0.46/3.71/14.28 | 119 / 319 | 7 / 135 | 44 / 72 | 6 / 41 | 33 | 0 | 73 / 272 |
| 150 | 10 | current | numba | 3747 | 0 / 0 | 0.39/0.34/0.87/12.81 | 75 / 142 | 3 / 73 | 51 / 86 | 4 / 34 | 27 | 0 | 67 / 101 |
| 150 | 10 | current | gpu | 3750 | 0 / 0 | 2.19/0.53/3.30/17.35 | 44 / 70 | 2 / 14 | 59 / 233 | 4 / 32 | 21 | 0 | 91 / 125 |
| 150 | 10 | spline | numba | 3750 | 0 / 0 | 0.38/0.92/2.24/24.04 | 37 / 114 | 6 / 32 | 85 / 160 | 2 / 13 | 20 | 0 | 86 / 122 |
| 150 | 10 | spline | gpu | 3754 | 0 / 0 | 2.16/0.33/3.40/5.90 | 64 / 130 | 3 / 77 | 61 / 158 | 5 / 15 | 22 | 0 | 71 / 124 |
| 150 | 10 | phase_spline | numba | 3746 | 0 / 0 | 0.48/0.30/1.05/11.34 | 46 / 96 | 3 / 16 | 7 / 77 | 1 / 17 | 22 | 0 | 210 / 646 |
| 150 | 10 | phase_spline | gpu | 3753 | 0 / 0 | 2.31/0.30/3.40/4.70 | 17 / 59 | 3 / 16 | 75 / 130 | 3 / 21 | 21 | 0 | 86 / 101 |
| 150 | 20 | current | numba | 3775 | 0 / 0 | 0.68/0.33/1.27/10.97 | 29 / 60 | 2 / 12 | 103 / 231 | 5 / 14 | 16 | 0 | 104 / 112 |
| 150 | 20 | current | gpu | 3743 | 0 / 0 | 2.09/0.25/3.15/4.14 | 19 / 67 | 2 / 11 | 33 / 52 | 2 / 16 | 20 | 0 | 70 / 73 |
| 150 | 20 | spline | numba | 3749 | 0 / 0 | 0.67/0.16/1.21/3.53 | 32 / 71 | 3 / 22 | 10 / 29 | 9 / 23 | 16 | 171 | 95 / 114 |
| 150 | 20 | spline | gpu | 3752 | 0 / 0 | 2.14/0.28/3.18/3.87 | 10 / 47 | 3 / 33 | 54 / 85 | 9 / 22 | 10 | 188 | 82 / 98 |
| 150 | 20 | phase_spline | numba | 3751 | 0 / 0 | 0.91/0.66/1.66/26.99 | 77 / 101 | 3 / 20 | 22 / 39 | 3 / 14 | 19 | 852 | 74 / 89 |
| 150 | 20 | phase_spline | gpu | 3746 | 0 / 0 | 2.30/0.46/3.38/17.81 | 54 / 86 | 2 / 21 | 36 / 54 | 1 / 10 | 17 | 474 | 103 / 138 |
| 248 | 5 | current | numba | 6165 | 0 / 0 | 0.35/0.05/0.58/0.75 | 46 / 101 | 3 / 15 | 66 / 122 | 4 / 32 | 23 | 0 | 93 / 157 |
| 248 | 5 | current | gpu | 6174 | 0 / 0 | 2.00/0.28/3.22/3.87 | 104 / 144 | 3 / 17 | 22 / 116 | 4 / 38 | 31 | 0 | 135 / 795 |
| 248 | 5 | spline | numba | 6164 | 0 / 0 | 0.34/0.05/0.57/0.69 | 52 / 73 | 1 / 14 | 27 / 66 | 3 / 9 | 31 | 0 | 124 / 337 |
| 248 | 5 | spline | gpu | 6174 | 0 / 0 | 2.03/0.28/3.19/4.07 | 34 / 135 | 2 / 32 | 52 / 67 | 3 / 9 | 20 | 0 | 134 / 139 |
| 248 | 5 | phase_spline | numba | 6155 | 0 / 9 | 0.47/0.07/0.79/2.03 | 48 / 202 | 9 / 564 | 58 / 101 | 5 / 47 | 24 | 36 | 120 / 145 |
| 248 | 5 | phase_spline | gpu | 6179 | 0 / 0 | 2.15/1.84/3.41/83.55 | 22 / 101 | 2 / 711 | 62 / 177 | 4 / 35 | 27 | 0 | 98 / 127 |
| 248 | 10 | current | numba | 6164 | 0 / 0 | 0.38/0.18/0.89/4.76 | 159 / 220 | 5 / 83 | 18 / 94 | 2 / 40 | 15 | 0 | 118 / 123 |
| 248 | 10 | current | gpu | 6175 | 0 / 0 | 2.03/0.30/3.31/4.54 | 67 / 138 | 1 / 286 | 97 / 171 | 7 / 47 | 25 | 0 | 95 / 115 |
| 248 | 10 | spline | numba | 6165 | 0 / 0 | 0.37/0.11/0.76/1.88 | 114 / 259 | 9 / 41 | 32 / 45 | 12 / 27 | 18 | 0 | 109 / 137 |
| 248 | 10 | spline | gpu | 6169 | 0 / 0 | 1.98/0.26/3.07/3.77 | 119 / 243 | 4 / 16 | 27 / 49 | 11 / 33 | 20 | 0 | 116 / 224 |
| 248 | 10 | phase_spline | numba | 6173 | 0 / 0 | 0.49/0.13/1.02/1.42 | 36 / 113 | 2 / 552 | 33 / 57 | 10 / 47 | 35 | 0 | 122 / 125 |
| 248 | 10 | phase_spline | gpu | 6162 | 0 / 0 | 2.11/0.15/2.78/3.57 | 87 / 110 | 3 / 844 | 36 / 160 | 9 / 52 | 17 | 0 | 159 / 537 |
| 248 | 20 | current | numba | 6163 | 0 / 0 | 0.64/0.11/1.14/1.41 | 55 / 161 | 3 / 792 | 102 / 161 | 12 / 78 | 35 | 0 | 266 / 604 |
| 248 | 20 | current | gpu | 6304 | 0 / 0 | 1.96/0.17/2.66/3.55 | 46 / 88 | 4 / 690 | 44 / 242 | 25 / 64 | 24 | 0 | 108 / 124 |
| 248 | 20 | spline | numba | 6163 | 0 / 0 | 0.65/0.28/1.27/10.76 | 64 / 205 | 18 / 52 | 31 / 60 | 10 / 23 | 21 | 0 | 126 / 171 |
| 248 | 20 | spline | gpu | 6165 | 0 / 0 | 1.97/0.13/2.51/3.15 | 55 / 145 | 9 / 90 | 191 / 274 | 14 / 47 | 21 | 0 | 106 / 370 |
| 248 | 20 | phase_spline | numba | 6131 | 0 / 31 | 0.92/0.27/1.86/5.48 | 76 / 131 | 17 / 397 | 65 / 130 | 7 / 74 | 27 | 88 | 90 / 120 |
| 248 | 20 | phase_spline | gpu | 6171 | 0 / 0 | 2.20/0.40/3.42/12.16 | 30 / 89 | 2 / 827 | 61 / 189 | 11 / 86 | 25 | 0 | 113 / 154 |
| 555 | 5 | current | numba | 13828 | 0 / 41 | 0.33/0.05/0.57/0.91 | 29 / 80 | 3 / 84 | 11 / 42 | 7 / 19 | 21 | 39 | 54 / 84 |
| 555 | 5 | current | gpu | 13873 | 0 / 30 | 1.40/0.19/2.16/3.16 | 8 / 70 | 5 / 130 | 19 / 93 | 7 / 19 | 27 | 42 | 82 / 84 |
| 555 | 5 | spline | numba | 13845 | 0 / 36 | 0.33/0.05/0.54/0.73 | 62 / 94 | 3 / 17 | 57 / 117 | 2 / 14 | 26 | 108 | 111 / 350 |
| 555 | 5 | spline | gpu | 13876 | 0 / 8 | 1.47/0.20/2.21/3.52 | 34 / 70 | 3 / 28 | 54 / 80 | 3 / 8 | 28 | 6 | 91 / 229 |
| 555 | 5 | phase_spline | numba | 13669 | 0 / 214 | 0.45/0.06/0.71/0.92 | 63 / 121 | 5 / 74 | 42 / 113 | 6 / 20 | 30 | 456 | 107 / 194 |
| 555 | 5 | phase_spline | gpu | 13874 | 0 / 21 | 1.57/1.90/2.41/86.31 | 13 / 54 | 2 / 108 | 29 / 73 | 6 / 16 | 24 | 63 | 80 / 127 |
| 555 | 10 | current | numba | 13876 | 0 / 33 | 0.34/0.10/0.76/0.96 | 67 / 128 | 5 / 19 | 19 / 87 | 9 / 23 | 19 | 99 | 61 / 231 |
| 555 | 10 | current | gpu | 13870 | 0 / 0 | 1.41/0.19/2.25/3.14 | 23 / 127 | 2 / 76 | 19 / 45 | 7 / 26 | 22 | 0 | 59 / 92 |
| 555 | 10 | spline | numba | 13762 | 0 / 108 | 0.34/0.09/0.74/0.88 | 52 / 143 | 5 / 22 | 38 / 145 | 2 / 7 | 24 | 324 | 87 / 117 |
| 555 | 10 | spline | gpu | 13933 | 0 / 9 | 1.43/0.19/2.20/2.73 | 72 / 173 | 4 / 17 | 61 / 76 | 8 / 15 | 19 | 0 | 83 / 200 |
| 555 | 10 | phase_spline | numba | 13829 | 0 / 47 | 0.46/0.12/0.95/1.19 | 13 / 35 | 5 / 74 | 15 / 54 | 6 / 19 | 20 | 141 | 84 / 106 |
| 555 | 10 | phase_spline | gpu | 13871 | 0 / 16 | 1.60/0.22/2.51/3.22 | 49 / 150 | 15 / 36 | 31 / 94 | 4 / 26 | 29 | 33 | 80 / 584 |
| 555 | 20 | current | numba | 13721 | 0 / 128 | 0.62/0.11/1.14/1.39 | 28 / 73 | 9 / 71 | 24 / 95 | 8 / 25 | 23 | 384 | 101 / 116 |
| 555 | 20 | current | gpu | 13895 | 0 / 0 | 1.48/0.14/2.07/3.14 | 42 / 123 | 5 / 26 | 26 / 50 | 6 / 11 | 23 | 0 | 72 / 88 |
| 555 | 20 | spline | numba | 13797 | 0 / 78 | 0.61/0.12/1.13/1.28 | 97 / 177 | 9 / 29 | 32 / 85 | 4 / 7 | 23 | 0 | 82 / 168 |
| 555 | 20 | spline | gpu | 13866 | 0 / 20 | 1.46/0.20/2.29/3.08 | 42 / 89 | 10 / 29 | 59 / 79 | 9 / 14 | 20 | 60 | 70 / 90 |
| 555 | 20 | phase_spline | numba | 13632 | 0 / 259 | 1.11/0.23/1.73/2.18 | 7 / 70 | 4 / 61 | 28 / 45 | 2 / 16 | 23 | 777 | 58 / 72 |
| 555 | 20 | phase_spline | gpu | 13857 | 0 / 46 | 1.66/0.23/2.65/3.30 | 78 / 134 | 5 / 35 | 105 / 149 | 5 / 21 | 19 | 102 | 79 / 102 |
