# 0 — Start-up, structure and shared state

Facts that span the experiment steps. Form and evidence levels: [README.md](README.md).

### F0.01 — Program structure: one outer sequence, three While loops

- **Trigger:** the user presses LabVIEW's Run arrow.
- **Inputs:** none.
- **Steps:**
  1. The diagram is a chain of flat-sequence frames (57 flat-sequence frames, 11 stacked-sequence frames, 76 case
     frames, 5 event frames, 17 For loops, 3 While loops; 170 diagrams in all).
  2. **Picking loop** (While loop uid 15173, diagram D99, inside frame D98): live image, bead clicks, manual focus and
     manual motor commands. Its stop terminal is wired to `Done Picking \nBeads?` (wire 19456).
  3. **Frame loop** (While loop uid 637, D43) and **motor loop** (While loop uid 25380, D20) sit side by side in one
     flat-sequence frame (D19), so they run in parallel, and only during the experiment.
  4. Frames after the loops save the traces (D19, after the loop) and shut down (D83).
- **Outputs:** none.
- **Moves hardware?** no (structure only).
- **Timing and errors:** no queue, notifier or semaphore exists; loops share state through panel objects (local
  variables, `Value` property nodes) and one VI Global (F0.07). The execution order of the outer frames is
  `unknown — the flat-sequence owner chain stops at uid 0 (V6:docs/main-vi-stop-and-save.md:30-34); needs a VI read`.
  The order used in this specification (start-up → picking → calibration → tracking → save) is *inferred* from
  what each frame reads and writes.
- **Evidence:** wiring — `V6:docs/frame-loop-anatomy.md` (loop map), `V6:docs/main-vi-state.md` section "Why the shape of the main VI matters here" (diagram
  census), `V6:docs/main-vi-stop-and-save.md` section 1, "CLOSED 2026-09-17" (stop terminal uids 648 / 25410 / 15276 and their wires),
  `V6:docs/main-vi-panel-map.md:359` (wire 19456 = `Done Picking \nBeads?`), node labels of D19 (two While loops)
  and D98 (one While loop) in `V6:tools/bench/main_vi_node_labels.json`.
- **Owner's intent:** the motor loop was split off in version 4.4 because motor commands delayed the frame loop
  (owner, recorded in `V6:docs/frame-loop-anatomy.md` section "Why this explains the user's instinct").
- **Port:** change — the port uses its own threads and processes (decisions 0002, 0005); the behavior of each
  feature below is what must match.

### F0.02 — Camera open and configure

- **Trigger:** start-up frame D87.
- **Inputs:** none from the panel; the camera's saved NI MAX settings.
- **Steps:** `IMAQdx Open Camera` → `IMAQdx Configure Grab` (a ring of buffers) → an IMAQdx property node reads
  `Height` and `Width` → `IMAQ Create` makes the image buffer. Opening the camera resets its ROI to full frame and
  resets the exposure.
- **Outputs:** `Width`, `Height` (indicators, read-backs), `CamSessionOut`, `IMAQimage` (session and image
  references shown on the panel).
- **Moves hardware?** no.
- **Timing and errors:** once. Error handling `unknown — needs VI read`.
- **Evidence:** wiring — `V6:docs/camera-acquisition-facts.md:479-616` (uid 9775 reads the geometry; D87 is the
  configuration frame), `:418-459` (open resets ROI and exposure, measured through the driver).
- **Owner's intent:** answered (Q0.02, owner 2026-10-22): the program sets the camera from device-settings presets and
  saves them with the data, rather than relying on NI MAX — "경우에 따라 장비 셋팅을 바꿔야하는 일이 종종 있음. 가장
  대표적으로는 카메라 셋업. Frame rate은 어떻게 할 것이며, signal magnification은 무엇이며, acquisition mode는 무엇이며,
  등등... 이 정보도 프리셋 적용하고, 데이터와 함께 저장하면 좋겠는데". Presets are applied after every open (the open
  resets ROI and exposure), read back and verified before acquisition; the file stores the preset, the read-back values
  and the measured frame rate ([ui-requirements.md](ui-requirements.md) U15; fields in
  [hdf5-v1.md](../format/hdf5-v1.md)).
- **Port:** port — the port opens the camera through its own layer (`docs/manuals/`), with the same geometry.

### F0.03 — Magnet motor (PI) connection and travel limits

