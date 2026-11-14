# 프로토콜 스크립트: 글이 어떻게 모터 움직임이 되는가

소유자 2026-11-05: "script 문법에 대한 자료가 필요함 (어떻게 거의 자연어를 실제 모터 모션으로 구동하는지)". 이 문서는
사용자용 안내이고, 모든 키와 범위가 있는 전체 문법은 [format/grammar.md](../format/grammar.md)입니다.
영어 원문: [protocol-scripts.md](protocol-scripts.md).

## 1. 한 줄이 한 동작, 위에서 아래로

프로토콜은 한 줄에 한 문장인 평문이고 위에서 아래로 실행됩니다. AI가 해석하는 것이 아닙니다. 프로그램이 고정된 문법으로
줄을 읽고(`src/mtpy/protocol/grammar.py`), 모든 값을 검사한 뒤(`check.py`), 차례로 실행합니다(`engine.py`).
Experiment 패널의 표(행 = 파라미터, 열 = 반복; 랩뷰 표와 같음)는 같은 줄들로 변환되고, 아래 글상자에 그 줄이 보입니다.

```
grammar 0.1
protocol "example"
hold f=1 t=2            # 1 pN으로 2초
ramp from=1 to=5 t=5    # 1 -> 5 pN을 5초에 걸쳐
mark "high force"       # 데이터에 글 이벤트
hold f=5 t=2
zero t=1                # 자석을 0 mm(맨 위)로, 1초
end protocol
```

단위는 키마다 정해져 있고 값에 쓰지 않습니다. `f`, `from`, `to`는 pN(`hold` / `ramp`), `t`는 초, 회전은 turn,
`mm`는 mm, `um`은 um, `stage`의 `x` / `y`는 um. `7pN`처럼 쓰면 오류이므로 단위가 조용히 섞이는 일이 없습니다.

## 2. 각 문장이 리그에서 하는 일

| 줄 | 프로그램이 하는 일 |
|---|---|
| `hold f=F t=T` | 힘 보정(M270 v3, Setup에서 잡은 touch position 기준)으로 F pN에 해당하는 자석 위치를 구하고, 모션 게이트를 거쳐 자석을 그 위치로 보낸 뒤 T초 기다림 |
| `ramp from=A to=B t=T` | 자석을 A의 위치로 보낸 뒤, B의 위치까지 T초가 걸리는 속도로 이동(`t=` 대신 `speed=` mm/s 또는 `rate=` pN/s도 가능. `rate=`는 진짜 loading rate: 한 번의 이동 중에 0.1초마다 읽은 위치에서 보정 곡선의 기울기로 속도를 다시 정하므로(rate / 기울기) touch 쪽으로 갈수록 빨라지고 멀어질수록 느려짐. 기울기가 너무 작아 rate를 못 지키는 곳에서는 프로파일 최대 속도로 묶이고 `coerced`로 기록). 프로파일의 자석 속도 한계를 넘는 속도는 한계로 낮추고 `coerced` 이벤트로 기록 |
| `move mm=X t=T` | 자석을 힘과 무관하게 X mm로, 그 뒤 T초 |
| `zero t=T` | 자석을 0 mm(맨 위, 힘 없음)로, T초. 추적의 영점은 잡지 않음 |
| `rotate from=A to=B f=F t=T` | 힘 F로 두고, 로터를 원점 기준 A turn으로 보낸 뒤 B turn까지 (B-A)/T turn/s로 회전. `t=` 대신 `speed=` turn/s 또는 `spd=`(로터의 SPD 설정값, turn/s = SPD x 10 / 500)도 가능 |
| `loading magnet` / `loading force` | 머리말 줄(`protocol` 다음): 램프를 자석 속도(`speed=`)로 썼는지 힘 loading rate(`rate=`)로 썼는지. 반대로 쓴 램프는 Check에서 경고. 표는 Loading 선택대로 이 줄을 씀 |
| `focus um=X` | 초점을 프로토콜 시작 위치에서 X um 떨어진 곳으로 (직전 단계 기준이 아님); `t=T`를 붙이면 이동 후 T초 대기; `speed=V` (um/s, 2026-11-14)를 붙이면 그 이동만 피에조를 그 속도로 천천히 움직임 (램프): 피에조를 열 때의 속도보다 빠르면 그 속도로 낮추고(`coerced`), 아주 느린 값은 컨트롤러가 반올림하며, 이동 뒤 원래 속도로 되돌림. 위치는 프레임마다 기록됨 (`/mt/focus_um`, 10 Hz로 읽음) |
| `stage x=X y=Y` | 샘플 스테이지를 프로토콜 시작 위치에서 (X, Y) um 떨어진 곳으로 (직전 단계 기준이 아님; 각각 ±1000 이내); `t=T`를 붙이면 이동 후 대기. 이동마다 리드백이 run 파일의 `act` 이벤트(`stage_xy_mm`, mm)로 남음; 스테이지 위치는 프레임마다 기록됨 (`/mt/stage_x_mm`, `/mt/stage_y_mm`, 5 Hz로 읽은 값) |
| `autofocus on` / `autofocus off` | 오토포커스 켜기 / 끄기 (값 없음: 기준 비드와 목표(LUT의 %)는 프로그램에서 설정). `focus` 단계 앞에는 `autofocus off`를 쓸 것: 켜져 있으면 오토포커스가 초점을 되돌림 (경고 이벤트가 남음) |
| `record on` / `record off` / `record t=T` | 런 파일에 기록을 켬 / 끔 / T초 동안 켬 |
| `mark "글"` | 런 파일에 글 이벤트 |
| `wait t=T` | T초, 아무것도 움직이지 않음 |
| `loop n=N ... end` | 안의 줄들을 N번 |
| `end protocol` | 끝(자석은 그 자리에 둠) |

