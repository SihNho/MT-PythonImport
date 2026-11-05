# GUI (plan phase 8) - first build on the simulators, 2026-10-29

Owner 2026-10-29: build the program first and fix design, protocol and detail by running it
("디자인 부분이나 아니면 프로토콜, 디테일한 부분 등은 실행해보면서 수정하는게 빠를 것 같음"); phases 6 and 7 (real devices) follow.

## Run
Double-click `MT Tracker.cmd` (the rig: JAI + iXon + motors; the program takes the rig lock itself, decision 0026)
in the repository folder. `MT Tracker (simulators).cmd` is the developer's: every device simulated with TEST-ONLY
limits, and the Setup panel then shows the backend and the fixture (owner 2026-11-05: the user sees the rig only)
root; the owner never types scripts into a terminal (2026-10-30). The same from a terminal:
```
.venv\Scripts\python.exe -m mtpy.gui --sim-dev          # simulators; TEST-ONLY focus / rotor limits on a config copy
.venv\Scripts\python.exe -m mtpy.gui                    # simulators on the shipped safety profile (focus moves refused)
```
`--fixture DIR` (recorded frames + a `cal*` file for the simulated camera; default `$MTPY_DATA/test`), `--out DIR`
(run files), `--screenshot PNG` (smoke test). `pip install -e .[gui]` adds PySide6 and pyqtgraph.

