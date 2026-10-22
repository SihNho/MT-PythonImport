# 0012 — Automation: protocol-driven partial automation first; full automation later

**Decided:** 2026-10-22 (owner, chat)

Owner: "우선 반드시 필요한 것은 부분 자동화: 프로토콜을 정하고 그에 맞춰 움직이도록 (이건 지금도 부분적으로 루프를 통해
돌아가는 부분). 완전 자동화: 목표이기는 하나 당장 써야하는 급박한 목표는 아님."

## Decision
1. **Required now: partial automation.** The user defines a protocol and the application executes it: an ordered list
   of steps (magnet position or force, hold time, rotation, recording) with repeats. It replaces LabVIEW's
   `CycleSchedule` table and 3-state clamping loop.
2. **Full automation is a goal, not urgent.** The protocol format is designed from the start to allow **conditional
   steps** (e.g. "continue when extension > X", "skip bead if screening fails") so that full automation (screening ->
   experiment -> next field) is an extension, not a rewrite. The first version need not use them.
3. Every protocol step passes the same safety layer as a manual action (0001, 0007), and the user can stop at any time.

## Consequences
- Screening protocols (U10) and experiment protocols share one format and one engine.
