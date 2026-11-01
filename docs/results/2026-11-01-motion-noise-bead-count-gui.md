# 2026-11-01 15:15-15:33: tracking noise under focus / stage / magnet motion, tracking time against the bead count, and the same through the GUI

Owner: "measure the tracking noise while moving the piezo and the stage each, and the magnet too; the same on the GPU;
run the bench", then "the frame numbers against the bead count too", then "in the end it has to be measured in the
app's GUI; GUI control allowed - run the same bench through the GUI". The owner's four beads at the owner's focus
(small ring), dry channel, 90 Hz, `current` Z method. Scripts tools/rig_motion_noise.py, tools/rig_bead_count.py,
tools/gui_rig_bench.py; data `G:\l2s_rig_data\2026-11-01_motion_noise`, `..._bead_count`, `..._gui_bench`
(noise.json / report.json / gui_bench.json, screenshots).

Noise = differential noise per frame within a 3 s hold (std of the difference of two beads / sqrt 2, median over the
6 pairs), nm; shift = mean bead position relative to the first hold, nm (203 nm / px).

## Motion (script: tools/rig_motion_noise.py)
| run | frames | lost / dropped | noise in the holds x / y / z (nm) | what the steps did |
|---|---|---|---|---|
| focus +-1 um, numba | 2452 | 0 / 0 | 0.9-1.1 / 0.9-1.0 / 1.4-2.4 | z follows: +0.5 -> 396, +1 -> 991, -0.5 -> -499, -1 -> -1066 nm (the piezo's own irregularity, as before) |
| focus +-1 um, GPU | 2453 | 0 / 0 | 0.9-1.4 / 0.9-1.5 / 1.5-4.8 | same; the run drifted 140 / 110 nm in x / y over 30 s |
| stage 1 / 2 / 5 um steps, numba | 4617 | 0 / 0 | 1-5 nm at 1-2 um steps; **beads lost at 5 um** | see below |
| stage, GPU | 4617 | 0 / 0 | same pattern | same |
| magnet 0 -> 30 -> 0 mm, numba | 2983 | 0 / 0 | 1.2-1.8 / 0.9-1.3 / 1.6-3.3 | shifts < 90 nm: **the magnet's travel does not move or shake the beads** |
| magnet, GPU | 3000 | 0 / 0 | 1.3-2.3 / 0.9-1.4 / 1.6-4.1 | same |

**The stage finding.** A 1 um step (5 px) is tracked cleanly (noise 1-4 nm, shift 954 nm as commanded; 1 um = 4.9
px = 1.00 um at 203 nm / px). A 2 um step mostly (shift 1904 nm; one hold at 184 nm noise). **A 5 um step (25 px)
loses the beads** (500-700 lost bead-frames per hold, noise in the hundreds of nm): the stage moves the 5 um inside
one or two frames, the XY stage of the tracker (LabVIEW's, window +-72 px but a frame-to-frame search of a few px)
does not follow, the bead is flagged lost and - the VI's rule - every bead restarts from its calibration position,
which is now 25 px off, so they stay lost until the stage comes back. Also a constant 30-45 lost bead-frames in every
stage hold, even at 0 / 0: one bead near the frame's edge region flickers (to be looked at; not seen in the focus
and magnet runs). This is the LabVIEW program's behaviour too; an operator who jogs the stage by 5 um during a
recording loses the tracking until the beads are re-selected. Candidate (owner's call): a larger search step after
a lost frame, or a re-pick from the display.

## Tracking time against the bead count (script: tools/rig_bead_count.py; copies of the four beads, 15 s each, 90 Hz)
| beads | numba track ms p50 / p99 | GPU track ms p50 / p99 | drops | latency p99 (numba / GPU) |
|---|---|---|---|---|
| 4 | 0.37 / 0.87 | 2.19 / 2.64 | 0 / 0 | 1.20 / 2.74 |
| 16 | 0.65 / 0.95 | 2.21 / 2.65 | 0 / 0 | 1.06 / 2.77 |
| 64 | 1.80 / 2.97 | 3.46 / 3.92 | 0 / 0 | 3.09 / 4.02 |
| 128 | 3.25 / 5.65 | 4.73 / 5.37 | 0 / 0 | 5.77 / 5.51 |
| 256 | 6.34 / 11.16 | 5.57 / 7.33 | 0 / 0 | 11.25 / 7.38 |

The frame budget at 90 Hz is 11.1 ms: numba reaches it at 256 beads (p99), the GPU is ahead from ~200 beads on
(as decision 0024 measured offline). No frame was dropped at any count.

## The same through the GUI (tools/gui_rig_bench.py: MainWindow, Connect, picks, Calibrate, bead list, Start / Record, shutdown dialog)
Connect 20 s (8 / 8), z scan from the Calibrate panel 21 s, selection from the bead list, every run started and
recorded with the GUI's buttons, the display and the plot running (30 Hz tap; 850-1900 display updates per run),
the shutdown dialog closed everything in 1.7 s and released the lock.

| run (GUI) | frames | lost / dropped | noise in the holds x / y / z (nm) | track ms p50 / p99 |
|---|---|---|---|---|
| focus, numba | 2470 | 0 / 0 | 0.9-1.2 / 1.0-1.1 / 1.5-3.1 | 0.40 / 2.57 |
| focus, GPU | 3145 | 0 / 0 | 1.0-1.7 / 0.9-1.3 / 1.8-3.2 | 2.35 / 7.44 |
| stage, numba | 4659 | 0 / 0 | as the script: 1-6 nm at 1-2 um, lost at 5 um | 0.39 / 2.77 |
| stage, GPU | 4674 | 0 / 0 | same | 2.32 / 7.20 |
| magnet, numba | 3029 | 0 / 0 | 1.1-2.5 / 1.1-1.4 / 2.2-4.9 | 0.39 / 2.76 |
| magnet, GPU | 3528 | 0 / 0 | 1.1-2.1 / 0.9-1.3 / 2.4-3.3 | 2.35 / 7.18 |

| beads (GUI, 10 s) | numba track ms p50 / p99 | GPU track ms p50 / p99 | drops |
|---|---|---|---|
| 4 | 0.40 / 2.68 | 2.33 / 7.11 | 0 / 0 |
| 64 | 3.01 / 8.98 | 4.78 / 19.66 | 0 / 0 |
| 256 | 11.13 / 28.96 | 7.47 / 38.69 | 0 / 0 |

- **Noise: the GUI path equals the script path** (same 1 / 1 / 2 nm in the holds, the same stage behaviour, no
  loss, no drop).
- **Time: the GUI costs the tracker its tail.** With the window alive the p99 tracking time is 3-4x the script's
  (2.6 vs 0.9 ms at 4 beads; 29 vs 11 ms at 256 beads numba, 39 vs 7 ms GPU) - the Qt thread (display, plot, event
  log) competes for the cores and the GPU's command queue. At 256 beads the p50 itself (11.1 ms numba) equals the
  frame period; nothing was dropped only because the ring buffer absorbed the tail. **At 90 Hz with the GUI, about
  100 beads on numba is the comfortable limit; the GPU's tail in the GUI is worse than numba's**, opposite to the
  script. This is the number that matters for the experiment (owner: the GUI is where it is measured).
- **GUI bug found (screenshot 04_256_beads.png):** with 256 beads the bead-chip row (one checkbox per bead) does not
  wrap, the window stretched to 14 726 px wide. The chips need a wrapping layout or a cap (fault list, GUI).
- The 30-45 lost bead-frames per stage hold appear in the GUI run too (same cause).

## Open
- The focus piezo's step irregularity (every run today) and the stage-jump loss are the two things that limit a
  z / xy calibration now; the owner decides the tracker's response to a lost bead.
- The GUI's tail cost: a lower display rate or a plot that draws less while recording would give the tracker back
  its p99; the chip row must wrap.

## Why the GUI slows the tracker (16:00, tools/gui_rig_isolate.py; owner: "run the isolation measurement")
The same window, 10 s recorded runs, the GUI's 33 ms tick timed; conditions: normal | display off (no image, no bead
boxes; plot on) | no plot | no event log | timers off (GUI idle, the pipeline alone).

| beads / exec | condition | track ms p50 / p99 | latency p99 | GUI tick ms p50 / max (ticks in 10 s) |
|---|---|---|---|---|
| 4 numba | normal | 0.39 / 3.21 | 3.5 | 6.3 / 15.6 (236) |
| 4 numba | display off | 0.38 / 2.18 | 2.7 | 1.8 / 3.4 |
| 4 numba | no plot | 0.37 / 0.90 | 1.2 | 4.4 / 10.0 |
| 4 numba | no log | 0.39 / 2.50 | 3.0 | 6.2 / 11.8 |
| 4 numba | timers off | 0.36 / 0.76 | 1.2 | - |
| 256 numba | normal | 11.09 / 15.14 | 86 | 317 / 2319 (26) |
| 256 numba | display off | 11.00 / 13.63 | 22 | 53 / 84 (64) |
| 256 numba | no plot | 11.03 / 12.30 | 16 | 257 / 309 (40) |
| 256 numba | no log | 11.04 / 16.98 | 71 | 315 / 2215 (28) |
| 256 numba | timers off | 6.34 / 11.32 | 12 | - |
| 256 GPU | normal | 7.10 / 34.39 | 56 | - / 1128 (163) |
| 256 GPU | display off | 6.60 / 41.13 | 163 | 36 / 40 (92) |
| 256 GPU | no plot | 7.11 / 33.06 | 55 | 206 / 2171 (75) |
| 256 GPU | no log | 7.17 / 35.97 | 58 | 246 / 2204 (54) |
| 256 GPU | timers off | 5.66 / 7.40 | 7.5 | - |

- **With the GUI idle the Python pipeline is the script's pipeline** (256 beads: 6.3 / 11.3 ms numba, 5.7 / 7.4 ms
  GPU): the slowdown is entirely the GUI thread's work competing with the worker for the interpreter (GIL).
