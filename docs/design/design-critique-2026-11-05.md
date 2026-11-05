# Design critique of the GUI, 2026-11-05 (design lint; no code changed)

Korean: [design-critique-2026-11-05.ko.md](design-critique-2026-11-05.ko.md).

**Material.** `src/mtpy/gui/app.py` (the window: top bar, the step bar Setup / Run / Explore / Beads / Calibrate /
Experiment / Save, the two camera views, the graph, the event list), `src/mtpy/gui/calview.py`,
`src/mtpy/gui/exptable.py`, [gui.md](gui.md), the mock-up [2026-10-23-main-window](../mockups/2026-10-23-main-window/README.md),
and screenshots of every page on the simulators (`python -m mtpy.gui --backend sim --sim-dev`, connected, acquisition
running, 1500 x 950 px). Nothing was run on the rig.

**Judged against the owner's words of 2026-11-05.** "The usual experiment is: watch the camera, pick beads, bead
calibration, choose where to save, tracking, save - here everything is scattered"; the user sees the rig only (no
simulator settings); file names follow LabVIEW (cal001, tra001, tra001-000); STOP is the emergency stop.

**Stage.** First build on the simulators, being fixed by running it (owner 2026-10-29). The findings are about
the flow and the wording, not polish.

## Overall impression

The Run page is the right answer to "everything is scattered": one page in the experiment's order. But the page
is still a list of sentences with buttons beside them, the first step's button lives in the top bar, the save
dialogs come after the scan, and the rest of the window still speaks the developer's language (decision numbers,
temporary paths, Python dicts in the event list, example protocols pre-filled that would move the rig). Six
other pages with their own numbers compete with it. The biggest opportunity: make Run the page the user lives
on, and make every other page read as "settings" rather than "steps".

## Findings, ranked by severity

Severity: **critical** = can move the rig or lose data, or blocks the usual experiment; **moderate** = costs a
trip to another page or a guess; **minor** = wording and polish.

### Critical

