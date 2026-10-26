# 0020 — Rig core parameters live in one register; the program checks and controls them together

**Decided:** 2026-10-26 (owner, in chat)

Owner: "우선은 1.0 mm로 두자. 이에 관해서도 인제스트 하고, 리그 핵심 파라미터 일환으로 둬야할듯. 리그 핵심 파라미터들은 따로
관리해서 추후 프로그램 통제할 때 한번에 확인 및 통제 가능하게 모아둬야할듯"

## Decision
1. **The PI stall threshold (Maximum Position Error, parameter 0x8) stays 1.0 mm.** Measured normal lag at 15 mm/s is
   about 0.05 mm (1/20 of it), so normal moves never trip it; it remains the extinguisher of 0019.
2. **One register of rig core parameters** ([docs/rig/core-parameters.md](../rig/core-parameters.md)): every value
   that sets how the rig moves, stops, sees or converts numbers, with its value, where it takes effect, who may change
   it, how and when it was verified, and its source. The rig safety profile (0015) is the part of it that the program
   enforces; the register also holds controller settings we only read (stall threshold, accelerations, travel
   geometry), presets and calibrations.
3. **Later (program control):** a machine-readable form of the register; at start-up the program reads the devices'
   values, compares them with the register and shows any difference before anything moves; one screen shows and
   controls all of them; changes to safety-relevant entries go through the protected admin path (0015 item 5).
