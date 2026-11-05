# GUI 디자인 비평, 2026-11-05 (디자인 린트; 코드는 바꾸지 않음)

영문 원본: [design-critique-2026-11-05.md](design-critique-2026-11-05.md).

**자료.** `src/mtpy/gui/app.py` (창: 상단 바, Setup / Run / Explore / Beads / Calibrate / Experiment / Save 단계 바,
카메라 화면 둘, 그래프, 이벤트 목록), `src/mtpy/gui/calview.py`, `src/mtpy/gui/exptable.py`, [gui.md](gui.md),
목업 [2026-10-23-main-window](../mockups/2026-10-23-main-window/README.md), 그리고 시뮬레이터에서 찍은 모든 페이지의
스크린샷 (`python -m mtpy.gui --backend sim --sim-dev`, 연결 후 acquisition 실행 중, 1500 x 950 px). 리그에서는 아무것도
실행하지 않았다.

**판단 기준은 2026-11-05 사용자의 말.** "보통 실험은 카메라 보고, 비드 찍고, 비드 캘리브레이션, 저장 위치 정하고,
트래킹, 저장인데 여기는 다 흩어져 있다"; 사용자는 리그만 본다 (시뮬레이터 설정 없음); 파일 이름은 LabVIEW를 따른다
(cal001, tra001, tra001-000); STOP은 비상 정지다.

**단계.** 시뮬레이터에서의 첫 빌드, 실행하면서 고치는 중 (사용자 2026-10-29). 결과는 흐름과 문구에 관한 것이지 마감이
아니다.

## 전체 인상

Run 페이지는 "다 흩어져 있다"에 대한 올바른 답이다: 실험 순서대로 한 페이지. 그러나 아직 문장 옆에 버튼을 붙인
목록이고, 첫 단계의 버튼은 상단 바에 있고, 저장 대화상자는 스캔 뒤에 뜨고, 창의 나머지는 여전히 개발자의 말을 한다
(결정 번호, 임시 경로, 이벤트 목록의 Python dict, 리그를 움직일 수 있는 예제 프로토콜이 미리 채워짐). 번호가 붙은
다른 여섯 페이지가 Run과 경쟁한다. 가장 큰 기회: Run을 사용자가 머무는 페이지로 만들고, 나머지 페이지는 "단계"가
아니라 "설정"으로 읽히게 하는 것.

## 발견, 심각도 순

심각도: **critical** = 리그를 움직이거나 데이터를 잃을 수 있음, 또는 보통 실험을 막음; **moderate** = 다른 페이지로
가거나 추측해야 함; **minor** = 문구와 마감.

### Critical

