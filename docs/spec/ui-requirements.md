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

**U15 - device-settings presets, applied with read-back and saved with the data.** Owner 2026-10-22: "경우에 따라 장비
셋팅을 바꿔야하는 일이 종종 있음. 가장 대표적으로는 카메라 셋업. Frame rate은 어떻게 할 것이며, signal magnification은
무엇이며, acquisition mode는 무엇이며, 등등... 이 정보도 프리셋 적용하고, 데이터와 함께 저장하면 좋겠는데"
- Named presets per device, e.g. "JAI 150 Hz tracking", "JAI 90 Hz wide field", "iXon ALEX 15 Hz". Camera fields:
  frame rate, exposure, gain ("signal magnification"), acquisition mode (continuous / external trigger / ...), ROI,
  binning, pixel format; iXon adds EM gain, readout speed, pre-amp gain, cooling set point, frame transfer, trigger
  mode. Other devices (lasers, rotor speed, ...) use the same structure.
- **Applied after every device open, then read back and verified** before acquisition starts: the JAI resets ROI and
  exposure on every open (V6 `docs/camera-acquisition-facts.md`, measured 2026-09-14). A mismatch is shown and acquisition
  does not start.
- Checked before applying: exposure longer than the frame period, frame rate above the maximum for the ROI, mismatch
  with the EMCCD frame ratio N (0005); the reason is shown.
- The data file stores the preset name **and the values read back from the device** (they can differ from the preset).
- The active preset is visible in the device details window (U8).
- Owner 2026-10-22: "평상시에는 바꿀 일이 없는데, 종종 바꾸는 일이 있음. 예를 들면, force calibration을 위해서는 frame
  rate을 최대한 올려서 찍고 실험 목적으로는 90 Hz로 사용하는 것 같음. 그런데, 일부 케이스에 카메라 Hz 정보가 없으니
  데이터 분석에 문제가 생기더라고". So: two default presets, "Force calibration (max fps)" and "Experiment 90 Hz".
- **The frame rate can never be missing from the data:** every frame stores its absolute buffer number and the
  camera's own timestamp; the file stores the preset rate, the read-back rate and the rate measured from the
  timestamps, with a warning when they disagree. Cause of today's problem: the `.tra` first column, labelled "time", holds
  the frame (buffer) number (fixture `tra002-000`: 4 ... 11824), so without a separately noted rate the time axis
  cannot be rebuilt. `.tra` stays byte-compatible (0006); the rate and timestamps go to the HDF5 file, and the MATLAB
  `.tra` reader loads them from the companion HDF5 automatically.
- Old data without a rate: a rough estimate is possible from the header start times of consecutive `.tra` files of one
  run and their row counts (not exact).
- Answers spec question Q0.02: the application sets these itself and saves them with the data, rather than relying on
  whatever NI MAX holds.

**U16 - device and run metadata saved with every data file.** Owner 2026-10-22: "저장하는 데이터에 장비의 정보들이 같이
저장되면 좋겠음. MT 데이터나 형광 데이터에 직접 들어가지 않지만 메타데이터로 두고 나중에 Matlab 분석에서도 참고할 수 있도록".
Structure in decision 0006, "Later notes": a `metadata` group (devices, presets, run) apart from the data tables, a JSON
copy for quick reading, one run ID shared by MT and fluorescence files, and a MATLAB `meta` struct.

**U17 - settings change while the program runs.** Owner 2026-10-22: "실험에 들어가기 전에도 장비를 가동하며 이리저리
움직여 봐야함. 현행 코드는 configuration이 코드 시작부분에 있어서 한번 셋팅하면 코드 작동중에 바꾸는게 불가능함. 이 부분
개선 필요"
- Configuration is **runtime state held by long-running device services**, not start-up constants; the GUI sends
  change requests; no restart is needed.
- An **exploration mode** before the experiment: live image, jog magnet / rotor / focus, change settings, no recording
  (or a short optional one).
- Three kinds of setting: **immediate** (exposure, gain, magnet, rotor, focus, display); **needs a short pause** (ROI,
  binning, JAI frame rate: the application stops acquisition, applies, reads back, restarts - one button for the
  user); **guarded while recording** (changes that alter how data are read, e.g. frame rate, ROI: confirmation, and an
  event with its time in the metadata, U16).