| # | Panel, widget | Finding | Change |
|---|---|---|---|
| 1 | **Experiment**: the table (`ExpTable`, `EXAMPLE`) and the text editor (`EXAMPLE_PROTOCOL`), buttons "Start from table" and "Start" | Both open **pre-filled with example protocols** (the table: 50 pN and a -3600 / +3600 degree rotation; the text: a 1 -> 5 pN ramp). On the rig, one press of either Start runs them - Check passes, the values are inside the limits. The example is the owner's own table, which makes it look like the real plan. | Open both empty (the table with one zero column); put the example behind a "Load example" button or in the Script guide. Until then, the Start buttons should show the protocol's name in a confirm ("Start 'table' (5 steps, up to 50 pN, 10 turns)?"). |
| 2 | **Run page**, step 3 "Calibrate the picked beads...": the two save dialogs | The owner listed "choose where to save" as one step. Here the .cal dialog comes before the scan and the **run-file dialog comes after it** (`_track_from_cal`), so the user must wait at the screen for a minute of scanning to answer a second dialog; a Cancel there leaves "calibrated, not tracking" and sends them to Beads -> Select checked beads. | Ask once, before the scan: one dialog for the data folder, with the names derived (cal001 and tra001 next to it, shown in the dialog), then scan -> track without a stop. Keep "Change..." for the rare other name. |
| 3 | **Calibrate**: "Write .cal to" (`cal_out`, seeded from `QSettings("KimLab", "MT Tracker").value("data_dir")`) | The test suite goes through the Run page's step 3 (`_flow_calibrate`), which **writes the data folder into the user's real QSettings**. On the screenshot the box reads `...\pytest-559\test_run_page_calibrates_then_0\cal001`; on the rig PC, where the tests run too, the owner's save dialog would open in a pytest temp folder, or the box would name a folder that no longer exists. | Tests must not touch the user's settings (`QSettings.setDefaultFormat` to a temp ini in `tests/test_gui.py`, or a `settings` argument to `MainWindow`). The box should fall back to the run folder when the remembered folder is gone. |
| 4 | **Top bar**: "Stop acquisition" next to "Record", "STOP" and "Acknowledge" | Three stops in one row: "Stop acquisition" (camera), "Stop" (Experiment: the protocol) and "STOP" (emergency). The red button is right of "Record", where a hand going for Record lands on it. "Acknowledge" is **always visible**, even with no emergency stop engaged, so the user asks "what are these" (owner 2026-11-05). | Move STOP to the far right with a gap, label it "EMERGENCY STOP", give it a keyboard shortcut (the mock-up's banner shows what it did); show "Acknowledge" only inside the red banner while the stop is engaged (the mock-up has that banner; the build has only a status-bar line). |

### Moderate

| # | Panel, widget | Finding | Change |
|---|---|---|---|
| 5 | **Run page**, step 1 "Start acquisition (top bar) and watch the JAI image" | The first step's button is **not on the page**; the sentence points at the top bar. Every other step has its button beside it. | Put a "1. Start the camera" button on the page (the same handler as the top bar's) that turns into "camera running, 90 Hz" when it is. |
| 6 | **Run page**, buttons "3. Calibrate the picked beads..." and "Reset calibration" | The primary action and the **destructive** one (drops the beads, closes the run file) sit side by side, same size, same style. "Reset" also reads like "reset the calibration values". | Make step 3 the one bold / default button of the page; move "Reset calibration" under step 4 as "Start over (drop the beads, pick again)" with a confirm while a run file is open. |
| 7 | **Run page**, step 4 "Record on / off" | The button has **no state**: the state is on the top bar's "Record" / "* Recording" far away, and in the status line. The run file's name is in the sentence, not the recording state. | A checkable button on the page mirroring the top bar ("Recording into tra001.h5" when on), or drop the page button and let the step 4 sentence show the state. |
| 8 | **Step bar** 1-7 | The numbers promise an order (Setup -> Run -> Explore -> Beads -> Calibrate -> Experiment -> Save), but the order is Run alone; Beads, Calibrate and Save are **sub-steps of Run** shown as peers, and Experiment (the protocol) is not reached from Run at all. The Run page's title says "camera -> beads -> calibrate -> track -> save" while the bar says 4, 5, 7 for the same things. | Two groups in the bar: "Setup | Run | Experiment" numbered, and "Explore, Beads, Calibrate, Save" unnumbered under a "Settings and details" heading (or as tabs inside Run). Add a step 6 "Run a protocol (Experiment)" line to the Run page. |
| 9 | **Setup**: "Safety profile" label (`_profile_label`) | The first thing on the first page is a three-line **temporary path** and a shell command ("change: python tools/rig_set_limit.py <quantity> --max ... --reason "...", then restart"). The owner asked to see where things are set; this is the developer's answer. | Show "Rig safety profile v10 (verified)" and the limits as a small table; the file path and the command go into a tooltip or a "Details..." panel. |
| 10 | **Setup**: group titles "Camera preset (U15)", "Analysis (decision 0024)", "Force equation (decision 0018)"; the Mode combo "(phase 10a)" | **Decision and requirement numbers in the user's labels.** They mean nothing at the rig. | Plain titles: "Camera preset", "Tracking", "Force from magnet position"; the numbers stay in the code comments. |
| 11 | **Setup**: Mode default "MT-TIRF: tracking + EMCCD, Arduino sync, lasers, light gating" | The default mode opens the EMCCD and promises lasers and light gating that phase 10a has not built; the EMCCD screen takes half the camera area ("EMCCD: no frame") during an MT experiment. | Default MT until 10a lands; the MT-TIRF entry says only what it does today ("tracking + EMCCD"). |
| 12 | **Event list** (bottom) | Lines are **Python dicts**: `device {'extra': {'device': 'emccd', 'action': 'open', 'origin': None}}`. The one list the user watches for "what just happened" needs decoding. | One sentence per event from the event's fields ("21:21:59 emccd opened", "21:22:02 acquisition started, 90 Hz, no beads"); the dict behind a double-click or in `gui_events.log` only. |
| 13 | **Status bar** as the only place for refusals (`_fail`: 15 s) | A refused action ("calibrate: start acquisition and left click the beads first", "run protocol: ...") shows for 15 s at the bottom-left, far from the button pressed; the second-Start symptom of 2026-11-04 came from this. | Show the refusal next to the control: the step's label on the Run page turns red with the text; the Experiment page already has `prot_status` - use the same pattern for every page. |
| 14 | **Calibrate**: the viewer (`CalView`, min height 560 px) | Before any .cal is loaded the three plots show **empty axes from -0.4 to 0.4** and push the page into a scroll; "no .cal loaded" is a one-line label above them. | Hide the plots (or show one "no calibration yet" placeholder) until `load()`; or put the viewer in its own panel like the camera settings. |
| 15 | **Calibrate**: "Save to .cal (then select the beads again to track with them)" | Saving new band-pass values **does not apply them**; the user must go to Beads -> Select checked beads. The camera no longer stops, so the program can do it. | Save applies via `api.beads.select` / `api.acq.retarget` when those beads are the ones tracked; the button reads "Save and use". |
| 16 | **Beads**: ".cal file" box, "Load list", "Select checked beads", "Reference bead ids (comma)" | The page is the manual version of Run's step 3 with an empty list filling the page; the reference bead is typed as ids in a text box while bead 1 is the reference in the usual flow. | Keep as the details page, but say so in its title ("Beads: the list behind Run"); a "reference" check box per bead row instead of the id text box. |
| 17 | **Save**: "Run name (next acquisition)" + the six-line paragraph | The paragraph explains naming that the Run page already does; the name box is edited by hand though the Run page sets it. Two sources of truth for tra00N. | Show the names as read-only facts ("next run file: tra003.h5 in D:\data\...") with one "Change..." button; the paragraph becomes a tooltip. |
| 18 | **Explore**: "Exposure (immediate)" / "Gain (immediate)" vs Setup's "Camera preset" | Exposure is set in two places with different wording ("immediate" against "Apply preset and read back"); a change during tracking makes the LUT wrong (queued item 2026-10-30). | One place (Setup's camera settings); Explore shows the value and a "Change..." that warns while beads are tracked. |

