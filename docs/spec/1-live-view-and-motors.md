# 1 — Live view and motors

The live image and the manual commands. In the original they run in two places: in the picking loop (D99) before
the experiment, and in the motor loop (D20) during the experiment. Form and evidence levels: [README.md](README.md).

### F1.01 — Live image display

- **Trigger:** every iteration of the picking loop (D99).
- **Inputs:** the camera session (F0.02); `Frame rate`.
- **Steps:** `IMAQdx Grab` (newest buffer) → `IMAQ ImageToArray` → `Flatten Pixmap` with the grayscale colour table →
  `Draw Flattened Pixmap` into the `Picture` indicator, then the bead overlay (F2.02). D97 sets the zoom from
  `Height` / `Width` and the picture's draw area. The colour table is built at start-up: `grayscale color table.vi`
  gives `Color table`; D87 with its case frames D93 / D94 and For loops D95 / D96 encodes it into
  `color table string` (16-bit words, big-endian — the picture's data string; *inferred* from wire 14726).
  D99 also takes `iteration mod Frame rate == 0` (Quotient & Remainder, `Equal To 0?`); what that gates there is
  `unknown — needs VI read`.
- **Outputs:** `Picture`, `Color table`, `color table string`.
- **Moves hardware?** no.
- **Timing and errors:** as fast as `IMAQdx Grab` returns; no explicit wait.
- **Evidence:** wiring — node census of D97, D99 (`V6:tools/bench/main_vi_node_labels.json`); panel rows 68, 69, 83,
  98 (`V6:docs/main-vi-panel-map.md`).
- **Owner's intent:** a live image at 10 Hz is enough, ideally adjustable at run time; if live display costs even
  one measured frame, display through another program is acceptable (owner 2026-09-14,
  `V6:docs/questions-for-user-2026-09-14.md` item 4).
- **Port:** change — display in the GUI process at an adjustable rate, never on the acquisition path (decision
  0005, CLAUDE.md rule 6).

### F1.02 — Manual focus (ASI) with keys

- **Trigger:** `Focus Step (F1)`, `+ Inc (PgUp)`, `- Inc (PgDn)` (keyboard shortcuts on the buttons).
- **Inputs:** the three buttons, passed as control references.
- **Steps:** `ASI_adjust focus-subvi.vi` reads the buttons through references each call; when one is pressed it sends
  `Move Axis to Position` and reads the position back (`Get Current Position`), with a fixed `Wait (ms)` whose
  constant is unread. Called from the picking loop (D99), the frame loop (D43) and the pre-tracking check (D16, via
  `check N bead pos v3-kimlab.vi`). The step sizes behind the three buttons are `unknown — needs a read of the subVI`.
- **Outputs:** `Focus Pos (Track)` (written on D99).
- **Moves hardware?** **yes — ASI focus axis.**
- **Timing and errors:** two UI-thread `Value` reads every call; the serial exchange only while a key is pressed. In
  the frame loop this is a serial call on the acquisition path.
- **Evidence:** wiring — `V6:docs/camera-acquisition-facts.md` section "ANSWERED: the frame loop does NOT transact
  serial every iteration", `V6:docs/main-vi-panel-map.md:548-562` (control references),
  `V6:docs/motor-call-site-census.md` count table.
- **Owner's intent:** focus adjustment happens often during real runs (owner 2026-09-15,
  `V6:docs/camera-acquisition-facts.md`).
- **Port:** change — the ASI is owned by its own device thread; the GUI sends requests (CLAUDE.md rule 6).

### F1.03 — Magnet manual move (`Send to Trans`)

- **Trigger:** `Send to Trans`.
- **Inputs:** `Trans Step (mm)`, `Trans Speed (mm/s)`.
- **Steps:** picking phase (D127–D130): case on `Send to Trans` → `VEL` from `Trans Speed (mm/s)` → `MOV` → the button
  is reset and `Trans Step (mm)` is written (value `unknown`). Experiment phase: the same buttons go by reference to
  `Motor control v5_No Recording.vi` in the motor loop (F1.09). Whether `Trans Step (mm)` is an absolute target or
  a relative step is `unknown — needs VI read` (the label says step; `MOV` is absolute).