| # | 패널, 위젯 | 발견 | 바꿀 것 |
|---|---|---|---|
| 1 | **Experiment**: 표 (`ExpTable`, `EXAMPLE`)와 텍스트 편집기 (`EXAMPLE_PROTOCOL`), "Start from table"과 "Start" 버튼 | 둘 다 **예제 프로토콜이 미리 채워진 채** 열린다 (표: 50 pN과 -3600 / +3600도 회전; 텍스트: 1 -> 5 pN 램프). 리그에서 Start 하나를 누르면 그대로 실행된다. Check는 통과하고 값은 한계 안이다. 예제가 사용자 본인의 표라서 실제 계획처럼 보인다. | 둘 다 비워서 연다 (표는 0 한 열). 예제는 "Load example" 버튼이나 Script guide 뒤로. 그 전까지는 Start가 프로토콜 이름과 요약을 확인창에 보인다 ("'table' 시작? 5단계, 최대 50 pN, 10회전"). |
| 2 | **Run 페이지**, 3단계 "Calibrate the picked beads...": 저장 대화상자 두 개 | 사용자는 "저장 위치 정하기"를 한 단계로 꼽았다. 여기서는 .cal 대화상자가 스캔 전에, **run 파일 대화상자가 스캔 뒤에** 뜬다 (`_track_from_cal`). 1분쯤 걸리는 스캔 동안 화면 앞에서 두 번째 대화상자를 기다려야 하고, 거기서 취소하면 "calibrated, not tracking"이 되어 Beads -> Select checked beads로 가야 한다. | 스캔 전에 한 번만 묻는다: 데이터 폴더 대화상자 하나, 이름은 파생해서 보여준다 (cal001과 그 옆의 tra001). 그 뒤 스캔 -> 트래킹을 멈춤 없이. 다른 이름이 필요한 드문 경우를 위해 "Change..."만 남긴다. |
| 3 | **Calibrate**: "Write .cal to" (`cal_out`, `QSettings("KimLab", "MT Tracker").value("data_dir")`에서 채움) | 테스트가 Run 페이지 3단계 (`_flow_calibrate`)를 거치면서 **사용자의 실제 QSettings에 데이터 폴더를 쓴다**. 스크린샷의 상자는 `...\pytest-559\test_run_page_calibrates_then_0\cal001`이다. 테스트도 도는 리그 PC에서는 저장 대화상자가 pytest 임시 폴더에서 열리거나, 상자가 이미 없는 폴더를 가리킨다. | 테스트는 사용자 설정을 건드리면 안 된다 (`tests/test_gui.py`에서 `QSettings.setDefaultFormat`으로 임시 ini, 또는 `MainWindow`에 `settings` 인자). 기억한 폴더가 없어졌으면 run 폴더로 되돌아간다. |
| 4 | **상단 바**: "Stop acquisition" 옆의 "Record", "STOP", "Acknowledge" | 한 줄에 정지가 셋: "Stop acquisition" (카메라), "Stop" (Experiment: 프로토콜), "STOP" (비상). 빨간 버튼이 "Record" 바로 오른쪽이라 Record로 가던 손이 닿는다. "Acknowledge"는 비상 정지가 안 걸렸을 때도 **항상 보여서** "이게 뭐냐"는 질문이 나왔다 (사용자 2026-11-05). | STOP을 맨 오른쪽에 간격을 두고 "EMERGENCY STOP"으로, 단축키를 준다 (목업의 배너가 무엇을 했는지 보여준다); "Acknowledge"는 정지가 걸린 동안 빨간 배너 안에서만 보인다 (목업에는 배너가 있고, 빌드에는 상태줄 한 줄뿐). |

### Moderate