- **Trigger:** start-up frame D91.
- **Inputs:** `Trans Speed (mm/s)`.
- **Steps:** `Mercury_GCS_Configuration_Setup.vi` opens the PI controller (M-126.PD1, COM3) → `VEL` (velocity from
  `Trans Speed (mm/s)`) → `GOH` → `TMX?` / `TMN?` read the travel limits.
- **Outputs:** `Max Travel Limit`.
- **Moves hardware?** **yes — `GOH` moves the magnet motor to its home position**, and `VEL` sets its speed.
- **Timing and errors:** once. Errors `unknown — needs VI read`.
- **Evidence:** wiring — node census of D91 (`V6:tools/bench/main_vi_node_labels.json`, `main_vi_subvis.json`);
  `V6:docs/motor-call-site-census.md` count table (GOH on D4 and D91).
- **Owner's intent:** ask (Q0.03).
- **Port:** port, through the project's motion gate.

### F0.04 — Magnet initial position (`Autoreference? 1=Y`)

- **Trigger:** start-up stacked sequence (uid 3593, frames D2 and D5).
- **Inputs:** `Autoreference? 1=Y`, `If no: current pos z?`, `Trans Speed (mm/s)`.
- **Steps:**
  1. D2: `Equal?` compares `Autoreference? 1=Y` with a constant; the case (uid 3826) then either
     moves with `MOV` to `If no: current pos z?` (D3) or runs `GOH` (D4). Which value selects which frame is
     *inferred* from the labels (1 = reference move).
  2. D5: `VEL` from `Trans Speed (mm/s)`, then `POS?` reads the position, which is written to the VI Global field
     `Trans position` and the indicator `Trans Pos (mm)`.
- **Outputs:** `Trans Pos (mm)`, `Trans position` (F0.07).
- **Moves hardware?** **yes — magnet motor (`MOV` or `GOH`).**
- **Timing and errors:** once.
- **Evidence:** wiring — `V6:docs/main-vi-startup.md` table rows 2-5; panel wiring rows 43/44
  (`V6:docs/main-vi-panel-map.md:323-324`).
- **Owner's intent:** the four greyed-out controls at the top right tell the program where things are before a run
  (owner, `V6:docs/main-vi-panel-map.md:28-30`).
- **Port:** port.

### F0.05 — Focus stage (ASI) start-up

- **Trigger:** start-up frames D88–D90, and D9–D14.
- **Inputs:** `Set Focus  (0->50)` (note the double space), `Focus Pos (Start)`.
- **Steps:** `ASI TG-1000 Initialize` (115200 baud, 500 ms timeout, COM4) → `Move Axis to Position` to a value passed
  through `In Range and Coerce` → `Wait (ms)` → `Get Current Position`. The same three-step pattern appears twice:
  D88–D90 (input `Focus Pos (Start)`, which D87 also writes through a property node) and D10–D12 inside D9 (input
  `Set Focus  (0->50)`, guarded by `x = 0?`; D13 holds a coerce, D14 is empty). Whether both run in one start-up,
  and the coerce limits, are `unknown — needs VI read`.
- **Outputs:** the ASI VISA session (kept for F1.02, F3.02, F4.06).
- **Moves hardware?** **yes — the ASI focus axis moves to the start focus.**
- **Timing and errors:** once; the wait constant is unread.
- **Evidence:** wiring — `V6:docs/main-vi-startup.md` table row 10, `V6:docs/motor-call-site-census.md` count table (Move Axis to
  Position on D10, D88, D151, D167).
- **Owner's intent:** ask (Q0.05).
- **Port:** port.

### F0.06 — Rotor (Autonics) connection and the told position

