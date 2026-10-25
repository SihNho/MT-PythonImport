# 0018 — Force inputs are coerced into the reachable range; the motor value is always coerced

**Decided:** 2026-10-25 (owner, in chat). Refines 0017 item 2 (which said "refused").

Owner:
- "힘 보정 테이블은, 범위를 찾는 게 아니라 equation에 대응해서 값을 찾는 방식일텐데. 이거는 사실 프로그램 병목을 줄이기
  위해 한 방법이고, 이제는 랩뷰가 아니라 파이썬이니 이 부분에서는 자유로울 것 같음. Acquisition, motor control, image
  analysis와는 별개의 루프로 돌면 문제가 없잖아. 그러면 실시간 계산으로 하면 될 것 같은데."
- "다만, 여기에 force 값을 넣었을 때 magnet limit 밖이면 limit 값 내부로 보정해줘야겠지. (ex. 60 pN을 했더니 magnet
  보정값에서 벗어남 --> 가장 가까운 50 pN으로 한다)" (numbers illustrative only)
- "그리고 인풋에 넣어준 숫자가 리밋때문에 작게 나오면 바로 숫자 고쳐줘야함. 그게 LabVIEW 프로그램에서는 돌아가고 있을거야"
- "프로토콜에서 한계 밖의 힘이 셋팅되면 자동으로 한계 안으로 넣으면서 수정해줘야함. 알람을 띄울 필요는 없겠고, 유저가
  타이핑 하는 칸에도, 그리고 유저가 타이핑 하는 값이 반영된 칸에도, 그리고 실제로 모터에 전달되는 값도 수정 해주면 될듯."
- "그리고 안전장치를 하나 더 써서: force 값이 어떻게 나오던지 모터에 전달되는 값은 coerce 잡히도록"

## Decision
1. **Force <-> position by the calibration equation, computed live** (not a precomputed table lookup), in its own
   thread, apart from acquisition, motor control and image analysis. The equation is the one in the LabVIEW program
   (`Magnet2Force v3_for M270.vi`, being read). Refines 0010 item 2 (table as default).
2. **A force outside the reachable range is coerced, not refused:** it becomes the nearest force reachable inside the
   magnet position limit (0017). This holds for a typed force and for a force set in a protocol.
3. **No alarm.** The corrected value is written back everywhere it appears: the field the user typed in, the field
   that shows the applied value, and the value sent to the motor. (The data file records the request, the corrected
   value and the reason as an event, so the record stays complete; this is a log entry, not an alarm.)
4. **Second safeguard:** whatever the force computation gives, the position sent to the magnet motor is coerced into
   the magnet position limit at the last step before sending. The controller's own TMN / TMX limits stay set as the
   hardware layer below that.
6. **No second bound from the touch position** (owner 2026-10-25, first "그 경우 상한이 갱신되어야함", then: "그 위치 상한
   39 mm는 리그에 변화가 생길 때 마다 계속 바뀌어야 하는 함수임. 그러니 괜히 이중으로 묶을 필요는 없는듯."): the
   upper bound is the rig safety profile's magnet position limit only; when the rig changes, that limit is updated by a
   new profile version (re-commissioning, 0015 item 5). The touch position is not used as an extra bound.
5. **Direct position commands are coerced too** (owner 2026-10-25: "가장 가까운 한계값으로 맞춰"): a magnet position
   outside the position limit becomes the nearest limit value, written back the same way (no alarm, event logged).
