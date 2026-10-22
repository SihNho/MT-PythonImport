# 4 — Experiment

Tracking runs in the frame loop (While loop uid 637, D43) beside the motor loop (F1.09). Form and evidence levels:
[README.md](README.md). Every frame-loop iteration runs the tracking kernel unconditionally; the other parts run in
case frames.

### F4.01 — Pre-tracking check (`continue tracking`)

- **Trigger:** start-up frame D16, after calibration (order *inferred*, F0.01).
- **Inputs:** `continue tracking`, the focus keys (F1.02), the camera session, the bead list.
- **Steps:** `grayscale color table.vi`, then `check N bead pos v3-kimlab.vi` shows the live image in `Image` with
  the beads and lets the user adjust focus; it returns when `continue tracking` is pressed. D9 and D17 re-arm the
  button through property nodes.
- **Outputs:** `exp/ref \narray`, `x,y blank z array` (start positions for F4.04).
- **Moves hardware?** **yes — ASI focus, through the subVI (`COMMAND` in the census).**
- **Timing and errors:** blocks until the button.
- **Evidence:** wiring — `V6:docs/main-vi-panel-map.md:550` (control references to the subVI),
  `V6:docs/motor-call-site-census.md` count table.
- **Owner's intent:** ask (Q4.01).
- **Port:** port.

### F4.02 — Experiment set-up

- **Trigger:** frames D17–D19 before the frame loop starts.
- **Inputs:** `# FD points`, `# DT points`, `Mp measure freq`, `Start Cycles`, `TurnOff`, `Mag Position`, the cal
  clusters (F3.06).
- **Steps:** arrays are initialised with sizes from `# FD points` and `# DT points`; the frame loop's 14 shift
  registers are initialised (positions, `Bead is good?` flags, `LastBufferNumber`, the data array, `F-x out`
  uninitialised, …); D18 reads `Start Cycles`, `TurnOff` and `Mag Position` and computes the exp / ref indices
  (F2.04).
- **Outputs:** initial state of F4.03–F4.11.
- **Moves hardware?** no.
- **Timing and errors:** once.
- **Evidence:** wiring — `V6:docs/main-vi-state.md` section "Per-frame state (the frame loop's shift registers)";
  panel rows 25, 93, 97 land on D19.
- **Owner's intent:** ask (Q4.02: meaning of `# FD points` and `# DT points`).
- **Port:** port.

### F4.03 — Frame acquisition and lost frames

- **Trigger:** every frame-loop iteration.
- **Inputs:** the camera session; `LastBufferNumber` (shift register).
- **Steps:** `get buff image-lost frames.vi` calls `IMAQdx Get Image` with an explicit buffer number
  (`Buffer to extract`, the requested buffer) and returns `current image number` (the buffer actually delivered)
  and `Missed frames?` (requested ≠ delivered). The lost count is accumulated.
- **Outputs:** the image (to F4.04); `current image number`; `Missing Frames?`; `Total Lost Frames` (local writes on
  D1 and D83, terminal on D78); `Lost Frame Message` at the end (F5.03).
- **Moves hardware?** no.
- **Timing and errors:** one buffer per iteration; at 90 Hz the camera keeps running and buffers that are overwritten
  before they are read are lost.
- **Evidence:** wiring — wiki `V6:docs/wiki/subvi/get buff image-lost frames.json` (pane, `Buffer Number Mode`
  constant, `x-y`, `x = 0?`); `V6:docs/frame-loop-wire-graph.md:179` (wire 5416 `Buffer to extract`); data — the
  `.tra` frame column has 124 gaps (largest 41 frames) in the recorded file.
- **Owner's intent:** the frame number is `current image number − first image number`; camera buffer numbers keep
  counting through dropped frames, so lost frames show as gaps (owner 2026-09-01, `V6:docs/fixture-recording.md`).
- **Port:** port the numbering; change — also store the absolute buffer number (decisions 0005, 0006).

### F4.04 — Tracking each bead (the kernel)

- **Trigger:** every frame-loop iteration, unconditionally.
- **Inputs:** the image; `Array of cal clusters`; the real-space cosine window and the Hilbert bandpass; cross size;
  `# of bead 4 packs` / `4 pack remainder`; the previous positions (`pos in cal image in`, shift register); the
  start positions and good flags from F4.05.
- **Steps:** `Track N beads four-fold over-kernel-v3.vi` (uid 5058, the only call site) returns x, y (pixels), z
  (µm, *inferred*) per bead, the index of the closest calibration slice per bead, and the good flags.
- **Outputs:** `x,y,z array out`, `pos in cal image out` (shown in `Pos within cal image` and `Pos: Diffraction
  Pattern`, wire 121; the x-axis length of that graph comes from `# of Points`), `Bead is good? array out`.
