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
- **Device details on double-click / "Open"** (owner 2026-10-22: "장비 정보들도 더블클릭 혹은 열기 등으로 보면 확인
  가능하도록 하면 좋겠음"): identity (model, serial number, firmware, port, driver / SDK version); current state
  (position and settings, connected since, last reply); safety limits (controller limits, allowed motion range);
  calibration in use (date, table version); recent errors and reconnects; links to the device manual
  (`docs/manuals/`) and to related troubleshooting cases (U9). **Read-only**: changes go through the settings screen
  with confirmation. The same information is written into each data file at the start of a run (as with U13 presets).

**U9 - built-in troubleshooting guide.** Owner 2026-10-22, from a discussion with Ecem: "트러블슈팅 가이드를 프로그램에
내장해두면 큰 도움이 될 것같음. 1) 실험 테스트를 해보고 가능한 트러블 및 트러블 슈팅 옵션들 제공 2) 이전의 경험들을 제공하며
그 당시의 트러블 정체, 그리고 트러블 슈팅 방법 알려줌"
- **Diagnostic tests:** the user picks a symptom (beads lost often, z too noisy, frames dropped, beads do not follow
  the magnet, a device does not reply, ...); the program measures the related quantities and shows each beside its
  normal range (e.g. reference-bead z noise now vs the ~4 nm baseline of 2026-10-22; focus drift; share of saturated
  pixels; real fps, exposure vs frame period, CPU / USB load; device status), then lists fixes in order of likelihood.
  A fix that moves hardware goes through the same safety layer and asks the user first.
- **Case log of past experience:** a "record a problem" button snapshots the state (device status, fps, noise levels,
  settings, recent errors); the user adds symptom, cause, fix and outcome. When a diagnostic finds something abnormal,
  the guide shows past cases with a similar symptom and similar measured values. Lab-wide, searchable.
- **Seeded from real history:** the incidents recorded in MT_LabVIEW (V6) documents, e.g. ASI XY moved by the
  joystick, the field changed and beads gone, the camera resetting ROI and exposure on every open, unexpected PC
  shutdowns, the rotor zero offset, causes of frame loss.
- Works without AI (decision 0001): rule-based checks plus a searchable case log; an AI helper only as an optional
  add-on later.

**U10 - the screening protocol is programmable, preferably from the UI.** Owner 2026-10-22, current criteria
(single-biotin attachment):
1. "0 force --> 7 pN 당겼을 때 변위" (extension change from 0 to 7 pN);
2. "Rotation 돌려서 길이 변화 패턴이 있는지 [Multi-tethering 있는지], 그리고 trace의 radius가 얼마나 큰지 (angle이 일정
   이상으로 작아야 좋음)" (extension pattern under rotation reveals multiple tethers; radius of the x-y trace during
   rotation, the angle must be small enough);
3. "Rotation 했을 때 trace가 정상적인지. [원형으로 돌아야 하는데, 다양한 이유로 원형이 아닌 다른 모양을 가질 때가 종종
   있음]" (the x-y trace must be a circle).
Owner: "위의 기준은 사실 single-biotin을 사용하는 나에게 맞고, 케이스에 따라서는 기준선이 달라질 수 있음. 따라서 선별
프로토콜을 프로그램 가능하게 두었으면 좋겠음. 유저 친화적으로 프로그램 하면 좋긴 하겠는데... UI로 가능하면 정말 좋고"
- A protocol = **actions** (magnet to force / position, rotate -N..+N turns at a speed, hold and record t s; an
  ordered, reorderable list) + **metrics** chosen from a library (extension change between two segments; extension vs
  turns: presence and symmetry of a decrease, for multiple tethers; x-y circle radius during rotation and the angle
  derived from it; circularity: circle-fit residual, ellipticity, closure) + **rules** (comparisons combined with
  AND / OR). Each failed rule is shown as the bead's reason.
- Templates: "Single-biotin (SiHyeong)" ships as the default; others copy it and change thresholds; saved in the
  lab-wide library.