### Minor

| # | Panel, widget | Finding | Change |
|---|---|---|---|
| 19 | **Run page** step texts | Mixed grammar: step 3's text starts lowercase mid-sentence ("3. asks where to write..."), step 5 is a statement, steps 1-2 are imperatives; the "Script guide" button sits in the Save row where it has nothing to do with saving. | Imperatives throughout ("3. Calibrate...", "5. Save the traces..."); move "Script guide" to the Experiment page and the top-bar Help. |
| 20 | **Camera view** label "JAI frame 396 seg 1 t 4.400 s 90.0 Hz" | "seg 1" is the pipeline's segment counter. | "JAI 90.0 Hz, frame 396, 4.4 s"; the segment in the status bar. |
| 21 | **Graph** empty state | Axes 0..1 with grid and no curve while nothing is tracked. | A centred "no beads tracked" text until the first point. |
| 22 | **Explore** magnet slider | A bare slider under the position box with no ticks or end labels (0 and 40.9 mm). | Tick labels at the ends, or drop the slider (the box and "move by" cover it). |
| 23 | **Explore** "Move" x 5, "Set" x 2 | The same word on five rows; the eye cannot tell them apart. | "Move magnet", "Move focus", "Set exposure" - or one "Go" per row with the row label bold. |
| 24 | **Beads** ".cal file" box | Shows the tail of a long path ("2 Ramp_Newbatch\test\cal002"). | Elide in the middle (`Qt.ElideMiddle`), full path in the tooltip. |
| 25 | **Top bar** "Pause display" | The first button of the bar is the least used; "Devices: 8 / 8 connected" is the only device state. | Order: devices, acquisition, Record, then Pause display; the protocol badge coloured when running. |

## Visual hierarchy

- **What draws the eye first:** the red STOP (correct for an emergency control) and, on Setup, the temporary path
  of the safety profile (wrong: the user should see Connect first). On Run, nothing is emphasised: the page is
  grey buttons and grey text.
- **Reading flow:** top bar -> step bar -> the right panel; the camera and graph on the left are the content
  but sit under the bar's right-aligned buttons, so the eye zig-zags. The event list at the bottom reads last and
  carries the most text.
