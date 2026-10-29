# 0025 — The project's motion gate is approved; the focus z window follows the controller's own limits

**Decided:** 2026-10-30 (owner, in chat): "승인함. Focus Z lock은 하드웨어 리밋 따라갈것."

## Decision
1. [design/motion-gate.md](../design/motion-gate.md) is approved as this project's motion gate (RULES.md 3): the
   real PI / ASI / Autonics drivers (`src/mtpy/devices/pi.py`, `asi.py`, `autonics.py`, backend `real-motors`) may
   send to the motors, under the rig lock, with the four stated differences from V6's gate (port open for the
   session, rotor `STO X` for the emergency stop, numbers from the safety profile, no token file). V6
   `tools/motor_gate.py` is no longer the only path; it remains V6's own gate.
2. **Focus z: the window is the ASI controller's own SL/SU Z limits** (as decision 0021 already does for V6's gate):
   the driver reads them at open, never writes them, and refuses a target outside them. The safety profile's
   `focus_z_um` entry is set from those read values (absolute um, `relative_to` null) at the first rig session and
   marked verified by that readback, so the API's check and the controller agree.
3. The rotor stays as it is: `rotor_turns` +-5 turns from the session start is enforced by the driver, and the
   profile entry remains unverified (the API refuses rotor moves) until the owner verifies it on the rig.