- Dry run on saved recordings, without the rig.
- Threshold tuning: the distribution of each metric over the beads is shown, and moving a threshold slider updates the
  pass / fail table live.
- Power users may add a metric as a small Python function; everyone else uses the UI only.
- **Owner's answers (2026-10-22):**
  - Angle: "Bead radius, DNA contour length 둘을 포함하여 계산. 이를 위해서는 특정 force값에서 어느 정도로 길이가 잡혀야
    하는지를 알아야 각도 계산이 될거임." Proposed (to be confirmed): attachment angle θ from the x-y circle,
    sin θ = r / R; and independently from the height deficit, z = L(F) - R (1 - cos θ), with L(F) from the
    worm-like-chain model and the contour length. Agreement of the two = a normal single attachment.
  - Rotation test: "+-10바퀴 정도면 괜찮은 기준 아닌가 싶음. 1~2 pN 사이면 사실 괜찮을듯." (depends on DNA length).
  - Thresholds: the owner's sample is nucleosomes; extension varies by condition (about 1400 nm in some, 800-900 nm in
    others), and the angle has never been computed explicitly, so no fixed numbers yet.
- **Follows:** rules may be **relative to the field** (e.g. within ±20 % of the median of the beads in view), and
  templates exist per sample type (naked DNA, nucleosome, ...); the threshold sliders (above) set the numbers per
  condition.
- Bead: M-270 amine (owner 2026-10-22), 2.8 µm diameter, R = 1.4 µm.
- **Open:** a recording that contains a rotation test, to try the metrics offline.

**U12 - eWLC fitting on a selected range, and an honest extension zero.** Owner 2026-10-22: "현재 LabVIEW에서 expected
WLC line을 그려주고, 파라미터를 조정할 수 있기는 한데 ... extensible WLC 모델이 아니어서 high force 영역에서 fitting이
벗겨간다는 점. 약 7 pN에서 extension 기준을 0 nm로 잡기 때문에, force를 내려주면 마이너스로 감. 그리고 저장하는 값도 이렇게
보정 안된 값을 저장하다보니 내가 추가로 보정하지 않는 이상 raw data가 이상하게 보임. 내 데이터 영역의 일부를 선택하여서 eWLC
fitting 해보고 거기서 persistence length 확인이 된다면 정말 좋을듯."
- Select a range on the force-extension graph with the mouse; fit an extensible WLC; show persistence length P,
  contour length Lc, stretch modulus S and zero offset z0 with uncertainties, plus residuals. Ranges can exclude
  unwrapping events (nucleosomes).
- **Model: the van Noort group's equations** (owner 2026-10-22: "van Noort 그룹에서 사용하는 equation이 좋을듯. 내
  publication 및 핵심 모델이 그걸 따르거든."). Verified from Meng, Andresen & van Noort, Nucleic Acids Res 43:3578
  (2015), full text via Europe PMC: DNA follows "an extensible WLC model" (their Eq. 1, citing Bustamante et al. 2000)
  with contour length L, persistence length A, stretch modulus S and kBT; the folded fiber adds a Hookean term per
  nucleosome (Eq. 3). Their analysis set the offset by aligning the high-force extension, after the last rupture, with
  a WLC of known contour length, A = 50 nm and S = 1200 pN, "to circumvent errors due to off-center attachment".
  **Eq. 1, supplied by the owner 2026-10-22 (screenshot of the paper):**
  `z_DNA(f, L) = L * [1 - (1/2) * sqrt(kB*T / (f*A)) + f / S]` (the Odijk high-force form).
  Implementation notes: valid at high force only (it turns negative below f = kB*T/(4A), about 0.02 pN at A = 50 nm;
  the paper analyses f > 0.5 pN), so the fit range defaults to f >= 0.5 pN with a warning below; each of L, A, S and
  the offset z0 can be fixed or fitted (defaults A = 50 nm, S = 1200 pN; z0 fixed when the zero-force zero is used);
  kB*T from the sample preset's temperature.