- **Emphasis:** no button on any page is the default / primary; on Run, "3. Calibrate..." should be.

## Consistency

| Element | Issue | Recommendation |
|---|---|---|
| Button wording | "Start acquisition" (top bar) vs "Start" (protocol) vs "Start from table"; "Stop acquisition" / "Stop" / "STOP"; "Record" / "Record on / off" | Name the object every time: "Start camera", "Start protocol", "Stop protocol", "EMERGENCY STOP". |
| Trailing "..." | "Calibrate the picked beads..." opens a dialog (right); "Change..." (right); "Browse..." (right); "Script guide" opens a file (no dots); "Camera settings..." opens a panel | Dots only when a dialog follows; the panel buttons without. |
| Numbers in labels | Run page numbers its sentences 1-5; the step bar numbers pages 1-7; the Experiment table numbers columns 1-5 | Numbers only where they are an order the user follows (the Run page). |
| Internal references | "(U15)", "(decision 0024)", "(decision 0018)", "(phase 10a)", "SPD", "seg 1", "bead_i32" (calview docstring, not shown) | Out of the user's labels. |
| Theme | White Qt panels around black pyqtgraph views; the mock-up is a dark window | Either theme is fine for the lab; pick one so the black views do not look like holes. The mock-up's dark header is closer to LabVIEW's. |
| The mock-up vs the build | Mock-up: vertical step list left, e-stop banner, Library; build: horizontal bar, no banner | The banner is the one piece to carry over (finding 4). |

## Accessibility

- **Colour contrast:** STOP white on #B91C1C 6.9:1 (passes); SIM-DEV amber #B45309 on white 4.6:1 (passes AA
  for bold); pick boxes #FBBF24 on the grey image fine; the graph's white text on black fine. The protocol badge
  "no protocol" is plain black text - no colour for "running".
- **Targets:** mouse only, Qt defaults (about 24 px high buttons) - adequate at the rig's desk; the table cells
  (70 px wide) are small for typing -3600 but fine.
- **Keyboard:** no shortcut for the emergency stop; no default button on any page (Enter does nothing). Give
  STOP a shortcut and the Run page a default button.
- **Text:** 9-pt Qt default throughout; the Run page sentences wrap to four lines at 440 px - readable but dense;
  the event list's dict lines are the only unreadable text.

## What works well

- The Run page exists and its order is the owner's order; the remembered data folder and the LabVIEW names
  (cal001, tra001, tra001-000) are right; "Reset calibration" and the pick count on the page save trips to Beads.
- The camera never stops through watch -> calibrate -> track -> reset; the user does not see a restart.
- Explore's "Now" block (every motor and the force, monospace) and the Cal+ / Cal- presets are exactly what the
  owner asked for on 2026-11-04.
- The calibration viewer shows the three things that were invisible before (PSF stack, band-passed LUT, self-fit
  residual in nm) with live re-processing.
- The safety profile and every limit are visible (owner: "the user must know"), even if the form needs work (#9).
- STOP's and Acknowledge's tooltips say what they do, in the owner's words.

## Priority recommendations

1. **Open the Experiment page empty (#1)** - the pre-filled table and script are the one thing on the window that
   can move the rig by surprise. Load example on request.
2. **One save dialog before the scan (#2) and a Start-the-camera button on the page (#5)** - then the Run page is
   complete: five buttons, top to bottom, nothing in the top bar, nothing after the scan.
3. **Keep the tests out of the user's QSettings (#3)** - before the next rig run, or the first save dialog opens
   in a pytest folder.
4. **Emergency stop as in the mock-up (#4)** - the red banner with Acknowledge inside it, a shortcut, STOP apart
   from the other stops.
5. **Speak the user's language (#9, #10, #12)** - the safety profile as a table, no decision numbers in labels,
   event lines as sentences.

## Not checked

The rig backend (never pressed Connect on the rig), the window at 1920 x 1080 and at the rig's own screen
size, the Camera settings and Device panels (`gui/attrs.py`, `_Panel`), the shutdown dialog, dark-theme
rendering, and any behaviour that needs real beads (the calibration viewer with a real .cal was shown only with
the fixture's cal file in the tests).