| # | 패널, 위젯 | 발견 | 바꿀 것 |
|---|---|---|---|
| 5 | **Run 페이지**, 1단계 "Start acquisition (top bar) and watch the JAI image" | 첫 단계의 버튼이 **페이지에 없다**; 문장이 상단 바를 가리킨다. 다른 단계는 모두 옆에 버튼이 있다. | 페이지에 "1. Start the camera" 버튼 (상단 바와 같은 핸들러); 실행 중이면 "camera running, 90 Hz"로 바뀐다. |
| 6 | **Run 페이지**, "3. Calibrate the picked beads..."와 "Reset calibration" 버튼 | 주 동작과 **파괴적** 동작 (비드를 버리고 run 파일을 닫음)이 같은 크기, 같은 모양으로 나란히 있다. "Reset"은 "캘리브레이션 값을 초기화"로도 읽힌다. | 3단계를 페이지의 유일한 굵은 / 기본 버튼으로; "Reset calibration"은 4단계 아래로 옮겨 "Start over (drop the beads, pick again)"로 하고 run 파일이 열려 있으면 확인창. |
| 7 | **Run 페이지**, 4단계 "Record on / off" | 버튼에 **상태가 없다**: 상태는 멀리 상단 바의 "Record" / "* Recording"과 상태줄에 있다. 문장에는 run 파일 이름만 있고 녹화 상태는 없다. | 상단 바를 비추는 체크 가능한 버튼 ("Recording into tra001.h5"), 또는 페이지 버튼을 빼고 4단계 문장이 상태를 보인다. |
| 8 | **단계 바** 1-7 | 번호가 순서를 약속하지만 (Setup -> Run -> Explore -> Beads -> Calibrate -> Experiment -> Save) 실제 순서는 Run 하나다; Beads, Calibrate, Save는 **Run의 하위 단계**인데 동급으로 보이고, Experiment (프로토콜)는 Run에서 닿지 않는다. Run 제목은 "camera -> beads -> calibrate -> track -> save"인데 바는 같은 것을 4, 5, 7로 부른다. | 바를 두 묶음으로: "Setup | Run | Experiment"는 번호, "Explore, Beads, Calibrate, Save"는 번호 없이 "Settings and details" 아래 (또는 Run 안의 탭). Run 페이지에 "6. Run a protocol (Experiment)" 줄을 더한다. |
| 9 | **Setup**: "Safety profile" 라벨 (`_profile_label`) | 첫 페이지의 첫 항목이 세 줄짜리 **임시 경로**와 셸 명령이다 ("change: python tools/rig_set_limit.py <quantity> --max ... --reason "...", then restart"). 사용자는 어디서 설정되는지 보고 싶다고 했지, 이건 개발자의 답이다. | "Rig safety profile v10 (verified)"과 한계를 작은 표로; 파일 경로와 명령은 툴팁이나 "Details..." 패널로. |
| 10 | **Setup**: 그룹 제목 "Camera preset (U15)", "Analysis (decision 0024)", "Force equation (decision 0018)"; Mode 콤보의 "(phase 10a)" | 사용자 라벨에 **결정 번호와 요구사항 번호**. 리그에서는 아무 뜻이 없다. | 평범한 제목: "Camera preset", "Tracking", "Force from magnet position"; 번호는 코드 주석에만. |
| 11 | **Setup**: Mode 기본값 "MT-TIRF: tracking + EMCCD, Arduino sync, lasers, light gating" | 기본 모드가 EMCCD를 열고 phase 10a가 아직 만들지 않은 레이저와 light gating을 약속한다; MT 실험 중에 EMCCD 화면이 카메라 영역의 절반을 차지한다 ("EMCCD: no frame"). | 10a가 들어오기 전까지 기본 MT; MT-TIRF 항목은 오늘 하는 것만 적는다 ("tracking + EMCCD"). |
| 12 | **이벤트 목록** (하단) | 줄이 **Python dict**다: `device {'extra': {'device': 'emccd', 'action': 'open', 'origin': None}}`. "방금 무슨 일이 있었나"를 보는 유일한 목록을 해독해야 한다. | 이벤트 필드로 한 문장씩 ("21:21:59 emccd opened", "21:22:02 acquisition started, 90 Hz, no beads"); dict는 더블클릭이나 `gui_events.log`에만. |
| 13 | **상태줄**이 거부의 유일한 자리 (`_fail`: 15초) | 거부된 동작 ("calibrate: start acquisition and left click the beads first", "run protocol: ...")이 누른 버튼에서 먼 왼쪽 아래에 15초 보인다; 2026-11-04의 두 번째 Start 증상이 여기서 왔다. | 거부를 컨트롤 옆에: Run 페이지 단계 라벨이 빨갛게 바뀌며 문구를 보인다; Experiment에는 이미 `prot_status`가 있다 - 모든 페이지에 같은 패턴. |
| 14 | **Calibrate**: 뷰어 (`CalView`, 최소 높이 560 px) | .cal을 읽기 전에 세 플롯이 **-0.4..0.4의 빈 축**을 보이며 페이지를 스크롤로 밀어낸다; "no .cal loaded"는 위의 한 줄이다. | `load()` 전까지 플롯을 숨긴다 (또는 "no calibration yet" 자리표시자 하나); 또는 카메라 설정처럼 뷰어를 별도 패널로. |
| 15 | **Calibrate**: "Save to .cal (then select the beads again to track with them)" | 새 band-pass 값을 저장해도 **적용되지 않는다**; Beads -> Select checked beads로 가야 한다. 카메라가 더는 멈추지 않으니 프로그램이 할 수 있다. | 추적 중인 비드가 그 비드면 Save가 `api.beads.select` / `api.acq.retarget`으로 적용한다; 버튼은 "Save and use". |
| 16 | **Beads**: ".cal file" 상자, "Load list", "Select checked beads", "Reference bead ids (comma)" | Run 3단계의 수동판인데 빈 목록이 페이지를 채운다; 보통 흐름에서는 비드 1이 기준인데 여기서는 기준 비드를 텍스트 상자에 id로 친다. | 상세 페이지로 두되 제목에 그렇게 적는다 ("Beads: the list behind Run"); id 텍스트 상자 대신 비드 행마다 "reference" 체크박스. |
| 17 | **Save**: "Run name (next acquisition)"과 여섯 줄 문단 | 문단은 Run 페이지가 이미 하는 이름 규칙을 설명한다; Run 페이지가 채우는 이름 상자를 손으로 고친다. tra00N의 진실이 둘. | 이름을 읽기 전용 사실로 ("next run file: tra003.h5 in D:\data\...")와 "Change..." 버튼 하나; 문단은 툴팁으로. |
| 18 | **Explore**: "Exposure (immediate)" / "Gain (immediate)" 대 Setup의 "Camera preset" | 노출을 두 곳에서 다른 말로 설정한다 ("immediate" 대 "Apply preset and read back"); 트래킹 중의 변경은 LUT를 틀리게 한다 (2026-10-30 대기 항목). | 한 곳 (Setup의 카메라 설정); Explore는 값과 "Change..."를 보이고 비드 추적 중이면 경고한다. |

