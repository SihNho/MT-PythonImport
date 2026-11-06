Run 창 안에 Explore 항목이 같이 들어있으면 좋겠음.

그리고 bead calibration 시작하면 브라우저가 뜨는데, 시작 디렉토리가 'G:\Data\SiHyeong\Dropbox\Data' 이면 좋겠고.

그 다음, calibration 진행 방향이 이상함. -z 방향으로 캘리브레이션 하는데, LabVIEW에서는 +z 방향으로 bead calibration 프로파일 쌓았음. 그리고 동시에 z-position 놓치지 않았고. 그리고 내가 잘못 알고 있었네... bead가 focus 위에 있었음.
그나저나 내가 방금 체크했는데, piezostage 부호가 거꾸로 되어있음. -가 음수가 아닌 플러스.
Manual하게 렌즈를 위로 올려서 focus를 bead 위로 올림. 그러면 bead 위치가 올라갈수록 (즉, piezo 위치가 높아질수록) bead pattern이 작아져야 하는데, 반대임.
추가로, objective와 coverslip 사이에 lens oil 사용중인데, piezo stage를 위로 올리면 coverslip과 lens 사이의 거리가 멀어지면서 lens-oil-coverslip 접착 면적이 줄어들어야 함. 그런데 역으로 접착 면적이 커짐.
예전에 고장 이후 수리를 맡겼는데 그 때 배선 관련해서 에러가 있었나봄.

---
> **답 (2026-11-06)**
>
> **1. Run 창 안의 Explore** — 넣었음. Run 페이지 맨 아래에 "Explore: move by hand" 그룹으로 들어감(자석 위치·속도·프리셋, 힘, 로터, focus, 노출/게인). More... 뒤의 Explore 페이지는 없앰(Beads, Calibrate, Save만 남음).
>
> **2. 캘리브레이션 폴더 브라우저 시작 위치** — `G:\Data\SiHyeong\Dropbox\Data`로 바꿈(폴더가 있을 때; 없으면 전처럼). Calibrate 페이지의 "Write .cal to"도 거기서 시작.
>
> **3. 스캔 방향·piezo 부호** — 스캔 방향을 Calibrate 페이지의 선택으로 뺐음(기억됨): **"up (+z per slice, LabVIEW's)"가 기본**, "down"도 선택 가능. 선택은 z 스캔에 전달되고 calibration 이벤트에 기록되며, autofocus 부호도 그 선택을 따름(코드 수정 없이 리그에서 바꿀 수 있음).
>
> 판단 근거는 하나뿐임: **force ramp에서 z가 힘과 함께 커지는가.** 오늘 낮의 +z 스캔 데이터는 z가 힘과 함께 **작아졌고**(그래서 Request1에서 down으로 바꿨던 것), −z 스캔으로는 아직 ramp를 안 봤음. 그러니 지금 상태(up 기본)로 다시 스캔해서 ramp를 한 번 돌려보고, z가 또 작아지면 Calibrate에서 "down"으로 바꾸면 됨. 둘 중 하나는 반드시 맞음.
>
> piezo 부호가 반대라는 관찰(+ 명령에 렌즈가 내려감, 오일 접촉면 커짐)은 하드웨어/컨트롤러 설정 문제라 프로그램이 바꿀 수 없음. ASI Tiger는 축 방향을 컨트롤러 설정으로 뒤집을 수 있으니(매뉴얼의 axis polarity 항목) 수리 뒤 설정이 바뀌었는지 ASI 설정에서 확인하는 게 맞음. 프로그램 쪽은 어느 쪽이든 위 ramp 검사로 방향이 정해지고, 리밋(SL/SU Z)은 컨트롤러 값을 읽어 쓰므로 안전에는 영향 없음.
>
> "LabVIEW는 z-position을 놓치지 않았다"는 말이 −z 스캔 때 비드를 잃었다는 뜻이면, 시작 focus를 비드 반대편에 둔 채 스캔한 탓일 가능성이 큼(up 스캔이면 비드 아래에서 시작, down이면 위에서 시작). 다음 실행 때 어느 슬라이스에서 잃었는지 로그(calibration warning 줄)를 보면 확인됨.
>
> 테스트: 시뮬레이터에서 Explore 위치, 스캔 방향 전달·기억, 다이얼로그 시작 폴더, autofocus 부호 통과. 커밋은 아직.
>
> **덧붙임 — 테스트하다 찾은 버그**: 프로그램 설정(QSettings)이 레지스트리에 저장되고 있어서, 테스트가 임시 ini로 돌리려던 게 안 먹히고 테스트마다 실제 설정(data_dir가 pytest 임시 폴더로, scan_dir)을 덮어쓰고 있었음. 이제 설정은 `%APPDATA%\KimLab\MT Tracker.ini`에 저장됨. 레지스트리 `HKCU\Software\KimLab\MT Tracker`에 남은 값은 더 이상 안 쓰니 지워도 됨. 기억해 둔 데이터 폴더는 한 번 초기화됨.