- Every change passes the safety checks and is logged with its time.
- "Save current settings as preset" turns a good combination found in exploration into a preset (U13, U15).

**Feedback on the first mock-up (owner 2026-10-23)**

**U18 - edit the protocol loop during an experiment.** "Experiment 중간에도 루프 수정이 가능해야 함." Edits made while a
protocol runs go to a draft; "Apply changes" commits them: steps not started yet take them now, steps already done
this loop take them from the next loop; the running step is locked. A draft that leaves the safe range (e.g. force
above the limit) cannot be applied. Every applied edit is an event with the old and new steps (U16).

**U19 - extensible screening and protocols, by script or by visual blocks.** "Screen condition에서 3 가지 조건으로
셋업되어 있음. (그러나 추후 상황에 따라 얼마든지 가능할 수 있기에 조금 더 확장 가능성 있는 방향이면 좋겠음. 1) Scripting으로
프로토콜을 작성 (지정된 방식을 통해) --> 프로그램에서 인식 --> 그래프 혹은 테이블로 표현 2) 시각적 프로그래밍 방식 차용하여
프로토콜 작성"
- One protocol model with two equivalent editors: **blocks** (visual: action blocks, rule blocks, add / remove /
  reorder) and **script** (a defined text format, one step per line, `key=value`; "Check and use" parses it, reports
  errors by line, and shows the result as blocks, a table and a force / rotation preview graph).
- Screening rules are a list (metric, comparison, threshold) of any length over a metric library; new metrics (incl.
  a Python function) extend it. Screening and experiment protocols share the format and engine (0012).
- Proposed script grammar (mock-up): `zero t=5`, `ramp from=0 to=7 t=30`, `hold f=7 t=10`,
  `rotate from=-10 to=10 f=1.5 t=40`, `record t=10`, `repeat 3`, `rule dext >= 0.8`.

- **The script is a defined grammar, not AI.** Owner asked 2026-10-23: "프로토콜을 스크립트로 작성했는데, 이 부분 AI가
  해석해야 하는거야 아니면 문법이 갖춰진거야?" Answer: a fixed grammar parsed deterministically by the program, with
  line-numbered errors; AI may only draft scripts through the gateway (0014). Before implementation a grammar
  specification (every keyword, parameter, unit and allowed range) is written in `docs/format/`.

**U20 - visible Save / Save as / Load for protocols and presets**, and a lab library browser. "프로토콜, 프리셋 등을 저장하는
버튼이 보이지 않음."

**U21 - saving runs asks where, like `uigetfile`.** "Save는 '시작 디렉토리'를 지정할 수 있으나, 기본적으로는 uigetfile처럼
프롬프트를 띄워서 물어보는게 좋을듯". A start folder is set in the settings; every save opens a file dialog that starts
there and asks for folder and name.

**U22 - mapping (channel registration).** Owner 2026-10-23: "Mapping". smCamera had it as Movie Mapper
([smcamera-emccd-parameters.md](../manuals/smcamera-emccd-parameters.md) section 5).
- Fluorescence CH1 <-> CH2: record or open a bead movie, find spots in both halves automatically, pair them, fit a
  polynomial (default cubic, as the old map files), show the rms residual and an overlay; save the map with date and
  objective in the library; data record which map was used. Existing `map_Andor1_*.txt` files can be imported.
- New for MT-TIRF: JAI bright field <-> iXon fluorescence mapping with targets visible in both, so a tracked bead's
  position gives its fluorescence ROI automatically.
- Owner 2026-10-23: "Mapping의 경우 single channel, 2 channel, 3 channel로 사용할 것 같고 각 채널 정체를 define할 수 있고
  그 정보를 프리셋 저장도 가능해야겠음. 동시에 magnetic bead와 EMCCD 사이의 mapping 역시 필요함. 사전의 mapping을 통해서
  데이터를 불러오는게 맞겠고, mapping 데이터 형식은 어떻게 할지도 정하면 좋을듯". So: a **channel-layout preset**
  (1 / 2 / 3 channels, each named and defined), **maps measured beforehand and loaded at run start**, and a map file
  format: proposal in [docs/format/mapping.md](../format/mapping.md) (not yet decided).