### Minor

| # | 패널, 위젯 | 발견 | 바꿀 것 |
|---|---|---|---|
| 19 | **Run 페이지** 단계 문장 | 문법이 섞여 있다: 3단계는 소문자로 문장 중간에서 시작하고 ("3. asks where to write..."), 5단계는 서술문, 1-2단계는 명령문; "Script guide" 버튼이 저장과 무관한 Save 줄에 있다. | 전부 명령문으로 ("3. Calibrate...", "5. Save the traces..."); "Script guide"는 Experiment 페이지와 상단 Help로. |
| 20 | **카메라 화면** 라벨 "JAI frame 396 seg 1 t 4.400 s 90.0 Hz" | "seg 1"은 파이프라인의 세그먼트 카운터다. | "JAI 90.0 Hz, frame 396, 4.4 s"; 세그먼트는 상태줄에. |
| 21 | **그래프** 빈 상태 | 추적이 없는데 0..1 축과 격자만 있다. | 첫 점까지 가운데에 "no beads tracked". |
| 22 | **Explore** 자석 슬라이더 | 위치 상자 아래 눈금도 끝 라벨도 없는 맨 슬라이더 (0과 40.9 mm). | 양 끝 눈금 라벨, 또는 슬라이더 제거 (상자와 "move by"로 충분). |
| 23 | **Explore** "Move" x 5, "Set" x 2 | 다섯 줄에 같은 단어; 눈이 구분하지 못한다. | "Move magnet", "Move focus", "Set exposure" - 또는 줄마다 "Go" 하나에 줄 라벨을 굵게. |
| 24 | **Beads** ".cal file" 상자 | 긴 경로의 꼬리만 보인다 ("2 Ramp_Newbatch\test\cal002"). | 가운데를 줄임 (`Qt.ElideMiddle`), 전체 경로는 툴팁. |
| 25 | **상단 바** "Pause display" | 바의 첫 버튼이 가장 덜 쓰는 것; "Devices: 8 / 8 connected"가 유일한 장치 상태다. | 순서: devices, acquisition, Record, 그다음 Pause display; 프로토콜 배지는 실행 중에 색을 입힌다. |

## 시각적 위계

- **눈이 먼저 가는 곳:** 빨간 STOP (비상 컨트롤로는 맞음), 그리고 Setup에서는 안전 프로파일의 임시 경로 (틀림: 사용자는
  Connect를 먼저 봐야 한다). Run에서는 강조된 것이 없다: 회색 버튼과 회색 글자뿐.
- **읽는 흐름:** 상단 바 -> 단계 바 -> 오른쪽 패널; 왼쪽의 카메라와 그래프가 내용인데 바의 오른쪽 정렬 버튼 아래에
  있어 눈이 지그재그로 움직인다. 맨 아래의 이벤트 목록이 가장 나중에 읽히면서 글자는 가장 많다.
- **강조:** 어느 페이지에도 기본 / 주 버튼이 없다; Run에서는 "3. Calibrate..."가 그래야 한다.

## 일관성