자석 위치 한계 안에서 낼 수 없는 힘은 낼 수 있는 가장 가까운 힘으로 바꾸고 `coerced`로 기록합니다(결정 0018).
시간 0도 됩니다(`hold f=5 t=0`: 그냥 거기로 가기만).

## 3. Start 전에 Check

**Check**는 아무것도 움직이지 않고 세 단계를 검사해서 문제를 줄 번호와 함께 모두 보여줍니다.
1. 문법: 모르는 단어, 빠진 키, 키의 고정 범위를 벗어난 값;
2. API와 리그 안전 프로파일(Setup에 파일과 모든 한계가 보임): 프로파일이 거부하는 힘·위치·속도·회전수, 낮춰질 속도;
3. 리그 상태: 장치 연결 여부, 힘 보정 준비(touch position) 여부.

**Start**는 먼저 Check를 돌리고 오류가 하나라도 있으면 거부합니다. 프로토콜이 도는 중의 Start는 그것을 끝내고 새 것을
돌립니다. 위 막대의 배지가 `PROTOCOL running (이름)`을 보여줍니다.

## 4. 도는 동안

- **Pause / Resume**: 대기 시간이 멈춤. 진행 중인 이동은 끝까지 감.
- **Stop** (Experiment): 현재 이동이 그 자리에서 멈춘 뒤 프로토콜이 끝남. 자석은 그대로.
- **STOP** (위 막대, 빨강): 비상 정지. 모든 모터가 멈추고 Acknowledge 전까지 모든 이동이 거부됨.
- **Apply edits**: 바뀐 값은 다음 문장 경계에서 적용됨. 도는 중에 문장을 추가·삭제·순서 변경하는 것은 거부됨
  (Stop 후 새 글로 Start).
- 모든 문장과 이동은 줄 번호와 함께 런 파일의 이벤트(`events/protocol`, `events/protocol_step`)로 남으므로, 나중에
  trace를 프로토콜과 맞춰 읽을 수 있습니다.

## 5. 표

열 하나가 한 단계: Force (pN), Wait (s), Loading, Rotor (degree), Rotor speed (SPD), Focus (um). **Focus**는 프로토콜 시작 위치 기준의 초점 오프셋(`focus um=`과 같음)이며, 값이 앞 열과 다르면 힘 변경 뒤, Wait 앞에 초점을 옮깁니다. 표에는 `stage`, `autofocus`, `record` 행이 없으므로 이들은 스크립트에 직접 씁니다. **Loading**(표 위의 선택)은
Motor (mm/s) = LabVIEW 실험에서 쓰던 자석 loading rate, 또는 Force rate (pN/s) = 힘 loading rate이며 표 전체에
하나만 적용됩니다. 한 열은 그 loading 값으로 그 힘까지 `ramp`(`speed=` 또는 `rate=`; 0이면 `hold`), 그 각도만큼
SPD로 `rotate`(turn/s = SPD x 10 / 500), 그 뒤 Wait만큼 `hold`로 변환됩니다. Start from table은 변환하고 바로
시작합니다.

## 6. 예: 피에조와 스테이지 (2026-11-12 / 13)

**힘을 고정하고 피에조 계단** (bead calibration 정밀도 측정). `focus um=`은 프로토콜 시작 위치 기준이고, 초점 위치는
프레임마다 run 파일의 `/mt/focus_um`에 기록됩니다. 피에조를 움직이면 기준 비드와 측정 비드의 z가 같이 변하므로,
비드별 z 변화량을 피에조 이동량과 비교합니다.

```
grammar 0.1
protocol "piezo steps at 10 pN"
loading force
autofocus off          # 켜 두면 오토포커스가 초점을 되돌림
record on
hold f=10 t=30
focus um=0.1 t=10      # 시작 위치 + 100 nm, 그 뒤 10 s
focus um=0.2 t=10
focus um=0.3 t=10
focus um=0 t=10        # 시작 위치로 복귀
record off
autofocus on
end protocol
```

`autofocus on`은 Run 페이지에서 정한 목표(LUT의 %, 기본 30)와 추적 중인 기준 비드를 씁니다. 기준 비드가 없으면 그
줄에서 프로토콜이 실패로 끝납니다.

**스테이지 xy 이동** (예: 기준 비드를 추적하면서 알려진 거리만큼 움직여 픽셀 크기 측정). `stage x= y=`도 프로토콜
시작 위치 기준이며 각각 ±1000 um 이내입니다. 이동마다 리드백이 `act` 이벤트(`stage_xy_mm`, mm)로 남습니다. 비드가
추적 ROI 밖으로 나가지 않도록 수 um 이내로 움직입니다.

```
grammar 0.1
protocol "pixel size"
record on
wait t=5
stage x=5 y=0 t=5      # 시작 위치에서 x로 5 um, 그 뒤 5 s
stage x=0 y=0 t=5
stage x=0 y=5 t=5
stage x=0 y=0 t=5
record off
end protocol
```