- **Outputs:** `Trans Pos (mm)` via F1.08.
- **Moves hardware?** **yes — magnet motor (`VEL`, `MOV`).**
- **Timing and errors:** one move per press; no travel clamp found on this path (F0.09).
- **Evidence:** wiring — node census D127–D130; implicit `Value` nodes for `Send to Trans` (D20, D130) and
  `Trans Step (mm)` (D130) (`V6:docs/main-vi-panel-map.md:591-613`); `MOV` on D129
  (`V6:docs/motor-call-site-census.md` count table).
- **Owner's intent:** ask (Q1.03).
- **Port:** port, through the motion gate.

### F1.04 — Magnet presets `+ Cal Zero` / `- Cal Zero`, and `Cal Zero`

- **Trigger:** `+ Cal Zero` or `- Cal Zero`.
- **Inputs:** the buttons; the preset positions are inside the diagram (`unknown — constants unread`).
- **Steps:** each button: case → `Initialize Array` → `MOV` to the preset → reset the button. Present in the motor
  loop's frame D21 (D34–D41) and in the picking loop's frame D100 (D119–D126). `Cal Zero` is an indicator
  computed on D87 and read on D21 / D100.
- **Outputs:** `Cal Zero`.
- **Moves hardware?** **yes — magnet motor (`MOV`).**
- **Timing and errors:** one move per press.
- **Evidence:** wiring — node census D34–D41, D119–D126; `MOV` on D36, D40, D121, D125
  (`V6:docs/motor-call-site-census.md` count table); text — the name means a magnet-motor preset, not a calibration.
- **Owner's intent:** `Cal Zero` is magnet position 0 and `+ Cal Zero` a position between 36 and 38; `- Cal Zero`
  is legacy and believed unused (owner, `V6:docs/main-vi-panel-map.md:61-74`). The wiring shows `- Cal Zero` is
  still reachable (it is read on D21 and D100 and drives a `MOV`). Q1.04.
- **Port:** change — rename the presets (decision 0008 names this case); drop `- Cal Zero` only on the owner's
  decision, because the wiring shows it is reachable.

### F1.05 — Magnet `HOME`, `Stop Trans`, `Send`

- **Trigger:** `HOME`, `Stop Trans`, `Send` during the experiment.
- **Inputs:** the buttons, passed by reference to `Motor control v5_No Recording.vi` (D20).
- **Steps:** handled inside the motor subVI (it calls `MOV`, `MVR`, `GOH`, `POS?`, `VEL`, `SetCommand.vi`). Which
  command each button sends is `unknown — needs a read of the subVI`. `Stop Trans` reaches the input
  `Stop one-way`.
- **Outputs:** `Trans Pos (mm)`, `Rot pos (deg)` written by reference.
- **Moves hardware?** **yes — magnet motor; possibly the rotor.**
- **Timing and errors:** in the motor loop, parallel to the frame loop.
- **Evidence:** wiring — `V6:docs/main-vi-panel-map.md:551` (references to the motor subVI);
  `V6:docs/rotor-scheduler-design.md` section "RESOLVED: multi-turn works" (callees of the subVI).
- **Owner's intent:** ask (Q1.05).
- **Port:** port, through the motion gate.

### F1.06 — Rotor one turn `1 L-Turn` / `1 R-Turn`

- **Trigger:** `1 L-Turn` or `1 R-Turn`.
- **Inputs:** the buttons; `Rot \nSpeed` is not read on this path.
- **Steps:** case → `SetCommand.vi` (relative move, `Ring` = `MovePosRel` *inferred*, one turn) → reset the button.
  In the motor loop frame (D22–D29) and the picking loop frame (D101–D108).
- **Outputs:** none directly (position via F1.08).
- **Moves hardware?** **yes — rotor.**
- **Timing and errors:** one command per press.
- **Evidence:** wiring — node census D22–D29, D101–D108; `SetCommand.vi` on D24, D28, D103, D107
  (`V6:docs/motor-call-site-census.md` count table).