**U23 - automatic candidate finding by parameters.** Owner 2026-10-23: "automatic check (radius 등의 parameter 넣고 버튼
누르면 자동으로 candidate 찾았던 것 같음.)" smCamera's Movie Analysis stored e.g. 3.0, 5.0 (radius-like), 1.7
(threshold-like) and a frame range in `analysis.save` (meanings inferred).
- Parameters + "Find" button; results update live as parameters change; result table; manual add / remove;
  parameters saved as presets.
- Fluorescence: spot radius, threshold, background handling, frames to average (the old FrameSequence role).
- MT beads: ring radius range, contrast threshold, minimum distance to neighbours, edge margin; candidates flow into
  screening (U10, U19).

**U24 - shutter and laser control.** Owner 2026-10-23: "내 기억으로는 shutter 컨트롤도 아마 했던 것 같음." Confirmed by the
static analysis ([smcamera-emccd-parameters.md](../manuals/smcamera-emccd-parameters.md) sections 3 and 7): smCamera
opened / closed the iXon's own shutter (`SetShutter`), and the separate ShutterManager drove three laser shutters
through an NI PCI-6503 (lines 1, 4, 7) from per-frame 0/1 sequence files split into header / body / footer, timed by
the PC through shared memory.
- An **illumination sequence editor** (0013): one column per laser or shutter, one row per EMCCD frame, with header /
  body (repeated) / footer parts; block and script editing like protocols (U19); a per-frame preview. Old
  ShutterManager files can be imported (column-to-laser assignment to be confirmed on the rig).
- Executed by the Arduino in hardware, locked to camera frames (0005), never timed by the PC.
- Manual open / close per laser and shutter in Explore, for alignment and focusing.
- Lasers and shutters close automatically whenever nothing is being recorded (photobleaching); every change is an
  event (U16).
- Owner 2026-10-23: "셔터는 나중에 결정할 부분이기는 하고" and "셔터는 지금 1) 기계식 셔터, 2) AOM 3) 레이저 컨트롤러 셋 중
  하나를 선택할 예정". So the light switch is **one interface with three back-ends** (mechanical shutter, AOM, laser
  controller e.g. OBIS digital modulation); the sequence files and screens are shared, only the device settings differ
  (shutter open / close delay; AOM TTL polarity and analog power level; laser modulation mode and power). All three
  are driven by Arduino TTL locked to frames (0005). Before a run the program checks the chosen back-end's switching
  time fits the gap between frames (e.g. warns for fast ALEX with a mechanical shutter). The back-end and its settings
  are stored in the metadata. Typical switching times (mechanical ms, AOM µs, laser modulation µs to tens of µs) are to
  be checked on the actual hardware.
- **Open:** which back-end; which wavelengths.

**U25 - identify the right fluorescence signal under a large bead.** Owner 2026-10-23: "Bead가 워낙 거대하다보니, bead에
연결된 DNA fluorescence signal이 뭔지 모를 수도 있다 임. 예를 들면, DNA labeling이 빽빽하게 되어 있을 때, bead 밑에 여러
개의 fluorescence 신호가 나올 수 있음. 이 때 어떻게 하면 정확하게 우리가 원하는 signal을 특정할 수 있는가"
Proposed (discussion, not decided): score every candidate spot near a bead on three kinds of evidence and recommend
one; the user decides.
- **Position:** the centre of the bead's x-y circle during rotation = the tether's surface anchor; mapped to the EMCCD
  (U22, needs < 1 px accuracy), candidates within a radius of it.
- **Time:** a true signal changes when the mechanics change (extension events, unwrapping); cross-correlate event
  times of extension and intensity / FRET per candidate.
- **Shape:** single-step photobleaching; ALEX stoichiometry for donor + acceptor on one molecule.
- Experimental side: lower labelling density, better passivation, a bead-free control for the surface background.
- Feeds the troubleshooting guide (U9).