- **Moves hardware?** no.
- **Timing and errors:** a lost bead returns −1 in x, y, z and `pos`; z is pinned at 5.9 (= (S − 1) × z step) at the
  top of the calibration range. The kernel computes in single precision in places (z = 5.900000087916851 in the
  `.tra` is a single-precision 5.9).
- **Evidence:** wiring — `V6:docs/main-vi-stop-and-save.md` section 4 (the 16 kernel terminals);
  `V6:docs/MAIN_VI_MAP.md` section 3b item 4; data — recorded `.tra` (13 values of −1 and 13 of 5.9 in z).
- **Owner's intent:** the numbers must stay identical (CLAUDE.md, decision 0003).
- **Port:** port, numerically identical; the computation is specified by the NumPy reference (decision 0003).

### F4.05 — Lost-bead reseed and auto-reset

- **Trigger:** every frame-loop iteration.
- **Inputs:** `Auto-Reset`, `Reset Tracking`, `Limit of Program`, `min value` (indicator), `# of Auto-Reset`,
  `Auto-reset zero`.
- **Steps:**
  1. `min value` = minimum of `pos in cal image out` (`Array Max & Min`). Lost term = `min value < 0` (constant I32
     0), read back through a property node of the indicator.
  2. `And` with `Auto-Reset` → selects the auto-reset case (uid 10445: D70 writes `# of Auto-Reset`, D71
     increments it) and, negated, disables autofocus (F4.06).
  3. `Or` with `Reset Tracking` → selects case uid 5540, placed between the shift registers and the kernel input:
     one frame passes the previous positions and flags, the other passes the start positions (the calibration
     positions with z blank) and all-true flags. Both frames are pass-through only.
  4. `Reset Tracking` is reset by a property write (D82).
  5. `# of Auto-Reset` equal to `Limit of Program` (`Equal?`, equality not ≥) feeds the stop condition (F5.01).
  The periodic term (`Quotient & Remainder` of the loop counter by a period that enters the loop from outside,
  uid 10114) and the use of `Auto-reset zero` are `unknown — needs VI read`.
- **Outputs:** `# of Auto-Reset`, `min value`; the kernel's next start state.
- **Moves hardware?** no.
- **Timing and errors:** the original reads `min value` through a property node with no wire ordering against its
  write — a race; on the recorded file "this frame's minimum" reproduces the `.tra` exactly.
- **Evidence:** wiring — `V6:docs/stage2-assembly-step-e.md` (all four selector feeders, case 5540's two frames
  5582 / 5592), `V6:docs/camera-acquisition-facts.md` section "MEASURED 2026-09-16 (master plan A6)"; data — the
  reseed rule reproduces the `.tra` with deviation 0 over 10,043 frames.
- **Owner's intent:** `Limit of Program` is the maximum number of auto-resets in one run; an overnight run loses
  beads, and past this many the program stops and saves what it has (owner 2026-09-15, `V6:docs/GLOSSARY.md`).
  The current frame's minimum is the right reading (owner 2026-09-15: "min value는 이번 장면 기준이 맞는 듯").
- **Port:** port; change — read this frame's minimum by direct dataflow (the owner's 2026-09-15 choice; Q4.05
  confirms it for this port).

### F4.06 — Autofocus

- **Trigger:** frame counter mod `Frame rate` = 0 (25 → every 25th frame) AND NOT `Fix to a Certain Pattern`.
- **Inputs:** `Frame rate` (despite its name, the autofocus period in frames), `Auto-Focus`,
  `Limit of Auto-Focus`, `Fix to a Certain Pattern`, `Focus Deviation from the Center`, `# slices in stack`, the
  slice index of bead index 0.