- **What the GUI thread does per tick is far too heavy at 256 beads:** 317 ms per tick (2.3 s worst), i.e. the
  "30 Hz" tick runs 2.6 times a second. Two culprits, both in `app.py`: `_draw_boxes` removes and recreates 2 x N
  QGraphicsItems (a rect and a text per bead = 512 items) every tick, and `_update_plot` rebuilds the whole 30 s
  history (900 rows x 256 beads x 3) into numpy arrays and re-sets 256 curves every tick. Display off (no boxes)
  brings the tick to 53 ms and the p99 to 13.6; no plot to 12.3; the event log is minor.
- **Even at 4 beads the plot is the tail:** p99 3.2 -> 0.9 ms without the plot (the tick is 6 ms with 4 curves).
- **The GPU executor suffers most** (p99 33-41 ms whatever is switched off, 7.4 ms idle): its per-frame CUDA calls
  are Python-side and need the interpreter many times per frame, so every GUI tick lands inside them.
- At 256 beads numba the p50 itself goes 6.3 -> 11.0 ms under the GUI: the worker gets about half the interpreter.

**Conclusion.** Not a Python-speed problem: the tracker itself holds 256 beads at 90 Hz. It is (1) a GUI drawing
problem - items recreated and history rebuilt every tick - and (2) the shared interpreter. Fixes, in order:
1. cheap drawing: one scatter item for all boxes (update data, never recreate), a bounded history array with a
   plot refresh at 10 Hz and only the checked beads' curves, labels only when few beads - expected to give back
   most of the p99 at any count;
