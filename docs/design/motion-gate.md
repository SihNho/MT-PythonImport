# The motion gate of this project (phase 7) - for the owner's approval

RULES.md section 3: every motor command goes through a gate that checks the rig lock, enforces the safe-motion
envelope in code, and sets the controller limits at the start of a job and releases them at the end, verified by
readback after a real PI reference move. Until the owner approves this gate, mtpy sends nothing to a motor; V6
`tools/motor_gate.py` stays the only path. This page is the gate, in one place, so it can be approved or refused.

## What the gate is

The gate is the three real motor drivers (`src/mtpy/devices/pi.py`, `asi.py`, `autonics.py`) plus the checks they
share (`src/mtpy/devices/gate.py`). There is no raw-command path: a driver can only write the handful of command
strings it builds itself, so the command-class default-deny of V6 (home, zero, save, program, jog, EEPROM ... refused)
holds by construction. The API above (`mtpy.api.magnet / stage / rotor / focus`) still checks every target against
the rig safety profile before the driver is called (decision 0015 item 5), so a move is refused twice: by the profile
in the API and by the controller limits in the driver.

| | PI C-863.11 (magnet, COM3) | ASI Tiger X/Y (stage) and Z (focus), COM4 | Autonics PMC-2HS (rotor, COM5) |
|---|---|---|---|
| lock | `RIGLOCK_TOKEN` + `riglock.permitted(token, {assembled, disassembled})` at open and before every send (same as the JAI camera, phase 6) | same | same |
| session start (= `open()`) | `SPA 1 0x15 39`, `SPA 1 0x30 0` (RAM, never `WPA`), read back `TMN?/TMX?`; `SVO 1 1`, `RON 1 1`, `FNL 1` (reference to the negative limit switch), wait `FRF? 1` and `ONT? 1`, `POS?` = 0 within 0.001; verify `MOV 1 2` then `MOV 1 0`, each within 0.05 mm with `ERR? 0`; limits re-read. Up to 3 attempts, else the open fails | read `W X`, `W Y`; write `SL/SU X Y` = position +- 2.0 mm (absolute mm, persistent in the controller), read back within 0.001. Z: read `SL Z?`, `SU Z?`, `W Z` and record that window; nothing is written for Z (decision 0021) | one dummy `POS` (first-read timeout), then `POS`; window = start +- 2500 pulses (5 turns). Nothing written |
| every move | in the same port session: `TMN?/TMX?` must still read 0 / 39, `FRF?` 1, `SVO?` 1 (else `SVO 1 1` once), target inside 0..39, then ONE `MOV 1 <mm>`; `ERR?` right after must be 0 | `SL/SU` must still read the session values (Z: the recorded window), target inside, then ONE `M X=<int>` / `M Y=<int>` / `M Z=<int>` (0.1 um units, absolute). Z never shares a command with X/Y | `POS` twice identical (stationary), target = PAB value inside the window, `SPD <= 100`, then ONE `PAB <int>` (X only) |
| watchdog | the API's arrival wait reads `POS?`; outside 0..39 by more than 0.5 mm -> `HLT 1` | `W` outside SL/SU by more than 0.05 mm -> `\` (halt) | `POS` outside the window by more than 25 pulses -> `STO X` |
| `stop()` (emergency stop, any thread) | `HLT 1` | `\` | `STO X` |
| session end (= `close()`) | `MOV 1 0` with the limits still set, `POS?` within 0.01 of 0 - not verified: nothing is released, `close()` raises, the lock holder keeps the lock; then `SPA` 0 / 52 (the release values), read back | `SL/SU X Y` = -500 / +500, read back; `SL/SU Z` re-read and compared with the start (nothing to release) | nothing to release |
| numbers from | the rig safety profile (`config/safety_profile.json` v5: `magnet_position_mm` 0..39 verified, `stage_x/y_mm` +-2.0 relative verified, `rotor_turns` +-5 unverified, `focus_z_um` unset). An unverified or unset entry: the driver still sets what it can, the API refuses the moves | | |

Differences from V6's gate, stated so they can be judged:
1. **In-process, one port open per device for the whole session** (V6 opens the port per command from PowerShell).
   The per-command limit readback is kept (it is what proves the controller carries the limits at transmit time);
   the port stays open so a position read costs 3 ms, not 300 ms. No serial call is on the frame path (rule 6): the
   drivers run on the device service threads; the motor poller reads at 20 Hz on its own thread.
2. **`stop()` is allowed for the rotor** (`STO X`): V6 refuses it by default-deny because its send path only knows
   bounded moves; here the emergency stop must reach every axis (decision 0007). A stop needs no envelope.
3. **The limits come from the safety profile, not from `motor_limits.json`**: one register (decision 0020). The
   release values (PI 0..52, ASI +-500) are controller geometry and stay constants in the drivers.
4. **No token file**: the one-shot token protected V6's PowerShell senders from being run by hand; here the only
   caller of a driver is the device service, and the drivers have no raw send.

## Tests before the rig
`tests/test_gate.py` runs the three drivers against fake controllers (`tests/fake_controllers.py`) that answer like
the real ones (GCS `1=<v>` replies and `ERR 7` outside TMX, Tiger `:A` replies and the SL/SU clamp, PMC-2HS 8-hex-digit
two's-complement `POS`): session start writes and reads back the limits; a target outside the window is refused
before anything is written; a controller whose limits no longer match refuses the move; an unreferenced PI refuses;
the session end homes the magnet first and releases only after; a failed home releases nothing; no `RIGLOCK_TOKEN`
-> `PermissionError` before any port is opened.

## On the rig (after approval)
1. Under V6 `tools/rig_session.py --no-motor-session` (lock only; this gate sets and releases the limits itself).
2. Magnet first: open (reference + verify), `api.magnet.move_to(5)`, `move_to(39)`, a request of 40 mm (coerced to 39
   by decision 0018; the driver's own check and the controller's `ERR 7` are exercised by the independent checker
   with a direct 40 mm target), close (home, release, readback).
3. Then the stage (+-0.5 mm steps, a target beyond +-2 mm refused), the rotor (1 turn each way, 6 turns refused;
   the profile's `rotor_turns` entry must be verified by the owner before the API allows it), the focus (window =
   the controller's own SL/SU Z; the profile's `focus_z_um` must be set).
4. The independent motor-limit check (`motor-limit-checker`): per device, per call site, PASS / FAIL, logs kept in
   `docs/results/`.