**U26 - fluorescence focus away from the surface (discussion).** Owner: "만약 fluorescence dye가 바닥이 아닌 조금
distant 한 곳에 위치한다면, focus를 바닥이 아닌 형광 위치정도로 두고 찍으면 되지 않을까 싶음. (다만 추가로 고려할 부분은,
extension 및 force 값에 따라 형광 위치가 요동칠텐데 그 부분을 감당 가능할지 모르겠음)"
- TIRF excites only ~100-200 nm above the surface; a dye higher up may need HILO / epi illumination, not just refocus.
- Bright field and fluorescence share the objective: moving the objective focus changes the bead image and breaks the
  z look-up table. A focus offset belongs in the **fluorescence path only** (e.g. a motorised relay lens or camera
  position before the EMCCD).
- Fluctuations: at high force tens of nm (inside a ~0.5-1 µm depth of field); force changes move the dye by µm. A
  focus follower could use live z (dye height ≈ surface + fraction × extension). Value depends on the illumination.

**U27 - comparable fields of view for fluorescence and bead tracking (discussion).** Owner: "형광 ROI와 magnetic bead
ROI를 대체로 비슷한 스케일로 맞추고 싶음. 현재는 형광 영역에서 너무 좁게 보고 있는 것같으니 형광 영역을 키우면 좋겠음.
아마도 렌즈 배율을 조정하는게 좋을 듯"
- Estimates (assumed iXon 897: 16 µm pixels, 512 × 512; 50x; extra emission-path magnification unknown): JAI ≈ 256 ×
  205 µm at ~200 nm/px; iXon without extra magnification ≈ 164 × 164 µm at ~320 nm/px, ≈ 82 × 164 µm per channel when
  split in two.
- A demagnifying relay widens the EMCCD field; larger pixels lower localisation precision but are fine (better SNR)
  for intensity-based smFRET. The choice follows the main measurement (intensity FRET vs. fluorescence localisation).
- **Open:** iXon model and the present emission-path magnification; main fluorescence measurement.

**U28 - FRET pipeline and MATLAB integration.** Owner 2026-10-23, from an explanation of smCamera received that day:
"1) 데이터 얻음 (~.smm) 2) 데이터 형태 전환 (~.smt) 3) 이후 다른 데이터들로 전환 (*.trace, .... 대략 7개의 형태?) 4) 이후
Matlab으로 분석함 (*.trace 쓴다고 함). 1) -> 2) 의 과정에서, shutter 정보를 읽는데 .txt 파일로 짜여있음 (0;0;0;0;1;1;1;1
--> 5~8 frame 해당됨). 전체의 movie .smm 데이터에서 Green laser, Red laser excitation 프레임을 지정함 --> Red/(Red+Green)
적용하여 계산. ( pre-defined mapping 파일도 적용함) --> FRET 계산 후 데이터 export." and "결국 Matlab 분석을 가능하게
해야하며, 이 부분은 기존의 MT 분석 라이브러리와 추후에 얻게 될 FRET 분석 library를 통합해야 할 것 같음. smCamera 예시
데이터는 추후 첨부하도록 하겠음."
- Fewer steps: the raw EMCCD movie (saved raw, 0006) plus **one combined file** with MT and FRET on one time axis.
  Per-frame excitation comes from the illumination sequence **actually executed** (U24, metadata), not from a separate
  text file; MT and EMCCD frames are linked by absolute buffer numbers (0005).
- Per molecule: ROI from the map (U22, U25), per-frame channel intensities with background, apparent FRET =
  acceptor / (acceptor + donor) on donor-excited frames. **Red-excited frames serve as a correction for the FRET
  calculation** (owner 2026-10-23: "ALEX 보다는, FRET 계산을 위한 보정으로 이해했음"), most likely the acceptor
  direct-excitation correction; donor leakage and gamma corrections may also apply. The exact formula smCamera uses is
  to be read from the example data / MATLAB scripts. Correction factors are preset values, recorded in the data, and
  FRET can be recomputed with other factors.
- MATLAB: export `.trace` in smCamera's format for existing scripts (format from the owner's example data), and one
  MATLAB package that reads the combined HDF5 and the legacy files, aligns MT and FRET time axes and offers the basic
  plots; the existing MT analysis library and the future FRET library are merged into it (extends 0011).
- **Open:** example smCamera data (`.smm`, `.smt`, `.trace`, the shutter `.txt`), the list of the ~7 formats and which
  ones are still used.