- **Trigger:** start-up frames D92 (configure) and D8/D9.
- **Inputs:** `Current pos rot?` (the operator types the rotor's current angle).
- **Steps:** Autonics `Configure.vi` opens the rotor port (COM5). The rotor angle is written to the VI Global field
  `Rot position` (D8), on the same wire as the indicator `Rot pos (deg)` (wire 7152). That `Current pos rot?` is
  the source of that wire is *inferred* (its terminal enters the start-up sequence, uid 3593).
- **Outputs:** `RotationVISA` (rotor session), `Rot pos (deg)`.
- **Moves hardware?** no (configure only — `CONFIGURE` in the census).
- **Timing and errors:** once.
- **Evidence:** wiring — `V6:docs/motor-call-site-census.md` count table; panel wiring rows 18 and 45; text — the rotor's
  absolute position is told to the program, not read (`V6:docs/main-vi-panel-map.md:39-41`).
- **Owner's intent:** the owner set an arbitrary middle point as rotor zero because the controller did not accept
  negative positions (owner 2026-09-13, `V6:docs/rotor-scheduler-design.md` section "Where zero is"). The zero offset is
  `Baseline Startpoint` = 200 turns inside `SetCommand.vi` (V6 measurement, `V6:docs/questions-for-user-2026-09-14.md`
  item 3). Open: Q0.06.
- **Port:** port the commands unchanged; record the offset (decision 0008, hardware row).

### F0.07 — Shared motor positions (`Global motor pos.vi`)

- **Trigger:** written at start-up (D5, D8), when the experiment ends (D19, after the frame loop) and at shutdown (D83).
- **Inputs:** positions from F0.04, F0.06 and the frame loop.
- **Steps:** a VI Global with three DBL fields — `Trans position`, `Rot position`, `Focus position`. All seven
  accesses in the main VI are writes; nothing in this hierarchy reads it.
- **Outputs:** none inside the program.
- **Moves hardware?** no.
- **Timing and errors:** none.
- **Evidence:** wiring — `V6:docs/main-vi-state.md` sections 1-2.
- **Owner's intent:** it was probably added to keep all motor positions in one VI for readability (owner
  2026-09-14, `V6:docs/main-vi-state.md` section "the user's reading"). Open: Q0.07 (does another program read it?).
- **Port:** drop if Q0.07 confirms no outside reader (the session-state file of decision 0007 replaces it).

### F0.08 — Panel reset at start, busy cursor

- **Trigger:** start-up frames D1, D15, D17; also D97 and D145.
- **Inputs:** none.
- **Steps:** D1 writes `Auto-reset zero`, `# of Auto-Reset`, `Lost Frame Message` through `Value` property nodes,
  disables `continue tracking`, and reinitialises `Force (pN) vs Extension (nm) ` to its default. D15, D17, D97,
  D145 call `Set Cursor.vi` (busy / normal cursor). D17 makes `Image` or `Picture` visible and clears
  `File # Saved`. The written values are `unknown — needs VI read`.
- **Outputs:** the panel state above.
- **Moves hardware?** no.
- **Timing and errors:** once each.
- **Evidence:** wiring — implicit `Value` nodes on D1 (`V6:docs/main-vi-panel-map.md:574-597`), node labels of D15,
  D17, D97, D145.
- **Owner's intent:** ask (none needed unless a value matters).
- **Port:** change — the GUI resets its own state (decision 0008, UI row).

### F0.09 — Magnet travel limit (`Max Trans Pos.vi`)

- **Trigger:** frames D87 (start-up) and D19 (experiment frame).
- **Inputs:** none from the panel.
- **Steps:** `Max Trans Pos.vi` returns the magnet's maximum allowed position; D87 also computes `Cal Zero` from a
  subtraction (`x-y`) whose operands are `unknown — needs VI read`.
- **Outputs:** `Max Trans Pos`, `Cal Zero`.
- **Moves hardware?** no.
- **Timing and errors:** whether every magnet move is clamped by this value is **not shown**: no motion call
  shares a diagram with `Max Trans Pos.vi` (`V6:docs/motor-call-site-census.md` count table).
- **Evidence:** wiring — D19 / D87 subVI identity (`V6:docs/main-vi-stop-and-save.md` section 2), panel row 89.
- **Owner's intent:** `Max Trans Pos` is a per-room parameter (in-VI comment, `V6:docs/GLOSSARY.md` section "Per-room parameters"). Q0.09.
- **Port:** change — the port's motion gate enforces the envelope on every move (CLAUDE.md rig rules).

### F0.10 — Error reporting

- **Trigger:** errors on the error wires.
- **Inputs:** error clusters.
- **Steps:** `Simple Error Handler.vi` on D1 and twice on D83 shows a dialog. Many error outputs are left unwired
  (for example the ASI moves in autofocus and `ASI Close`), so those errors are never reported.
- **Outputs:** `error out 2` (indicator; its source is `unknown — needs VI read`).
- **Moves hardware?** no.
- **Timing and errors:** a dialog stops the user until it is closed.
- **Evidence:** wiring — `V6:docs/main-vi-stop-and-save.md` section 3, `V6:docs/autofocus-case-10407.md` section "Outputs".
- **Owner's intent:** ask (Q0.10).
- **Port:** change — every device error is logged and shown without blocking the frame loop (decision 0007).