2. the pipeline in its own process (camera -> tracking -> file in a worker process; the GUI receives display
   snapshots and results through shared memory / a queue): removes the interpreter sharing entirely, which is what
   LabVIEW's separate loops gave for free. A design change: a decision record.
A change of language is not needed for this; it would buy something only for hard real-time guarantees (which
Windows does not give either way) or for far more beads at far higher rates than the camera delivers.

## The same window as a client of the engine process (17:04, decision 0029 step 3; tools/gui_rig_isolate.py CLIENT=1)
| beads / exec | condition | in-process GUI (16:00) track p50 / p99 | **client GUI** track p50 / p99 | script (GUI idle) |
|---|---|---|---|---|
| 4 numba | normal | 0.39 / 3.21 | **0.39 / 0.61** | 0.36 / 0.76 |
| 4 numba | no plot | 0.37 / 0.90 | 0.38 / 0.68 | |
| 256 numba (12 threads) | normal | 11.09 / 15.14 | 11.01 / 11.73 | 6.43 / 11.60 |
| 256 numba (10 threads) | normal | - | **7.39 / 8.48** | 7.37 / 7.89 |
| 256 GPU | normal | 7.10 / 34.39 | **5.73 / 6.62** | 5.58 / 6.28 |
| 256 GPU | display off | 6.60 / 41.13 | 5.59 / 7.55 | |

- **The interpreter sharing is gone:** the 4-bead tail (3.2 -> 0.6 ms) and the GPU tail (34 -> 6.6 ms) equal the
  script's; no drops anywhere; the GUI tick itself is unchanged (276 ms at 256 beads - still worth the drawing fix).
- **One effect remained with numba on all 12 cores:** 256 beads p50 11.0 ms under the GUI vs 6.4 idle, in the
  client too. Not the GIL (separate process) but the cores: the parallel kernel waits for its slowest thread, and
  the GUI's drawing displaces one. With `NUMBA_NUM_THREADS=10` the frame costs 7.4 ms with or without the GUI
  (8.5 ms p99 under it). The engine now leaves two cores by default (`python -m mtpy.engine`).
- **Acceptance of 0029 item 7 met:** p50 / p99 under the GUI within 20 % of the script at 4 and 256 beads, numba
  (10 threads) and GPU; shutdown through the dialog released the lock; the engine exited 0.

