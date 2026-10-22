# UI requirements from the owner (2026-10-22)

Input for plan phase 8 (GUI). Owner's answers 2026-10-22, quoted, then the requirement that follows. The design
sketch discussed in chat is at the end; it is a proposal, not yet agreed in detail.

## What was wrong with the LabVIEW panel
Owner: "모든 항목이 다 스크린에 있어서 가독성이 떨어졌던 점. 화면에 딱 맞게 있지 않아서 화면 스크린을 드래그해서 움직여야
했던 점. 경우에 따라 보고싶은 그래프가 다른데 2개밖에 없어서 (예를 들면, rotation vs extension을 보고 싶은데 불가능) 나중에
분석 화면에서나 볼 수 있던 점. 그래프 스케일이 고정되어 있어서 실험중에는 바꿀 수 없다는 점."
(The LabVIEW front panel holds about 106 controls and 96 indicators; V6 `docs/main-vi-panel-map.md`.)

| # | Requirement |
|---|---|
| U1 | **Readable:** each experiment step shows only its own controls; rarely used settings sit in a collapsed "advanced" section. |
| U2 | **Fits one screen:** the window lays itself out to the screen size; no scrolling or dragging of the panel is ever needed. Image and graphs can be maximised with one action. |
| U3 | **Any graph during the run:** each graph slot takes any variable on either axis (time, magnet position, force, rotation, extension, per-bead x / y / z, fluorescence intensity, ...), e.g. rotation vs extension live. Slots can be added (1, 2, 4, tabs) and the beads shown are selectable. Graph sets are saved as view presets. |
| U4 | **Scales change during the run:** auto / manual scale switch, mouse zoom and pan, double-click to reset, "follow the last N seconds". Display only; acquisition and saving are unaffected. |

## Setting
| # | Fact | Requirement |
|---|---|---|
| U5 | One monitor (owner: "모니터는 한 대") | Layout designed for one screen first (U2); no layout that needs a second monitor. |
| U6 | The whole lab will share it (owner: "연구실 전부 공유할 예정") | Per-user profiles (layout, view presets, recent settings; the user's name is written into the data file); lab-wide shared protocols and rig presets (objective / pixel size); guidance for new users (step order, a reason shown for every disabled button, confirmation for risky actions); the same safety limits for everyone. |

## Pain points in the experiment itself (owner, 2026-10-22)

**U7 - numbers before picking, and bead screening by protocol.** Owner: "모든 데이터는 bead 골라서 코드 실행을 해야지만
숫자를 알 수 있음. 그래서 긴가민가 싶으면 비드 고른 다음 숫자 확인해보고 일일히 숫자 넣어 움직이면서 변화를 봐야함. 프로토콜을
미리 셋팅해서 bead selection 기준을 잡은 다음 실험해보기 전에 골라낼 수 있으면 훨씬 좋겠음. 그게 되면 자동화 선택도 될 것
같고, 자동 실험도 될 것 같은데"
- Detect all candidate beads in the field automatically; one z scan calibrates all of them at once.
- Show live x / y / z for every candidate right after calibration, before any picking.
- A **screening protocol** (saved, shared, editable) runs short magnet / rotation steps and scores each bead against
  criteria, e.g.: follows the magnet (tethered) or not (reference candidate); extension at a set force inside the
  expected contour-length window (rejects multiple or short tethers); rotation response (hat curve = coilable, none =
  nicked); x / y fluctuation symmetry (off-centre attachment); distance to neighbours; ring quality.
- Output: a pass / fail table with the **reason** for each bead; the user confirms or overrides, then the experiment
  runs on the accepted beads.
- This is the basis for automatic selection and automatic experiments (later, possibly over several fields); per
  decision 0001 automation sits on the normal interfaces, passes the same safety layer, and the user can stop it.
- **Open:** the owner's actual criteria and thresholds (what numbers are checked today, and the accept ranges).

**U8 - device connection status.** Owner: "기계 연결상태를 각자 표시하지 않아서 블락 다이어그램 직접 들어간 후에 일일히 에러
체크 해줘야함. 가끔 기계 연결 문제가 있던데, 이럴 때 곤란함"
- A device panel: one row per device (JAI, iXon, PI magnet, ASI, rotor, Arduino, laser) with a state light
  (connected / disconnected / error / slow), the last response time and the last error in plain words with a hint
  (e.g. "PI magnet: no reply for 3 s on COM3 - check controller power and cable"); a summary icon in the status bar.
- A reconnect button per device, without restarting the program.
- A start-up self-check (open, reply, read position for each device) listed with results; a failure stops at that
  step with its reason.
- Device errors are logged with time stamps and saved with the data.
- Status checks run in each device's own thread, never on the frame acquisition path (rule: no serial / VISA call on
  the frame path).

## Also to be supported (owner, earlier in the same chat)
- The Andor iXon EMCCD added later (decision 0005: the JAI is the master clock, the Arduino divides frames).
- Real-time fluorescence traces.
- Frame-ratio setting between the JAI and the EMCCD.

## Design sketch (proposal discussed 2026-10-22)
- A step bar on the left (setup → bead picking → calibration → experiment → save, plus a review mode for saved data);
  the main image in the centre (JAI bright field, the iXon image beside it once present); the current step's controls
  on the right; live graphs on a common time axis at the bottom.
- An always-visible status bar: rig state, real fps and lost frames, magnet / rotor / focus position, recording
  indicator, and the emergency stop (also a keyboard shortcut).
- Dockable panels whose arrangement is saved per user.
- Device settings panels generated from each device's settings description, so a new camera needs a device module,
  not a new screen; settings are saved with the data.
- A frame-ratio panel that shows which JAI frames pair with each EMCCD frame and warns before start when exposure or
  rate limits are exceeded.
- Fluorescence ROIs picked on the iXon image or mapped from bead positions; intensities plotted with z and force on
  one time axis.
- A protocol editor (list of steps: magnet position or force, hold time, rotation, repeats) with a force-vs-time
  preview, saved as a file, replacing the `CycleSchedule` table.
- Bead picking by click as now, plus suggested beads from automatic detection; the reference bead in its own colour;
  a bead table with status and small traces.
- GUI in its own process (PySide6 + pyqtgraph, plan phase 8); the display refreshes at about 30 Hz while acquisition
  runs at 150 Hz, so moving windows loses no frames.

## Next
A clickable mock-up with fake data, for the owner and lab members to try before any GUI code is written.