- **Steps:**
  1. enable = NOT(lost-bead `And` of F4.05) AND `Auto-Focus` AND (a counter from case 10445 < `Limit of Auto-Focus`);
     `Fix to a Certain Pattern` is written with NOT(enable).
  2. Case uid 10407 (D73 when firing; D72 passes the position through):
     move = clamp((slice index of bead 0 − # slices / 2 + `Focus Deviation from the Center`) × 1.0, −0.2, +0.2)
     → `ASI Move Axis Relative` by that amount → `Get Current Position` → `Focus Pos (Track)`.
  There is no dead band: every firing sends a move, zero when the bead is on the set-point.
- **Outputs:** `Focus Pos (Track)`; `Fix to a Certain Pattern` (written by the program).
- **Moves hardware?** **yes — ASI focus axis, at most ±0.2 internal units per firing (about 3.6 times a second at
  90 Hz).**
- **Timing and errors:** a serial exchange inside the frame loop; its errors are not wired.
- **Evidence:** wiring — `V6:docs/autofocus-case-10407.md` (the computation, constants −0.2 / +0.2 / 2.0 / 1.0),
  `V6:docs/camera-acquisition-facts.md` sections "NAMED 2026-09-16" and "N = the front-panel control Frame rate".
  The `Axis` enum value is unread.
- **Owner's intent:** ask (Q4.06: the meaning of `Fix to a Certain Pattern`; units of the ±0.2 step).
- **Port:** port the computation; change — the ASI runs in its own thread, off the acquisition path (CLAUDE.md
  rule 6), and `Frame rate` gets an honest name (decision 0008, UI row).

### F4.07 — Cycle schedule table (`CycleSchedule`)

- **Trigger:** the user edits `CycleSchedule` or `NumCol`; handled by the frame loop's event structure (uid 10153).
- **Inputs:** `CycleSchedule` (rows = items, columns = cycles), `NumCol`.
- **Steps:** D47 (`"CycleSchedule": Value Change`, per `V6:docs/MAIN_VI_MAP.md` section 3b): whole-row edits with
  `Replace Array Subset`, sets `NumCol` to the column count and writes `Mag Position`. D46: `Array Subset` of
  `CycleSchedule` to `NumCol` columns (the `NumCol` event, *inferred*). D45: only an event-data node (timeout,
  *inferred*).
- **Outputs:** `CycleSchedule`, `NumCol`, `Mag Position`.
- **Moves hardware?** no — the schedule is a reservation until `Start Cycles`.
- **Timing and errors:** the event structure sits in the frame loop; its timeout value is unread.
- **Evidence:** wiring — node census D45–D47; `V6:docs/rotor-scheduler-design.md` section "The table's shape".
- **Owner's intent:** rows are fixed (the items: speed, force, wait), columns grow as the user types, and the table
  is only a reservation until the start button is pressed (owner 2026-09-12, `V6:docs/rotor-scheduler-design.md`).
- **Port:** port; change — a table widget in the GUI.

### F4.08 — Force-clamp cycling (3-state clamping)

- **Trigger:** `Start Cycles`; runs in the frame loop (D43 and its case frames D44, D48, D49, D56–D69).
- **Inputs:** `CycleSchedule`, `Set # of Cycles`, `Switch`, the magnet-position-to-force table (D42:
  `Magnet2Force v3_for M270.vi` over magnet positions, with `Mag pos when touched to glass`).
- **Steps (structure measured, transitions *inferred* from node labels):**
  1. Start (D59): `Start Cycles`, `SubCycle`, `Switch` and `Start Moving?` are written; D56 / D57 store
     `Cycle Start Time` from `Tick Count (ms)`.
  2. Move (D69): `SubCycle` + 1; two `Index Array` reads of `CycleSchedule` → `VEL` (speed) and `MOV` (magnet
     target, `Target`); `Start Moving?` cleared. A target force is turned into a magnet position with
     `Threshold 1D Array` on the force table (D48, *inferred*).
  3. Wait to arrive (D61): |target − position| < tolerance (`abs(x)`, `x < y?`) → `Reached clamp`;
     `Time span after start (min)` = floor(elapsed ms / 60000).
  4. Hold (D64, D66, D67): `Initial Time at Start` from `Tick Count (ms)`; when the elapsed time passes the wait,
     `Start Moving?` is set again for the next column.
  5. `Total cycle #` = `Set # of Cycles` × columns; `Estimated end time (min)` from the schedule (D44 sums
     |Δposition| / speed per column, *inferred*).
  Which three states the name "3StateClamping" refers to, the arrival tolerance, the wait unit, and what happens
  after the last cycle are `unknown — needs VI read and Q4.08`.
- **Outputs:** `SubCycle`, `Start Moving?`, `Reached clamp`, `Initial Time at Start`, `Cycle Start Time`,
  `Time span after start (min)`, `Estimated end time (min)`, `Total cycle #`; the debug indicators `Target`,
  `x < y?`, `abs(x)`, `Value`.
- **Moves hardware?** **yes — magnet motor (`VEL`, `MOV` on D69), from the frame loop.** The rotor is not in the
  schedule.
- **Timing and errors:** the moves are serial calls inside the frame loop; time comes from `Tick Count (ms)`
  (wraps after 49.7 days).
- **Evidence:** wiring — node census D42–D69 (`V6:tools/bench/main_vi_node_labels.json`), `MOV` / `VEL` on D69
  (`V6:docs/motor-call-site-census.md` count table); `V6:docs/restructure-plan-4.6.md` G3 ("the cycle-execution logic
  lives inside the frame loop"); `V6:docs/MAIN_VI_MAP.md` section 4 item 3 (transitions not traced).
- **Owner's intent:** move the magnet first, then the rotor; the rotor value absolute in degrees — a requested
  future row, not in the original (owner 2026-09-12, `V6:docs/rotor-scheduler-design.md`). Q4.08.
- **Port:** port the schedule semantics exactly; change — the scheduler runs in its own thread and commands the
  motor thread (decision 0005), never from the acquisition path.

### F4.09 — Live Z and dZ plots

- **Trigger:** every frame-loop iteration; case on `Z/dZ`.
- **Inputs:** `Z/dZ`, `Correction Factor`, `x,y,z array`, the exp / ref indices.
- **Steps:** D76 `N bead plot Z.vi` (z of each bead) or D75 `N bead plot dZ.vi` (z relative to the reference bead,
  *inferred* from `z index of first ref`), both scaled by `Correction Factor`.
- **Outputs:** the plot (indicator not identified on the panel list — `unknown`).
- **Moves hardware?** no.
- **Timing and errors:** front-panel drawing in the UI thread.
- **Evidence:** wiring — node census D75, D76; panel rows 20, 21.
- **Owner's intent:** ask (Q4.09: what `Correction Factor` corrects — the oil/water index note in the `.tra`
  header?).
- **Port:** change — plotted by the GUI at display rate.

### F4.10 — Force–extension analysis (WLC)

- **Trigger:** every frame-loop iteration (`WLC function sub.vi`, uid 1114, index = loop counter).
- **Inputs:** `Lc`, `Lp`, `Baseline`, `Exp Baseline`, `+ -> Lc`, `x -> Lc`, `# DT points`,
  `Force\nsmoothing\nhalf-width`, `Extension\nmedian filter\nhalf-width`, the magnet position and z traces.
- **Steps:** force from magnet position (`Magnet2Force v3_for M270.vi`, D42 / D74) with FIR smoothing and a median
  filter; extension from z minus the baseline; a worm-like-chain curve from `Lc` / `Lp`; D53–D55 handle the
  baseline and the graph scales; D50 median-filters the extension.
- **Outputs:** `Force (pN) vs Extension (nm) `, `Extension (nm) vs Time (Frame #)`; `Value 2` and `Value 3` may be
  debug read-backs here (`unknown`).
- **Moves hardware?** no.
- **Timing and errors:** display analysis; not written to the `.tra`.
- **Evidence:** wiring — `V6:docs/frame-loop-anatomy.md` (uid 1114 pane: `Lp`, `Lc`, `Baseline`, `F-x in/out`);
  node census D42, D50, D53–D55, D74.
- **Owner's intent:** ask (Q4.10: which magnet calibration `Magnet2Force v3_for M270` applies to; is this display
  needed in the port?).
- **Port:** change — moves to the application's basic analysis (decision 0006 item 4), off the frame path.

### F4.11 — Trace recording and file names

- **Trigger:** every frame-loop iteration (`save trace.vi`, uid 376); file names at set-up (D8, D9).
- **Inputs:** this frame's data (frame number, `Trans Pos (mm)`, `Rot pos (deg)`, x, y, z per bead), the `.cal`
  path, `File Size`.
- **Steps:**
  1. D8 / D9: the `.cal` file's path (from the refnum of F3.05) becomes `Cal File Path`; `Replace Substring` makes
     the trace path (`cal002` → `tra002`, *inferred* from the recorded pair) → `Track File Path`.
  2. Each frame: the row is appended to `total data array` (shift register). `save trace.vi` checks the row count
     against the file size (`Quotient & Remainder`, `x = y?`) and, when a file is full, calls
     `save N xyz traces.vi` to write it and increments `file number to append` (suffix `-000`, `-001`, …).
  3. After the loop the remaining rows are written (F5.02).
- **Outputs:** `file progress`, `File # Saved`, `File Size`, `Track File Path`, `Cal File Path`; `.tra` files.
- **Moves hardware?** no.
- **Timing and errors:** a full-file write happens inside the frame loop (a stall can lose frames).
- **Evidence:** wiring — wiki `V6:docs/wiki/subvi/save trace.json`, `save N xyz traces.json`;
  `V6:docs/main-vi-stop-and-save.md` section 2; data — the recorded header says
  `actual data points/nominal: 10043/2000000`.
- **Owner's intent:** ask (Q4.11).
- **Port:** port the `.tra` byte for byte (decision 0006); change — writing happens in a writer thread, and the
  HDF5 file is written alongside ([../format/hdf5-v1.md](../format/hdf5-v1.md)).