## 5 / 10 / 20 beads x 3 Z methods x 2 executors (17:34-17:47; owner: "so we can guess how far the hardware goes")
Pipeline alone (tools/rig_bead_count.py, 15 s each) and under the client GUI (tools/gui_rig_isolate.py CLIENT=1, 10 s
each, plot at 10 Hz); 90 Hz, the owner's four beads copied to the count; 0 drops and 0 gaps in all 36 runs.
Numbers: median / std / slowest 1 % (p99) / max of the per-frame tracking time, ms (frame budget 11.1 ms).

| beads | Z method | exec | pipeline alone: median / std / p99 / max ms | under the client GUI: median / std / p99 / max ms |
|---|---|---|---|---|
| 5 | current | numba | 0.38 / 0.71 / 1.01 / 17.15 | 0.38 / 0.06 / 0.55 / 1.38 |
| 5 | current | gpu | 2.16 / 0.14 / 2.55 / 3.08 | 2.23 / 0.23 / 3.16 / 4.22 |
| 5 | spline | numba | 0.37 / 1.40 / 1.05 / 31.77 | 0.37 / 1.26 / 0.93 / 29.88 |
| 5 | spline | gpu | 2.18 / 0.15 / 2.60 / 3.13 | 2.23 / 0.24 / 3.18 / 4.06 |
| 5 | phase_spline | numba | 0.49 / 0.18 / 0.61 / 6.69 | 0.49 / 0.07 / 0.81 / 1.27 |
| 5 | phase_spline | gpu | 2.38 / 0.39 / 2.77 / 15.44 | 2.42 / 0.27 / 3.47 / 4.26 |
| 10 | current | numba | 0.39 / 0.08 / 0.66 / 1.93 | 0.40 / 0.08 / 0.76 / 1.72 |
| 10 | current | gpu | 2.19 / 0.50 / 2.74 / 15.99 | 2.23 / 0.27 / 3.33 / 3.51 |
| 10 | spline | numba | 0.37 / 0.08 / 0.65 / 1.89 | 0.39 / 0.10 / 0.90 / 1.52 |
| 10 | spline | gpu | 2.21 / 0.40 / 2.68 / 14.21 | 2.25 / 0.26 / 3.29 / 3.83 |
| 10 | phase_spline | numba | 0.50 / 0.10 / 0.90 / 2.13 | 0.51 / 0.10 / 0.94 / 2.09 |
| 10 | phase_spline | gpu | 2.38 / 0.41 / 2.99 / 12.50 | 2.42 / 0.26 / 3.46 / 4.05 |
| 20 | current | numba | 0.67 / 0.09 / 1.13 / 2.04 | 0.70 / 1.95 / 1.57 / 61.64 |
| 20 | current | gpu | 2.18 / 0.41 / 2.70 / 11.54 | 2.23 / 0.22 / 3.13 / 3.85 |
| 20 | spline | numba | 0.67 / 0.10 / 1.10 / 2.24 | 0.68 / 0.09 / 1.11 / 2.03 |
| 20 | spline | gpu | 2.20 / 0.25 / 2.65 / 8.86 | 2.24 / 2.07 / 3.20 / 94.08 |
| 20 | phase_spline | numba | 0.91 / 0.17 / 1.66 / 3.54 | 0.93 / 0.17 / 1.64 / 2.22 |
| 20 | phase_spline | gpu | 2.40 / 2.44 / 2.93 / 91.41 | 2.42 / 0.21 / 3.23 / 4.94 |

- **Up to 20 beads the tracker is far from the budget on either path**: numba 0.4-0.9 ms median, p99 under 1.7 ms;
  the GPU executor sits at 2.2-2.4 ms whatever the count (its per-frame CUDA launch cost), so below ~100 beads numba
  is the better executor, as the 10-29 offline bench said.
- **Z method cost**: `phase_spline` is ~30 % slower than `current` / `spline` on numba (0.49 vs 0.38 ms at 5 beads,
  0.93 vs 0.68 at 20); `spline` costs the same as `current`. On the GPU the three are within 0.2 ms.
- **The GUI (engine client) adds nothing to the median** and 0.1-0.5 ms to the p99 at these counts.
- **Single-frame outliers of 15-95 ms** appear in a few runs on both paths (std inflated to 1-2.5 ms by one frame,
  the max column): one frame per run at most, not tied to the count, method or path; the ring absorbs them (0
  drops). Likely an OS / driver pause or a GC; worth a look only if they recur in long runs (the 10-31 20-minute runs
  had none visible in their loss counts).
- GPU runs under the GUI show more frames per "10 s" (up to 3188): the GPU executor's start-up (CUDA context, first
  kernel) delays the recording start, and the frame count runs from acquisition start; the timing columns are
  unaffected.