| 요소 | 문제 | 권고 |
|---|---|---|
| 버튼 문구 | "Start acquisition" (상단 바) 대 "Start" (프로토콜) 대 "Start from table"; "Stop acquisition" / "Stop" / "STOP"; "Record" / "Record on / off" | 매번 대상을 적는다: "Start camera", "Start protocol", "Stop protocol", "EMERGENCY STOP". |
| 말줄임표 "..." | "Calibrate the picked beads..."는 대화상자를 연다 (맞음); "Change..." (맞음); "Browse..." (맞음); "Script guide"는 파일을 연다 (점 없음); "Camera settings..."는 패널을 연다 | 대화상자가 따라올 때만 점; 패널 버튼은 점 없이. |
| 라벨의 번호 | Run 페이지는 문장에 1-5, 단계 바는 페이지에 1-7, Experiment 표는 열에 1-5 | 사용자가 따르는 순서인 곳 (Run 페이지)에만 번호. |
| 내부 참조 | "(U15)", "(decision 0024)", "(decision 0018)", "(phase 10a)", "SPD", "seg 1", "bead_i32" (calview 독스트링, 화면에는 없음) | 사용자 라벨에서 뺀다. |
| 테마 | 검은 pyqtgraph 뷰를 흰 Qt 패널이 둘러쌈; 목업은 어두운 창 | 실험실에서는 어느 쪽이든 좋다; 하나를 골라 검은 뷰가 구멍처럼 보이지 않게. 목업의 어두운 헤더가 LabVIEW에 더 가깝다. |
| 목업 대 빌드 | 목업: 왼쪽 세로 단계 목록, 비상 정지 배너, Library; 빌드: 가로 바, 배너 없음 | 가져올 것은 배너 하나 (발견 4). |

## 접근성

- **색 대비:** STOP의 흰 글자 on #B91C1C 6.9:1 (통과); SIM-DEV 황색 #B45309 on 흰색 4.6:1 (굵은 글자 AA 통과); 회색
  이미지 위의 노란 pick 상자 #FBBF24 양호; 그래프의 검은 바탕 흰 글자 양호. 프로토콜 배지 "no protocol"은 검은
  평문 - "running"에 색이 없다.
- **타깃:** 마우스 전용, Qt 기본 (버튼 높이 약 24 px) - 리그 책상에서는 충분; 표 셀 (너비 70 px)은 -3600을 치기에
  작지만 쓸 만하다.
- **키보드:** 비상 정지 단축키가 없다; 어느 페이지에도 기본 버튼이 없다 (Enter가 아무것도 안 한다). STOP에 단축키,
  Run 페이지에 기본 버튼.
- **글자:** 전체 Qt 기본 9 pt; Run 페이지 문장이 440 px에서 네 줄로 접힌다 - 읽히지만 빽빽하다; 이벤트 목록의 dict
  줄이 유일하게 읽을 수 없는 글자다.

## 잘 된 것

- Run 페이지가 있고 그 순서가 사용자의 순서다; 기억하는 데이터 폴더와 LabVIEW 이름 (cal001, tra001, tra001-000)이
  맞다; 페이지의 "Reset calibration"과 pick 수가 Beads로 가는 걸음을 줄인다.