**U29 - FRET and extension overlaid.** Owner 2026-10-23: "필요한 그래프는 결국은 FRET, extension 둘이 오버레이된
그래프는 반드시 필요하겠고, 그 외에 필요에 따라 다양한 데이터 조합 및 분석이 있겠음." A required plot: FRET and
extension on one time axis (two y-axes), live in the application and as a function in the MATLAB package. Other
combinations through the graph axis choice (U3), with FRET, donor / acceptor intensity and stoichiometry added as
variables.

**U30 - numeric entry for every setting; sliders only as a shortcut.** Owner 2026-10-24 (on the Explore screen):
"Magnet position, Camera settings 등이 숫자로 입력 가능하도록. 스크롤 하는건 보조역할이면 괜찮은데 유일하면 곤란함".
Every adjustable value (magnet position, rotor, focus, exposure, gain, thresholds, ...) has a number box with its unit
and step buttons; a slider may sit beside it as a shortcut but is never the only way. Values are clamped to the
allowed range, and the range / limit is shown next to the box. Applied on Enter or when the box loses focus.

**U31 - moving the JAI camera along the axis for a fluorescence focus offset (hardware + program).** Owner 2026-10-24:
"EMCCD를 움직이려면 한 번에 움직여야 할 부품이 너무 많아서 현실성이 떨어짐. IR camera (JAI)를 움직이는게 가장 간편함. 만약
어렵다면 샘플 바꿀때만 움직이는게 좋을 것 같음. 수동이라면 위치 기록이 어렵기는 함. 빼먹을 수도 있고, 수치도 신뢰가 어려울
수 있고". (Replaces the fluorescence-path-only idea of U26: the objective focus goes to the dye plane, the EMCCD stays
fixed, and the JAI camera is moved so the beads image well.)
- Facts found 2026-10-24: the SP-5000M-USB is C-mount (flange 17.526 mm per a distributor listing, to confirm). No
  off-the-shelf **motorised** C-mount focusing tube was found; manual ones exist (ASI C-mount focus adapters ±1.7 / ±4 mm,
  Edmund fine-focus tube, Thorlabs SM1Z).
- Scale: moving the camera by Δ moves its conjugate plane at the sample by about Δ / M²; at 50x, about 2.5 mm of camera
  travel per 1 µm at the sample (ASI ±4 mm ≈ ±1.6 µm). The needed range follows from the dye's height.
- **Only between samples, before calibration.** The z look-up table assumes a fixed objective-camera geometry: after
  any camera move the program marks the LUT invalid and blocks the experiment until a new calibration; the pixel size
  may change slightly and is re-checked per position.
- **Position always recorded automatically**: (1) a motorised stage with encoder (if ASI, check whether an axis can be
  added to the existing Tiger controller), or (2) a manual tube with a digital gauge / micrometer with USB readout read
  by the program; typing the value by hand is not relied on. The position is read at calibration start, stored in the
  `.cal` metadata and the run metadata (U16), and a later change raises a warning.
- Owner 2026-10-24: the JAI sits on the IX73 at the turret position directly below the objective. If that branch has
  its own tube lens in infinity space (likely, to be confirmed), refocusing the JAI does not touch the EMCCD path, and
  besides moving the camera, **moving only the JAI tube lens** or putting an **electrically tunable lens** there are
  options that may fit the tight turret space better. The JAI magnification is 50x × (its tube-lens focal length / 180 mm,
  Olympus standard), so the nominal 200 nm/px and the travel estimate depend on that focal length.
- **Open:** the dye's height above the surface (sets the travel); motorised vs manual + digital readout; the JAI tube
  lens (present? focal length?) and the free space around the turret port.

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
- **Mock-up (2026-10-22/23):** https://claude.ai/artifact/Hg7YRQbKfDN8jZyEDeMLHd (private until shared from its Share
  menu). Version 1 covered U1-U17; version 2 added U18-U21 (mid-run protocol edits, block + script editors, save /
  load buttons, save dialog with start folder). Not yet in it: mapping screens (U22), parameter-based candidate
  finding (U23), illumination sequence editor (U24), signal identification (U25).
