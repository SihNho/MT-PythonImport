# Phase 7 first rig run: the real motors through the API and the project's motion gate (2026-10-30)

Owner's approval in chat (decision [0025](../decisions/0025-motion-gate-approved.md), the words are quoted there).
Rig state `assembled`, no experiment, sample mounted (bench use). Both runs inside V6
`tools/rig_session.py --no-motor-session` (lock holder `V6-chat`; the gate sets and releases the controller limits
itself). Script `tools/phase7_motors.py`; logs `bench_out/phase7/rig_session_run{1,2}.log` (local, git-ignored).

## What the controllers are (read through the drivers)

| device | identity | at open |
|---|---|---|
| magnet | PI C-863.11 firmware 1.3.0.7, COM3 | TMN / TMX written 0 / 39, FNL reference, verify 2 -> 0 mm; speed 15 mm/s |
| stage | ASI Tiger `USB-9.2m`, COM4 | position (-1.4382, -3.6446) mm; SL / SU = position +- 2.0 mm written and read back |
| focus | ASI Tiger Z, COM4 (shared) | controller SL / SU Z = **-0.075 / +0.075 mm** (read, never written); Z = 0 |
| rotor | Autonics PMC-2HS `VER 20081001`, COM5 | POS 100 000 pulses = 200.0 turns; window 97 500..102 500 (+-5 turns) |

## Run 2 (08:38, 31 steps, 0 failed)

| step | result |
|---|---|
| magnet 5 mm, 39 mm, 0 mm through the API | read back 5.00015, 39.0002, -0.00015 mm (2.5 s for 34 mm at 15 mm/s) |
| magnet 40 mm requested | API coerced to 39 (0018), read back 39.00015 |
| magnet driver-direct 40 mm and -1 mm (gate alone) | refused before anything was written: `PI ERR 7: target ... outside the soft limits TMN/TMX (0, 39)` |
| stage +0.5 mm x, -0.5 mm y, back | read back within 0.2 um of the request; 0.4-0.5 s per move |
| stage +3 mm x through the API | refused by profile v6: `outside the allowed range [-3.4382, 0.5618] mm` |
| stage driver-direct +3 mm x (gate alone) | refused: `ASI target X=15618 outside the controller window -34382..5618` |
| focus driver-direct +1 um and back | read back 1.0 / 0.0 um |
| focus driver-direct beyond SU Z (gate alone) | refused: `Z target 760.0 outside the controller window -750..750` |
| **profile v6** (written in run 1): `focus_z_um` = -75..+75 um absolute, verified by that readback | then +1 um and back through the API |
| rotor +0.5 turn through the API | refused: `rotor_turns ... not verified` (the owner has not verified it; unchanged) |
| rotor driver-direct +0.5 turn and back (gate alone) | 200.0 -> 200.5 -> 200.0 turns, 1.1 s each |
| rotor driver-direct +6 turns (gate alone) | refused: `target 103000 pulses outside the session window 97500..102500` |
| disconnect | magnet homed to 0 mm (verified), PI limits released, ASI limits released, COM4 closed |
| independent readback on fresh ports after the release | PI `TMN 0 / TMX 52 / POS 0 / ERR 0`; ASI `SL/SU +-500`, `SL/SU Z -0.075 / 0.075` unchanged, X/Y within 0.2 um of the start, Z 0 |

The rig is back at its initial condition; rig_session: no LabVIEW was running, lock released.

## Run 1 (08:13) and what it fixed
- Every magnet move was refused with `PI axis not referenced (FRF? 0)`: the driver re-WROTE the limits (`SPA`) after
  the reference move, and an SPA write un-references the axis (V6 found the same on 2026-09-18). Fixed: after the
  reference the limits are only read back.
- The shared COM4 line was never closed (the stage and the focus each dropped their reference); the independent
  readback could not open COM4. Fixed: the port closes with the last of the two.
- `api.devices.disconnect()` swallowed a device's close error; with real motors a failed close is a failed cleanup
  (RULES.md 2.5). Fixed: it closes everything, then raises DeviceError naming the failures.
- Rule slip, reported: the script's dry run on the simulators also ran the "independent readback", which opened the
  real COM3 / COM4 WITHOUT the rig lock (read-only queries: TMN?/TMX?/POS?/ERR?, SL/SU, W; nothing written). The
  readback is now skipped for the sim backend.

## Rotor window verified (09:18, `tools/phase7_rotor.py`, 14 steps, 0 failed; owner: "반영하도록 하고")
Driver-direct from the start 200.0 turns: +5 -> 205.0, back 200.0, -5 -> 195.0, back 200.0 (3.5 s per 5 turns);
+5.002 turns (one pulse past the edge, 102 501) refused before a write. Profile **v7**: `rotor_turns` +-5 turns
(session-relative) verified by these readbacks. Through the API: rotate(+1) -> 201.0, rotate(-1) -> 200.0,
rotate(+6) refused by the profile. Disconnect clean, lock released.

## Still open
- The rotor speed conversion assumes the controller multiplier 10 (`autonics.py`, shortcut comment);
  `rotor_speed_turns_s` stays unverified (a given speed is refused; None = SPD 100 as the main VI).

## Independent motor-limit audit (separate checker session, read-only, same day)

Per path, working tree after run 2: PI move_to PASS (driver check and limit re-read before the write; the
controller's own ERR 7 NOT EXERCISED because the driver refuses first), PI close / home PASS, PI open / reference
PASS (HEAD 02dc849 FAIL - the SPA re-write bug), ASI stage move_to PASS, stage close PASS (release only), ASI focus
move_to PASS, rotor move_to PASS for the driver window (no hardware backstop), emergency stop and watchdogs NOT
EXERCISED on the rig (fakes only), disconnect error reporting PASS by code reading (failure branch not exercised).

Fixed from its findings in the same commit: a failed ASI open released the shared port and its user count (item 3);
a stage move checks both axes before the first write (item 8); the PI driver caps `VEL` by the profile itself
(item 7); the fakes now model the SPA-un-references-the-axis bug, and tests cover the shared-port count, a failed
open, a whole-move refusal and a failed close making `disconnect()` raise (item 2).

Left open, by its numbering: 4 (the ASI / rotor windows recentre on every driver re-open: no absolute bound through
driver-direct calls or a new process; the API keeps its first origin), 5 (the rotor driver honours the window while
the profile entry is unverified - decision 0025 item 3), 6 (rotor speed: multiplier assumed, `SPD` query parse
unverified, speed None = SPD 100 as the main VI), 9 (watchdogs run only inside `moving()`), 11 (`stop()` waits for
an in-flight reply, up to 1.5 s on the rotor), 12 (a PI open that fails three times leaves TMN/TMX 0..39 set - the
safe side), 13 (close releases the stage / rotor but does not return them; the ASI SL/SU values before the session
were not recorded). Not proven on the rig: the controller's ERR 7, the ASI clamp, any stop or watchdog, the failed-
home path, the 3-attempt reference retry, lock loss mid-session.
