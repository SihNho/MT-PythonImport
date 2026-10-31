# GUI (plan phase 8) - first build on the simulators, 2026-10-29

Owner 2026-10-29: build the program first and fix design, protocol and detail by running it
("디자인 부분이나 아니면 프로토콜, 디테일한 부분 등은 실행해보면서 수정하는게 빠를 것 같음"); phases 6 and 7 (real devices) follow.

## Run
Double-click `MT Tracker (simulators).cmd` (TEST-ONLY limits), `MT Tracker.cmd` (shipped profile) or
`MT Tracker (rig).cmd` (JAI + iXon + motors; the program takes the rig lock itself, decision 0026) in the repository
root; the owner never types scripts into a terminal (2026-10-30). The same from a terminal:
```
.venv\Scripts\python.exe -m mtpy.gui --sim-dev          # simulators; TEST-ONLY focus / rotor limits on a config copy
.venv\Scripts\python.exe -m mtpy.gui                    # simulators on the shipped safety profile (focus moves refused)
```
`--fixture DIR` (recorded frames + a `cal*` file for the simulated camera; default `$MTPY_DATA/test`), `--out DIR`
(run files), `--screenshot PNG` (smoke test). `pip install -e .[gui]` adds PySide6 and pyqtgraph.

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
| Calibrate | z scan of the selected beads from the display frames -> `.cal` (`gui/zscan.py`) | `focus`, `acq.display`, `lvfiles.write_cal` |
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
