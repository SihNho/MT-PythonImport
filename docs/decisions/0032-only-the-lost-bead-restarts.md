# 0032 - After a lost frame only the lost bead restarts, from where it was last seen

**Decided:** 2026-11-15 (owner: "fix it", after the odd / even frame offset was traced to the restart rule). A
deliberate departure from the LabVIEW program's numbers (decisions 0003 / 0004: identical unless the owner decides
otherwise).

## What was seen
The V6 analysis found that x and z of many tethered beads alternate between odd and even frames in the run files of
2026-11-06 and 2026-11-10 (`G:\Data\Sihyeong-DevelopedTool\...\tra00N.h5`). Read from the raw `/mt` rows:

- LabVIEW's rule (`track.Tracker`, copied by `acq.pipeline.BeadTracker`): a bead flagged bad is output as -1 on the
  next frame, and on the frame after any -1 **every** bead restarts from its calibration (pick) position.
- A bead that has moved away from its pick is not found from there: 11-06 Batch2 `tra001`, beads 7 and 12 (15 and
  12.7 px from their picks) read z = 0.000 (the LUT's bottom) on every tracked frame, are flagged bad again, and
  come back as -1 on every second frame to the end of the run.
- So every second frame is a restart frame for all beads. On those frames a bead started some px away from where
  it is reads differently: rows 42000-43000 of that file (499 restart frames), z(restart) - z(between) = -25 nm
  (bead 8), -26 (9), -37 (10), -36 (14), -45 (16), x up to -0.59 px; the reference bead, at its pick, -0.4 nm.
  11-10 `tra003`: -26 nm (bead 2), -15 (3), +18 (13). 11-06 Received `tra002`: -278 nm (14), -221 (16), -78 (12).
- The offset starts in the same 10 s window as the first alternating -1 bead (the V6 session's count: 341 s in
  Received `tra002`, ~400 s in 11-10 `tra005`), does not depend on the force and keeps its sign.

## Decision
`BeadTracker` (the live pipeline; every kernel, CPU and GPU):

1. A bead flagged bad is still output as -1 on the next frame (the lost mark in the data stays as it was).
2. Only that bead restarts. Every other bead goes on from its own previous output.
3. It restarts from where it was last seen - the x, y of the frame that flagged it - when that lies inside the
   image by the kernel's half window; otherwise, and at every second failed try in a row, from its calibration
   position.

`track.Tracker` (the reference implementation the LabVIEW fixture is replayed against) keeps LabVIEW's rule.

## Consequences
- Run files written from v0.3.0 on do not have the restart-frame offset; their numbers differ from what LabVIEW
  would have written whenever a bead is lost. `/metadata/run/code_version` tells the two apart.
- A bead that stays bad still alternates between a tracked frame and a -1 frame, but alone.
- Existing run files: drop the frames whose previous frame (buffer number + 1) has any bead at -1; the frames in
  between are the unaffected ones.

## Not verified
On the simulator and with a fake kernel only. Not measured on the rig: that a bead found by its last-seen position
is the same bead (a neighbour's rings could be picked up), and why the restart frames read mostly low in z (the
single centring pass from a start some px off is the assumed cause).
