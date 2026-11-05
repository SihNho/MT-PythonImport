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
`mm`는 mm, `um`은 um. `7pN`처럼 쓰면 오류이므로 단위가 조용히 섞이는 일이 없습니다.

## 2. 각 문장이 리그에서 하는 일

| 줄 | 프로그램이 하는 일 |
|---|---|
| `hold f=F t=T` | 힘 보정(M270 v3, Setup에서 잡은 touch position 기준)으로 F pN에 해당하는 자석 위치를 구하고, 모션 게이트를 거쳐 자석을 그 위치로 보낸 뒤 T초 기다림 |
| `ramp from=A to=B t=T` | 자석을 A의 위치로 보낸 뒤, B의 위치까지 T초가 걸리는 속도로 이동(`t=` 대신 `speed=` mm/s도 가능). 프로파일의 자석 속도 한계를 넘는 속도는 한계로 낮추고 `coerced` 이벤트로 기록 |
| `move mm=X t=T` | 자석을 힘과 무관하게 X mm로, 그 뒤 T초 |
| `zero t=T` | 자석을 0 mm(맨 위, 힘 없음)로, T초. 추적의 영점은 잡지 않음 |
| `rotate from=A to=B f=F t=T` | 힘 F로 두고, 로터를 원점 기준 A turn으로 보낸 뒤 B turn까지 (B-A)/T turn/s로 회전 |
| `focus um=X` | 초점을 실행 시작점에서 X um만큼 |
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

열 하나가 한 단계: Force (pN), Wait (s), Motor (mm/s), Rotor (degree), Rotor speed (SPD). 한 열은 모터 속도로 그
힘까지 `ramp`(속도 0이면 `hold`), 그 각도만큼 SPD로 `rotate`(turn/s = SPD x 10 / 500), 그 뒤 Wait만큼 `hold`로
변환됩니다. Start from table은 변환하고 바로 시작합니다.