- watch -> calibrate -> track -> reset 내내 카메라가 멈추지 않는다; 사용자는 재시작을 보지 않는다.
- Explore의 "Now" 블록 (모든 모터와 힘, 고정폭)과 Cal+ / Cal- 프리셋은 2026-11-04에 사용자가 요구한 그대로다.
- 캘리브레이션 뷰어가 전에 안 보이던 세 가지 (PSF 스택, band-pass LUT, self-fit 잔차 nm)를 실시간 재처리로 보여준다.
- 안전 프로파일과 모든 한계가 보인다 (사용자: "사용자가 알아야 한다"), 형식은 손봐야 하지만 (#9).
- STOP과 Acknowledge의 툴팁이 사용자의 말로 무엇을 하는지 적는다.

## 우선 권고

1. **Experiment 페이지를 비워서 연다 (#1)** - 미리 채워진 표와 스크립트가 창에서 유일하게 리그를 예고 없이 움직일 수
   있는 것이다. 예제는 요청할 때만.
2. **스캔 전에 저장 대화상자 하나 (#2)와 페이지에 카메라 시작 버튼 (#5)** - 그러면 Run 페이지가 완성된다: 위에서
   아래로 버튼 다섯, 상단 바에 아무것도 없고, 스캔 뒤에 아무것도 없다.
3. **테스트가 사용자 QSettings를 건드리지 않게 (#3)** - 다음 리그 실행 전에, 아니면 첫 저장 대화상자가 pytest 폴더에서
   열린다.
4. **목업대로의 비상 정지 (#4)** - 빨간 배너와 그 안의 Acknowledge, 단축키, 다른 정지들과 떨어진 STOP.
5. **사용자의 말로 (#9, #10, #12)** - 안전 프로파일은 표로, 라벨에 결정 번호 없이, 이벤트 줄은 문장으로.

## 사용자의 첫 전체 실행 뒤 검수 (같은 날 저녁, 2026-11-05 ~22:30)

사용자의 목록(gui.md "Owner's list after the first full run")을 반영한 뒤 시뮬레이터에서 모든 페이지를 다시 찍어
확인했다. 위 발견 기준으로 바뀐 것:

| # | 상태 | 확인 |
|---|---|---|
| 1, 2, 3, 4, 5, 9, 10, 12 | 오늘 밤 앞서 수정 (gui.md) | 빈 표와 스크립트; 폴더 대화상자 하나; 테스트의 QSettings는 임시 ini; 배너가 있는 EMERGENCY STOP (Shift+Esc); 페이지의 "1. Start the camera"; 프로파일 표; 평범한 제목; 이벤트 문장 |
| 7 | 수정 | "4. Record on" / "* Recording (press to stop)"이 유일한 Record 버튼, Run 페이지에, 상태와 함께 |
| 8 | 수정 | 바는 `1. Setup | 2. Run | 3. Experiment | More...`; Explore, Beads, Calibrate, Save는 More 뒤에만 (번호 없이) |
| 14 | 일부 | 잔차가 자기 플롯을 가짐 (사용자: 한 축에서는 둘 다 읽을 수 없었다); .cal을 읽기 전의 빈 축은 남음 |
| 19 | 수정 | Script guide가 Experiment 페이지로 옮겨졌고 프로그램 안에서 열림 |
| 11, 13, 15, 16, 17, 18, 20-25 | 미해결 | 위와 같음 |
| 신규 | 수정 | Y 라벨은 Force인데 범례는 Magnet (이전 축의 곡선이 남아 있었음): 축이 바뀌면 곡선을 다시 만든다 |
| 신규 | 수정 | 자석 / 힘 곡선이 램프를 계단으로 그림: 플롯이 2 Hz 읽기값을 썼다; 이제 폴러의 10 Hz 읽기값, 즉 run 파일의 값을 쓴다 |
| 신규 | 수정 | 오른쪽 클릭이 pick 제거 위에 pyqtgraph의 View / Export 메뉴를 열었음: 메뉴 끔 |
| 신규 | 수정 | Experiment 표의 버튼 줄이 440 px에서 글자를 잘랐음 ("tart from tabl"): 두 줄로 |
| 신규 | 미해결 | Experiment 페이지의 프로토콜 콤보가 긴 편집기 아래에 있어 스크롤해야 보임: 편집기 위로 옮길 것 |
| 신규 | 미해결 | "4. Record on"은 체크 버튼인데 눌린 모양이 Qt의 옅은 회색: 녹화 중에는 색을 (배너처럼) |
| 신규 | 기록 | 오토포커스 (잃은 비드 재시도, 사용자가 고른 위치의 피에조 클램프)는 아직 없음; 사용자는 있다고 기대함 - 생기면 Run 페이지의 한 단계로 |

## 확인하지 않은 것

리그 백엔드 (리그에서 Connect를 누르지 않음), 1920 x 1080과 리그 자체 화면 크기에서의 창, Camera settings와
Device 패널 (`gui/attrs.py`, `_Panel`), 종료 대화상자, 어두운 테마 렌더링, 실제 비드가 필요한 동작 (실제 .cal을
읽은 캘리브레이션 뷰어는 테스트의 픽스처 cal 파일로만 봤다).