## The Run page (owner 2026-11-05)
Owner: "the usual experiment is: watch the camera, pick beads, bead calibration, choose where to save, tracking,
save - here everything is scattered". Step 2 **Run** is that order on one page: (1) Start acquisition and watch
(no file is written while no beads are selected); (2) left click the beads; (3) **Calibrate the picked beads...**
asks for the data folder once (remembered; the names are LabVIEW's next free `cal001` and `tra001.h5` in it:
design critique 2026-11-05 #2), scans, then tracks every bead of the .cal from the next frame on with
bead 1 the reference - the user never stops the camera by hand; **Reset calibration** drops the beads and the
image takes picks again; (4) Record on / off writes into the run file; (5) **Save the traces** writes the LabVIEW
`tra001-000` next to it. **Script guide** opens [guide/protocol-scripts.ko.md](../guide/protocol-scripts.ko.md).
The other pages keep the settings (Calibrate: slices, step, band-pass viewer; Beads: the list and the roles).

Owner 2026-11-05, same evening: the JAI has no shutter, so stopping its acquisition protects nothing; the restart
at bead selection is the program's (the tracker is built at acquisition start) and now happens inside step 3.
Done the same night: `api.acq.retarget` swaps the tracker and the run file between two frames, so Select beads,
the Run page's step 3 and Reset calibration never stop the camera (one segment through the whole flow). The
EMCCD is the camera whose acquisition and shutter the user controls.

## Design critique 2026-11-05 - what was applied the same night
[design-critique-2026-11-05.md](design-critique-2026-11-05.md) (the owner: "design lint"); applied: #1 the
Experiment table and script open empty, "Load example" fills them; #2 one data-folder dialog before the scan;
#3 the tests point QSettings at a temp ini, a remembered folder that is gone falls back to the run folder; #4
"EMERGENCY STOP (Shift+Esc)" apart at the far right, Acknowledge only inside the red banner while the stop is
engaged; #5 "1. Start the camera" on the Run page; #9 the safety profile as a table (path and command in the
tooltip); #10 plain group titles; #12 event lines as sentences (the fields only in `gui_events.log`). Open: the
rest (#6-#8, #11, #13-#18 and the minor ones).

## Owner's list after the first full run on the rig (2026-11-05 evening, applied the same night)
The owner ran watch -> picks -> calibrate -> track -> protocol -> Save the traces on the rig
(`G:\Data\Sihyeong-Developing61105 Test`: cal001, tra001.h5, tra001-000) and asked for:
- **Duplicates hidden** ("the Run page is really good; hide the duplicated panels as sub-panels, shown only when
  looked for"): the step bar is `1. Setup | 2. Run | 3. Experiment | More...`; Explore, Beads, Calibrate and
  Save appear only after More (`DETAILS`). The top bar keeps Pause display and EMERGENCY STOP only: the one camera
  button ("1. Start the camera" / "Stop the camera") and the one Record button ("4. Record on" / "* Recording")
  are on the Run page. Beads lost its second Clear picks and New calibration (Run's Reset calibration is the one).
- **Right click** removes a pick without pyqtgraph's View / Export menu (`enableMenu=False`).
- **Data folder** `G:\Data` is where every data dialog starts (`DATA_ROOT`; the last chosen folder when it still
  exists); the owner's protocols live in `G:\Data\protocols` (`*.mtprot`) and the Experiment page lists them in a
  combo (one click loads; Save as... puts a new one there) - "a protocol used again and again is tedious to type".
- **Explore** magnet speed starts at the profile limit (15 mm/s).
- **Calibration viewer**: z found (um) and the residual (nm) were on one axis and both unreadable; the residual
  has its own plot now (x linked).
- **Experiment**: a `repeat N x` spin on the table (cycle repeat -> `loop n=N`); "estimated M min S s" after
  Table -> script, Check and a protocol pick (the t= times with loops expanded plus each `speed=` ramp's magnet
  travel at its speed); the **Script guide** opens inside the program (a panel rendering the Markdown; the .md
  had opened in whatever application owns the extension).
- **The protocol stopped at 50 pN** (troubleshooting #28): the ramp 1 -> 50 pN at 0.1 mm/s is ~30 mm = 300 s and
  the arrival wait was the device's 60 s; a move now carries its own duration (`Motion.expected_s`, distance /
  speed read before the move) and both the device wait and the engine's timeout stretch by 1.5 x it.
- **1-2 s between steps with no wait**: measured in the log, step 1 (rotate t=10) took 14 s, step 2 took 11 s.
  Each column first sets the force (a magnet move with a VEL? read, an ONT? poll and a read-back) and a rotation
  pre-reads the rotor position; those device round trips are the overhead. Not changed yet: to measure per call
  on the rig before cutting (candidates: skip `set_force` when the magnet is already there within tolerance).
- **The trace plot drew a ramp as stairs**: the window took the magnet position from its 2 Hz read-back; it now
  takes every `motor_reading` event (the poller's 10 Hz, the same values the run file holds: a change every 9
  frames at 90 Hz in tra001.h5). The Y label said Force while the legend still said Magnet: the curves are
  rebuilt when the axis changes.
- **tra001-000 format**: header (weekday, date, the three lines, the .cal path, "file 0 of a series", points /
  nominal) and columns (frame, magnet mm, rotor deg, x y z per bead: 3 + 3 x 4 = 15) as the LabVIEW file. One
  difference to decide with the owner: the rotor column holds the controller's absolute count (72000 deg here)
  where the LabVIEW file holds the position told relative to its origin (0 at the start).
- **Autofocus - not built** (owner: "I do not know whether auto-focusing is on"). Two functions the LabVIEW
  program has and this one does not yet: (1) a bead reported bad returns to its calibration position and tracking
  is retried (spec F4.05 lost-bead reseed); (2) the piezo keeps a chosen coverslip position (spec F4.06, the
  +-0.2 clamp rule) - the owner must be able to choose which position to hold. Queued for the hardware phase
  (STATUS Next); until then the focus stays where the z scan or Explore left it.

## What the first build has (src/mtpy/gui)
One window after the mock-up ([mockups/2026-10-23-main-window](../mockups/2026-10-23-main-window/README.md)):
top bar (device summary, display pause, acquisition start / stop, Record, STOP, Acknowledge), six steps, two camera
screens side by side (owner 2026-10-30: the JAI with the bead boxes, the EMCCD with its snap or Live frames), any-axis live graphs (x / y / z per bead, magnet, force against time, magnet or force; follow
30 s; bead chips), the event list (without the 20 Hz motor readings) and the status line (frames, fps, recording,
magnet position and live force, protocol state, e-stop).

**Camera SDK** (owner 2026-11-01, decision 0028): a box in Setup, IMAQdx (default; NI's driver, shared with LabVIEW) or eBUS (Pleora's driver); it must match the USB3 Vision driver the camera is bound to.

**Modes** (owner 2026-10-30: "MT, MT-TIRF 모드 구분이 필요함"): a Mode box in Setup. **MT** = tracking alone: the JAI and
the motors are opened, the EMCCD screen and group are hidden. **MT-TIRF** = everything (phase 10a: the iXon, the
Arduino sync box - "Arduino는 mt-tirf 용도" - later the lasers and light gating). The mode goes into the connect preset (`api.devices.MODES`), the
connect event, the window title and every run file (`/metadata/run/mode`); changing it while connected applies at
the next Connect. Default MT-TIRF (today's behaviour).

| Step | Does | API |
|---|---|---|
| Setup | connect / disconnect the rig, self-check, device table (a click on a row opens that device's panel: identity, read-back, limits and the profile window as rows, and what the device can be told as numeric fields with Move / Set - owner 2026-10-31: a control panel, not a raw dump; the EMCCD row opens the camera-settings panel), "Camera settings..." opens the JAI preset and the EMCCD parameters in their own panel (owner 2026-10-31: not crammed into the step column), Z method and executor (0024), touch position for the force equation (0018: starts at 40.94 mm = the magnet's travel end, locked, Change... / Set only, kept in `config/touch_position.json` across restarts, applied at every Connect) | `devices`, `camera`, `magnet.set_touch_position` |
| Explore | magnet position and force, rotor, focus, exposure and gain, read-backs | `magnet`, `rotor`, `focus`, `camera` |
| Beads | list the beads of a `.cal`, check, reference ids, select | `beads.select` |
| Calibrate | z scan of the selected beads from the display frames -> `.cal` (`api.zscan`, run in the engine since 0029); "Settle after each move" 0.2 s default (owner 2026-11-01: the 10-31 scan without it gave LUT slopes 1.04-1.06) | `focus`, `acq.display`, `lvfiles.write_cal` |
| Experiment | protocol text editor, Load / Save, Check, Start / Pause / Resume / Stop, Apply edits, Mark | `protocol`, `acq.mark` |
| Save | run folder and name (acquisition writes `<folder>/<name>.h5`; Record toggles recording inside it), export `.tra` / `.cal`, open a run | `acq`, `data` |

Every API call is made as caller "gui" on a worker thread; the window reads the display tap at 30 Hz and the motors
at 2 Hz, so it cannot slow acquisition. A `magnet_stall` event opens a modal error (decision 0019 contract).
Smoke test: `tests/test_gui.py` (offscreen Qt, the fixture frames; connect -> beads -> acquisition -> protocol ->
stop).

## Not in the first build (phase 8 list)
Candidate finder and screening (U7, U10, U23), presets library (U13), on-site analysis (eWLC, Allan; 0011, U12),
zero / bridge / exclude (U12, U14), troubleshooting guide (U9), MT-TIRF mode (10a), block-style protocol editor
(text only), review of a finished run beyond the summary.

## Shortcuts recorded in the code
- The GUI shares the API's process (the plan says its own process); it moves out only if phase 6 shows the camera
  thread losing frames while the window is dragged.
- The simulated camera does not change with focus: a z scan on the simulator writes a flat LUT (flow only).
- `--sim-dev` is for the simulators alone: it never touches the shipped config and is removed with the window.
- Plot bar: "Plot refresh" (1-30 Hz, default 10) paces the live plot's redraw only; the history keeps every displayed
  frame (owner 2026-11-01, after the GUI isolation measurement showed the plot as the GUI's largest cost per tick).

## UX backlog from the owner (2026-11-04, "do not change now, just noting")
1. **Camera controls are a fraction of the camera** - done 2026-11-04 night: `api.camera.catalogue()` /
   `get_attribute` / `set_attribute` (the JAI's 156 driver-listed attributes in 10 categories, read from IMAQdx at
   connect; the simulator a slice of them), `api.emccd.catalogue()` from its settings, and the generic panel
   `gui/attrs.py` (category tree, search, beginner / expert / guru level, favourites per device in
   `config/camera_favourites.json` / `emccd_favourites.json`, a control per type, every write read back) inside
   Setup -> Camera settings. Guards: reset / stored defaults / factory / a pixel format other than Mono8 are refused
   by the device; ImageFormatControl, AcquisitionControl, TransportLayerControl, UserSetControl and DeviceControl
   writes pause the acquisition and need the panel's confirm checkbox while recording; each write is a `setting`
   event in the run file. The driver's catalogue: [manuals/camera-jai-attributes.md](../manuals/camera-jai-attributes.md).
   Original note: the panel had exposure, frame rate, gain; the JAI exposes 193
   features in 12 categories (ROI, binning, pixel format, trigger source / activation / overlap, exposure mode incl.
   trigger-width, 8 digital I/O lines with TTL / LVDS / opto formats and line sources, two pulse generators, ALC,
   LUT / gamma, user sets, multi-ROI and sequence modes): [manuals/camera-jai-features.md](../manuals/camera-jai-features.md).
   1-1. One page cannot hold them: a **settings panel** is needed - a category tree (NI MAX's categories and
   visibility levels, search), each feature rendered from the device's own catalogue (type, range, enum values, read-
   only), a **favourites / per-experiment preset** layer on top (the few the experiment changes), and the same
   guard model as today (needs-a-pause settings, confirm while recording, settings stored with the recording).
   1-2. **The EMCCD (iXon) is the same case**: today's keys (frame transfer, shutter, exposure, rate, EM gain mode /
   gain, temperature, cooler, HS / VS speed, output amplifier, read / acquisition / trigger mode) are a subset of the
   SDK; the panel must be driven by a device-reported catalogue, not hand-written rows, so both cameras (and a later
   one) get the same panel.
2. **Bead picking**: left click adds, right click removes the nearest pick - but right click also opens pyqtgraph's
   context menu (view options). Candidates: left click toggles (click a pick to remove it); right click keeps the
   menu and gains "remove pick", "set as reference", "details"; double click or hover for the detail window; the
   Delete key removes the last / highlighted pick. Decide with the owner at the UI/UX session.
3. **.cal / .tra export status**: `.cal` is written by the z scan (`lvfiles.write_cal`, byte-identical round trip on
   the owner's files, `tests/test_lvfiles.py`); `.tra` is exported from the run file (`api.data.export(kind="tra")`,
   GUI "Export .tra"; byte-identical round trip and the frame column from the first recorded frame,
   `tests/test_data.py`). Not yet checked: a `.tra` / `.cal` from this program opened in the owner's LabVIEW /
   MATLAB analysis end to end on a real recording (the owner's acceptance).
4. **Explore panel (owner 2026-11-04, from the experiment)** - done 2026-11-04 evening (commit below): show, live and continuously refreshed, every motor's
   position (stage x / y, focus z, magnet mm, rotor deg) and the force (pN) from the magnet position; add the motor
   speed to the magnet / stage move controls (it is missing); **two PI presets** (the owner keeps "Cal+" and "Cal-"
   positions as two buttons with stored values, editable); after a relative "move by" the entry returns to 0 so the
   next move is typed fresh.
5. **Calibrate panel**: the bandpass and forget-radius values are not visible, nor the PSF and the result.
   **Done 2026-11-05** (`gui/calview.py`): below the scan settings the viewer shows, per bead of the .cal, the raw
   stack as an image (the PSF through focus), the band-passed stack after the forget radius (what z is matched
   against) and the self-fit (every slice's own profile through the z method against the LUT: z found against z
   scanned, the residual in nm); LOW / HIGH / forget spins re-process live and "Save to .cal" writes them into the
   file's bead_i32 (then select the beads again). Open: the owner's words "delta r vs delta z" may mean another
   LabVIEW picture than the self-fit - to confirm with the owner.
6. **Experiment panel**: (a) the owner pressed Start, it ran once, and the next Start did nothing visible. In the
   simulator the API runs protocols one after another (`tests/test_protocol.py`), so the cause is on the GUI path
   (the Start handler only resumes when the state is "paused"; a refusal from `api.protocol.run`, such as a check
   error against the rig's present state, shows only as a 15-s status-bar line "run protocol: ...") - to reproduce
   with the owner: read that line, or the `refused` event in the log, on the second Start - since 2026-11-04 evening
   the log pane is also written to `gui_events.log` in the run folder, so the line survives the window. (b) The text script is
   not intuitive for the owner: wanted a **table editor**, rows = parameters, columns = iterations, e.g.

   | | 1 | 2 | 3 | 4 | 5 |
   |---|---|---|---|---|---|
   | Force (pN) | 1 | 1 | 1 | 50 | 1 |
   | Wait (s) | 0 | 0 | 0 | 0 | 0 |
   | Motor (mm/s) | 0.1 | 0.1 | 0.1 | 0.03 | 0.1 |
   | Rotor (degree) | -3600 | 3600 | 0 | 0 | 0 |
   | Rotor speed (pulse) | 50 | 50 | 0 | 0 | 0 |

   The table compiles to the existing protocol script (one step per column: hold / ramp at the force with the motor
   speed, rotate by the degrees at the pulse speed, wait), so the engine, the check and the recording stay as they
   are; the text view remains for the rest. **Done 2026-11-05** (`gui/exptable.py`; `ramp` gained `speed=` mm/s as
   the alternative to `t=`; the rotor speed column is the Autonics SPD value, SPD x 10 / 500 turns/s as the driver
   assumes). The example above compiles to:

       grammar 0.1
       protocol "table"
       # column 1
       rotate from=0 to=-10 f=1 t=10
       # column 2
       rotate from=-10 to=0 f=1 t=10
       # column 3: nothing to do
       # column 4
       ramp from=1 to=50 speed=0.03
       # column 5
       ramp from=50 to=1 speed=0.1
       end protocol
