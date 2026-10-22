# 2 — Bead picking

The user clicks beads on the live image in the picking loop (D99). Form and evidence levels: [README.md](README.md).

### F2.01 — Click to pick a bead

- **Trigger:** a mouse event on `Picture`, handled by the picking loop's event structure (uid 15544): D139 is a frame
  with only `Time` / `Type` (a timeout frame, *inferred*), D140 is the mouse frame.
- **Inputs:** mouse position and modifiers; `Count`.
- **Steps:** D140 → stacked sequence: D141 takes `Mouse Position` (X, Y) and appends it to `Array of bead x/y pos`;
  D142 converts `Count` to an integer and compares it (`Equal?`) — the case D143 (empty) / D144 (writes `Count`).
  How modifiers change the action (e.g. remove a bead) is `unknown — needs VI read`.
- **Outputs:** `Bead Pos`, `Array of bead x/y pos` (handed to F2.02, F3.02, F4.02).
- **Moves hardware?** no.
- **Timing and errors:** once per click; the timeout value is unread.
- **Evidence:** wiring — node census D139–D144; panel rows 80 and 92 (`V6:tools/bench/main_vi_panel_wiring.json`).
- **Owner's intent:** the first click is the reference bead (owner; see F2.04). Q2.01 for `Count`.
- **Port:** change — GUI widget; same resulting bead list and order.

### F2.02 — Bead overlay on the live image

- **Trigger:** every picking-loop iteration with at least one bead (`Empty Array?` on D99).
- **Inputs:** `Array of bead x/y pos`, `exp/ref array`, `Cross length (pixels)`.
- **Steps:** D132: `rect coord from center.vi` → `Draw Grayed Out Rect.vi` (the region outside the box, *inferred*);
  D133 → For loops: per bead `Draw Circle by Radius.vi` and `Draw Text at Point.vi` with the bead number (D137);
  D134 holds a case (D135, D136, both empty) per bead. D131 and D138 are empty frames of these cases.
- **Outputs:** the overlay on `Picture`.
- **Moves hardware?** no.
- **Timing and errors:** per iteration.
- **Evidence:** wiring — node census D131–D138.
- **Owner's intent:** ask (none needed beyond appearance).
- **Port:** change — drawn by the GUI.

### F2.03 — `Done Picking \nBeads?` ends the picking loop

- **Trigger:** `Done Picking \nBeads?` (newline in the label).
- **Inputs:** the button.
- **Steps:** the button's terminal is the picking loop's stop condition; the program goes on to calibration.
- **Outputs:** none.
- **Moves hardware?** no.
- **Timing and errors:** there is no way back to picking without restarting the program (*inferred* from the
  structure).
- **Evidence:** wiring — wire 19456 is both the picking loop's stop terminal and the button's terminal
  (`V6:docs/main-vi-stop-and-save.md` section 1, "CLOSED 2026-09-17", `V6:docs/main-vi-panel-map.md:359`).
- **Owner's intent:** ask (Q2.03).
- **Port:** port; the GUI may allow going back (to be decided, Q2.03).

### F2.04 — Reference and experiment beads (`exp/ref \narray`)

- **Trigger:** the experiment set-up frame D18; also stored in the `.cal` file (F3.05).
- **Inputs:** the bead list.
- **Steps:** `exp-ref management.vi` returns `index of first ref`, `indices of all ref`, `indices of all exp` and an
  `exp/ref array` (one flag per bead). In the recorded `.cal` the flags are `0,1,1,1,1` for five beads: bead 1 is 0.
- **Outputs:** `exp/ref \narray` (written on D16), the indices used by F4.09.
- **Moves hardware?** no.
- **Timing and errors:** once.
- **Evidence:** wiring — node census D18; data — `cal002` tail (see [../format/tra-cal.md](../format/tra-cal.md));
  data — bead 1 has the smallest z noise in two recordings.
- **Owner's intent:** the first-clicked bead is the reference bead (owner, quoted in
  `V6:docs/autofocus-case-10407.md`, "What the table says" item 3). Q2.04: is there ever more than one reference bead?
- **Port:** port.
