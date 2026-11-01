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