- **Zero:** owner 2026-10-22: "fitting을 제대로 하려고하면 0점을 잘 잡아야 할거야" and "zero-force로 내려서 영점을 잡고,
  그 보정을 기준으로 실시간 길이를 보는게 맞는듯." So the **primary zero is measured at zero force** (magnet far away)
  and the live extension is shown against it. The fit offset (van Noort high-force alignment) is kept as a cross-check;
  the difference between the two zeros reflects off-centre attachment and links to the angle metric of U10. Drift
  after zeroing is corrected with the reference bead.
- Saved values stay **raw**; the zero is stored **separately** with how it was set (fit z0 / surface contact / the
  LabVIEW 7 pN rule). The display offers raw / surface-referenced / fit-z0-referenced. Raw is never overwritten.
- `.tra` stays byte-compatible with LabVIEW (decision 0006); zero and correction metadata go to the HDF5 file.

**U13 - experiment presets, recorded in the data.** Owner 2026-10-22: "현행 트위저에서 실험하다 보면 거의 공통적으로
사용하는 파라미터들이 있을 것 같음. Bead는 무엇을 썼는지 (현재는 M270-amine 사용중), diffraction 보정 (지금은 0.88 사용하는
걸로 아는데, oil immersion이 cover slip과 만나고 채널 안의 물과 만나서면서 빛이 꺾이는 정도를 보정하는 것으로 알고 있음) 이런
정보들을 프리셋으로 저장해두고 꺼내 쓰면서, 동시에 최종 데이터에 해당 프리셋 정보도 같이 있으면 좋을 것 같음."
- Three preset layers: **rig** (objective, pixel size, camera settings, focal-shift factor, magnet-position-to-force
  calibration), **sample** (bead type and diameter, DNA construct name and contour length, sample type, buffer,
  temperature), **protocol** (screening template, experiment sequence).
- The full content of the chosen presets is written into each data file, so later preset edits never change what a
  file says about its own conditions (prevents stale values like the 84 nm/px of [rig-facts.md](../rig-facts.md)).
- The focal-shift factor carries its source (assumed 0.88 = 1.33/1.515, or measured); data keep both uncorrected and
  corrected z. The literature survey found a measured factor of 0.57 for an NA 1.49 objective (unverified authors),
  so measuring ours is worth considering.

**U14 - re-zero by clicking, during or after a run.** Owner 2026-10-22: "실험하다 보면 여러가지 이유로 에러가 생기는데
(프레임이 튄다던가, 아니면 실험하는 bead 위로 버블이나 다른 bead가 움직인다던가) 특정 시점에 클릭해서 원점을 갱신하는 방식이
편리할듯"
- Click on a trace (or press a button) to update the zero from that time on, in one of two modes: **"set zero here"**
  (mean over a short window, e.g. ±0.5 s, around the click; meant for a zero-force moment) or **"bridge a step"**
  (shift everything after a jump so the trace continues from before it; no force change needed).
- Scope: one bead, selected beads or all beads (a frame jump usually affects all; a bubble or a passing bead one).
- Mark **excluded segments** (bubble, passing bead) so fits and analysis skip them.
- Every re-zero and exclusion is an **event** in the data (time, beads, old and new value, reason: frame jump / bubble
  / other bead / other, user). Raw data are never changed; the display and exports apply the events. Undo and edit
  are possible.
- Later: suggest a bridge when all beads, or the reference bead, jump at the same frame; it is applied only after the
  user confirms.

**U11 - UI language.** Owner 2026-10-22: "글자는 무조건 영어." All UI text in English only.

**Note - local AI model.** Owner 2026-10-22: "Laya 내장하는거는 염두에 두고 있음. 로컬로 트레이닝한다면 내 계정이
필요없음." The owner is considering embedding "Laya", trained locally so no personal account is needed. What Laya
is: owner 2026-10-22, "Laya는 Jev와 유사한 AI 모델인데, 로컬로 설치 가능하며 fine tuning 가능하다는 장점이 있음" (an AI
model similar to Jev, installable locally and fine-tunable). Per decision 0001 any AI stays an optional add-on on top
of the normal interfaces; a natural use is the troubleshooting guide (U9), trained on the lab's case log.

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
