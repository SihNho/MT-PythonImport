# Questions for the owner

For the interview with the project owner (SiHyeong). Each question names the feature it settles. Answers are
recorded in the feature as **owner** evidence, with the date. Questions that only a VI read can answer are not
here; they are the `unknown — needs VI read` entries in the step files and in [coverage.md](coverage.md).

**Most important first:** Q4.08, Q5.01, Q0.06, Q4.06, Q1.04, Q4.05, Q5.03, Q0.07, Q4.11, Q3.05.

## 0 — Start-up and shared

- **Q0.02 (F0.02)** Frame rate, exposure and ROI come from NI MAX, not from the program. Should the port set them
  itself (and save them with the data), or keep reading what the camera holds?
  *Answered (owner 2026-10-22):* set them from presets and save them with the data ("이 정보도 프리셋 적용하고, 데이터와
  함께 저장하면 좋겠는데"); see [ui-requirements.md](ui-requirements.md) U15.
- **Q0.03 (F0.03)** At every start the PI controller runs `GOH` (the magnet moves home). Is that wanted every time?
  Is it safe with a sample in place?
- **Q0.05 (F0.05)** The focus stage is moved at start-up to `Set Focus  (0->50)` (51.5 on the panel) and also to
  `Focus Pos (Start)`. Which one is the real start focus, and what range is safe?
- **Q0.06 (F0.06, F1.07)** Rotor zero: you chose a middle point as zero because the controller did not take negative
  positions; the driver adds `Baseline Startpoint` = 200 turns. (a) What is the physical meaning of rotor 0? (b) What
  should `Current pos rot?` be at the start of a run? (c) May the port read the rotor position as signed (as decided
  for V6 on 2026-09-13)? Note: the V6 hardware test left the controller counter at 0, not 200 turns
  (`V6:docs/questions-for-user-2026-09-14.md`, item 3).
- **Q0.07 (F0.07)** Does any other program read `Global motor pos.vi` (Trans / Rot / Focus position)? If not, the
  port drops it.
- **Q0.09 (F0.09)** What is `Max Trans Pos` for this room, and should every magnet move be clamped by it? (No clamp
  was found on the move paths.)
- **Q0.10 (F0.10)** Which device errors have you seen during runs, and what should the program do then: stop, warn,
  or continue?
- **Q0.11 (all)** Was the working copy `Min_Track N beads V6_ParallelLoop.vi` changed on the front panel after it was
  copied from 4.5 (other than the TIFF writer)? The inventory was read from the copy.

## 1 — Live view and motors

- **Q1.03 (F1.03)** Is `Trans Step (mm)` an absolute target or a step added to the current position?
- **Q1.04 (F1.04)** `+ Cal Zero` moves the magnet to a preset between 36 and 38 (your words; unit not stated), `Cal Zero` shows 0. What is each
  preset used for? `- Cal Zero` is still wired and still moves the magnet: drop it or keep it? What names should the
  buttons have in the port?
- **Q1.05 (F1.05)** What do `HOME`, `Stop Trans` and `Send` do exactly during the experiment?
- **Q1.07 (F1.07)** `Rot \nSpeed`: unit and safe range? After `Send to Rot` the program rewrites `Rot Step (deg) `;
  should the step reset to 0?
- **Q1.09 (F1.09)** What is `Mp measure freq` (unit; how often the magnet position is read)?

## 2 — Bead picking

- **Q2.01 (F2.01)** How do you remove a wrongly clicked bead? What is `Count` for?
- **Q2.03 (F2.03)** After `Done Picking Beads?` there is no way back. Should the port allow going back to picking
  (or adding a bead) before the calibration starts?
- **Q2.04 (F2.04)** Is there ever more than one reference bead? Is the reference always the first click?
  *Partly answered (owner 2026-10-22):* every measurement includes non-paramagnetic streptavidin polystyrene
  reference beads ([rig-facts.md](../rig-facts.md)). Still open: how many are picked, and whether it is the first click.

## 3 — Calibration

- **Q3.01 (F3.01)** Which calibration values change between experiments (slices, step, averages, cross length), and
  which are fixed per room? *Partly answered (owner 2026-10-22):* step 100 nm over about 6 µm
  ([rig-facts.md](../rig-facts.md)). Still open: whether any of them change between experiments.
- **Q3.07 (F3.01)** The calibration file stores `pixel distance (nm)` = 84, but the 50x objective with binning 2 gives
  about 200 nm/px nominally (100x would give about 100). Is 84 a value left from the 100x setup, or was it measured?
  Where is it used? ([rig-facts.md](../rig-facts.md)) *Answered (owner 2026-10-22):* "예전 렌즈 사용할 때 기록인듯.
  (100X)" — stale for 50x. Still open: where the program uses it, and the measured 50x pixel size.
  *Answered (owner 2026-10-22):* "Matlab 분석할때 거기 있는 파라미터 사용함. 그러니 사실 랩뷰에서는 사용 안하는 숫자" —
  analysis is done in MATLAB with its own parameters; LabVIEW does not use this number. (An earlier worry that the
  LabVIEW force subVI might apply 84 nm/px to 50x data is withdrawn.) The port keeps writing the field for format
  compatibility (decision 0006) and should show it as "not used by tracking".
- **Q3.02 (F3.02)** Does the Z scan start at the current focus and go up, and is the bead expected to be in focus at
  the start or in the middle of the scan?
- **Q3.05 (F3.04)** Do you choose the bandpass and forget radius by hand during calibration? What do the three numbers
  stored per bead mean (e.g. 0, 25, 23)?
- **Q3.06 (F3.05)** Is an old `.cal` file ever reused for a new run, or is a calibration always made fresh?

## 4 — Experiment

- **Q4.01 (F4.01)** What do you check in the `continue tracking` step before tracking starts?
- **Q4.02 (F4.02)** What are `# FD points` and `# DT points`?
- **Q4.04 (F4.04, [phase 3 results](../results/2026-10-22-offline-core.md))** The port matches LabVIEW within
  1e-6 px / 1e-4 um on 50 137 bead-frames, with two exceptions. (a) Frame 1937, bead 5: a near tie between two
  calibration slices flips the slice choice, so z differs by 4.7e-3 um on that one bead-frame. Accept it, or should we
  read LabVIEW's single-precision rounding order from the VI to fix it exactly? (b) Beads LabVIEW has already flagged
  bad (defocused, z = 5.9) differ by up to 3.1e-5 px in x, y. Is a looser tolerance acceptable for flagged beads?
- **Q4.05 (F4.05)** (a) `Auto-Reset` on: a lost bead restarts all beads from their calibration positions; is that
  the intended reset? (b) What is `Auto-reset zero`? (c) Is the periodic reset (every N frames) still used? (d) May
  the port keep reading "this frame's minimum" (your 2026-09-15 choice for V6)?
- **Q4.06 (F4.06)** Autofocus fires every `Frame rate` frames (25) and moves the focus by at most ±0.2 internal units
  toward the centre of the calibration stack plus `Focus Deviation from the Center`. (a) What does
  `Fix to a Certain Pattern` mean to you? (b) Is a move on every firing, even a tiny one, intended, or should there
  be a dead band? (c) May `Frame rate` be renamed "autofocus period (frames)"?
- **Q4.08 (F4.08)** The 3-state clamping: (a) what are the three states? (b) what do the three schedule rows hold,
  with units (speed in mm/s, force in pN or a magnet position, wait in minutes or seconds)? (c) when is the clamp
  "reached" (tolerance)? (d) what happens after the last cycle — stop, hold, return? (e) What do `Switch` and
  `Start Moving?` mean?
- **Q4.09 (F4.09)** What does `Correction Factor` correct (the oil/water index note of the `.tra` header?), and which
  value do you use?
- **Q4.10 (F4.10)** Is the live force–extension (WLC) display used during runs? Which magnet / bead does
  `Magnet2Force v3_for M270` describe? What do `Value 2` and `Value 3` show?
- **Q4.11 (F4.11)** Is the nominal 2,000,000 rows per `.tra` file and the `cal…` → `tra…` naming fixed by your
  analysis scripts?

## 5 — Save and stop

- **Q5.01 (F5.01)** How do you normally end a run: `stop (end)`, `stop (end) 2`, or LabVIEW's Abort? What is
  `stop (end) 2` for? The port will offer Stop-and-save and Stop-without-saving — is anything else needed?
- **Q5.02 (F5.02)** Have you lost data from an aborted run? How much loss after a crash is acceptable (seconds)?
- **Q5.03 (F5.03, decision 0007)** (a) Should the laser start in the off state after an abnormal end? (b) What should
  the emergency stop do to the laser? (c) Is a UPS possible for the rig PC?

## Format

- **Q-F1 ([../format/hdf5-v1.md](../format/hdf5-v1.md))** Which fields of the HDF5 draft do you need first? Should
  command and event logs (schedule steps, button presses) be in the data file?
