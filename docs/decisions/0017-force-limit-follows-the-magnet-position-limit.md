# 0017 — The force limit follows the magnet position limit

**Decided:** 2026-10-25 (owner, in chat)

Owner: "자석 힘 최대값은 모터 리밋에 종속되어야함. Force calibration 때 마다 달라지기도 하는데, magnetic force가 강해서
생기는 문제가 아니라 자석이 물리적으로 스테이지와 부딪히는게 문제임. 그러니 force calibration이 어떻게 되든, bead를
무엇을 쓰던 magnet이 부딪히지 않게 하는 모터 리밋을 따라야함. 여기서 force limit이 생김."

## Decision
1. **There is no separate maximum force in the rig safety profile.** The danger is the magnet physically hitting the
   stage, not a large magnetic force. The only safety limit is the magnet POSITION limit (today 0..39 mm, set at the
   rig so the magnet cannot touch the stage; 0 mm = ceiling, farthest from the sample).
2. **The force limit is derived:** for the force table in use (it changes with each force calibration and with the
   bead type), the reachable force range is the force at the position-limit ends. A force request is converted to a
   position through the table and checked against the position limit; a force the table only reaches outside the
   position limit is refused, with both numbers in the message.
3. **Force and magnet position are one-to-one** (owner 2026-10-25: "우선은, Force vs magnet은 1:1 대응이기는 함"), so
   the force table is inverted directly and a table whose values are not strictly monotonic is refused (as
   implemented in c0ecefc). If a real calibration ever has a flat or noisy part, this is revisited (smooth first).
4. This fits 0010 (magnet position is the raw record, force is derived and recomputable). The `magnet_force_pN` entry
   leaves the profile (or becomes a derived, non-editable entry); changing it is not a safety-profile change, changing
   the position limit is.
