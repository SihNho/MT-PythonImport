# 0027 — The rotor's limit is the controller's own soft-limit registers; the program writes none

**Decided:** 2026-10-30 (owner, in chat): "로터도 하드위어 리밋 따라가자", then, on the question of who sets the values
in the controller: "내가 알기로는 reading 할 때 limit이 있을건데? stack overflow 관련해서" and "그걸 리밋으로 두면 될듯".

## Decision
1. **The rotor envelope is the Autonics PMC-2HS's own soft limits, read at every open** (`IXR X7B` minus, `IXR X7A`
   plus, pulses, absolute in the controller's counter frame; `IHR XE4` operation mode 2 is read with them). The driver
   `src/mtpy/devices/autonics.py` cuts the session window to them, refuses to open when the rotor already sits outside
   them, and reports them in `limits()` (`controller_soft_limits_pulses`, `controller_soft_limits_in_use`). Readback of
   the position after every move stays the second stage (decision 0025); a reading outside the window sends `STO X`.
2. **The values are the ones the controller holds today: the factory defaults -8 388 608 .. +8 388 607 pulses**, read
   on the rig 2026-10-30 (`tools/rotor_limits_probe.py`, read-only). They are the 24-bit position counter's own range
   (the limit the owner meant by "reading 할 때 limit"), so the limit is the point beyond which the controller could not
   report a position at all. In turns (500 pulses per turn): about -16 777 .. +16 777.
3. **Nothing is written to the controller.** The program never sends `IHS` / `IXS` (EEPROM parameter writes); the
   earlier option "program writes once" is dropped. If the owner later sets tighter soft limits on the controller's own
   panel, the driver picks them up at the next open with no code change.
4. **The safety profile follows the controller, not the other way round.** `rotor_turns` becomes an absolute window
   (`relative_to: None`) equal to the controller's limits in turns, written as a new profile version through the admin
   API by `tools/rotor_limits_probe.py --adopt` after a fresh readback on the rig. Until that runs, the current
   profile v7 (+-5 turns from the session start) is the tighter of the two and stays in force; the driver always takes
   the intersection. The adoption needs the rig outside an experiment and the owner's go; it has not run yet.

## Why this and not a fixed +-N turns
- The rotor has no mechanical end stop and no home switch the program trusts (`HOM` ignores the soft limit, manual
  p. 70); a turn count relative to an arbitrary start was a guess. The counter range is a fact of the controller and
  cannot be exceeded by a correct reading.
- A limit the controller enforces itself (decelerate to stop, `ERD` bits 9 / 8) protects the rig even when the
  program is not the one moving it.

## Consequences
- The rotor's protection against a runaway inside the counter range is the readback stage: `moving()` sends `STO X`
  when the position leaves the window by more than 25 pulses, and the e-stop stops every device.
- `docs/manuals/rotor-autonics-pmc2hs.md` open question 5 is closed by this decision; question 4 (where the rotor is
  left at the end of a job) stays open.
- Tests: `tests/test_gate.py::test_rotor_follows_the_controller_soft_limits` and
  `test_rotor_absolute_window_from_the_controller` on the fake controller.