- **Owner's intent:** relative turns may be used mid-experiment (owner, `V6:docs/rotor-scheduler-design.md` section
  "Consequence: one less step than planned").
- **Port:** port.

### F1.07 — Rotor move by step (`Send to Rot`)

- **Trigger:** `Send to Rot`.
- **Inputs:** `Rot Step (deg) ` (trailing space in the label), `Rot \nSpeed` (newline in the label),
  `Rot step (turns)` (by reference, experiment phase).
- **Steps:** case → `SetCommand.vi` twice: set the speed from `Rot \nSpeed`, then move by `Rot Step (deg) ` →
  reset `Send to Rot` and write `Rot Step (deg) ` (value `unknown`). D30–D33 (motor loop frame) and D109–D112
  (picking loop frame). The angle is cumulative and signed: −7200 turns the rotor 20 times.
- **Outputs:** none directly.
- **Moves hardware?** **yes — rotor.**
- **Timing and errors:** the read-back of a negative position is broken in the original driver: `SetCommand.vi`
  parses the position as unsigned (V6 measurement, `V6:docs/questions-for-user-2026-09-14.md` item 3).
- **Evidence:** wiring — implicit `Value` reads of `Rot \nSpeed` on D32 / D111 and `Rot Step (deg) ` on D32
  (`V6:docs/main-vi-panel-map.md:579-589`); owner — "−7200 then Send to Rot turns 20 times"
  (`V6:docs/rotor-scheduler-design.md`).
- **Owner's intent:** the rotor value is in degrees, absolute in a future schedule row (owner 2026-09-12,
  `V6:docs/rotor-scheduler-design.md`). Q1.07.
- **Port:** port the commands; change — read the position as signed (owner decided this for V6 on 2026-09-13; Q1.07
  confirms it for this port).

### F1.08 — Position read-back (`Trans Pos (mm)`, `Rot pos (deg)`)

- **Trigger:** picking loop D113–D118 (a case whose selector is `unknown`); motor loop through the motor subVI
  (references `tran display ref`, `rot display ref`); frame loop reads both indicators every iteration (F4.11).
- **Inputs:** none.
- **Steps:** rotor `SetCommand.vi` (Get Position) → `Rot pos (deg)` (D115–D116); PI `POS?` → index 0 (D117).
- **Outputs:** `Trans Pos (mm)`, `Rot pos (deg)`.
- **Moves hardware?** no (queries).
- **Timing and errors:** the read times are not recorded; the frame loop writes whatever the indicators hold into the
  trace (decision 0006 adds read times).
- **Evidence:** wiring — node census D113–D118; `POS?` on D117 (`V6:docs/motor-call-site-census.md` count table).
- **Owner's intent:** position must be read as fast as possible during force ramping (owner,
  `V6:docs/rotor-scheduler-design.md` section "Sequencing").
- **Port:** port; change — every reading carries its time stamp (decision 0006).

### F1.09 — Motor loop during the experiment

- **Trigger:** the experiment frame D19 starts it with the frame loop.
- **Inputs:** `Mp measure freq`; the button references of F1.03, F1.05, F1.07; `TurnOff`.
- **Steps:** each iteration calls `Motor control v5_No Recording.vi` once (D20); the rotor buttons and presets are
  handled in the frame D21 beside it (F1.04, F1.06, F1.07). The loop reads `TurnOff` through a property node and
  stops when the frame loop stops (F5.01).
- **Outputs:** `Trans Pos (mm)`, `Rot pos (deg)`.
- **Moves hardware?** **yes — through F1.03–F1.07.**
- **Timing and errors:** `Mp measure freq` reaches the subVI and the D19 set-up; its unit and meaning are
  `unknown — Q1.09`.
- **Evidence:** wiring — `V6:docs/frame-loop-anatomy.md` (loop A), panel rows 93 and 104.
- **Owner's intent:** see F0.01.
- **Port:** change — one device thread per controller (decision 0005); behavior of each command as above.
