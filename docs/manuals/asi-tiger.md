# ASI Tiger (TG-1000) controller: XY stage and Z piezo

## Purpose on the rig

Moves the sample in X and Y, and holds the focus. The LabVIEW program corrects focus automatically: every 25th frame,
unless the panel control `Fix to a Certain Pattern` is on, it compares bead 2's position in the calibration stack with
the stack centre and moves the focus axis (`ASI_adjust focus-subvi.vi` and `Move Axis Relative.vi`). The joystick on
the controller is separate hardware and also moves the stage.

## Connection

| item | value | evidence |
|---|---|---|
| interface | RS-232 on the SUNIX PCIe serial card, port **COM4** (`\Device\SNX_SerialPort1`) | registry `HKLM\HARDWARE\DEVICEMAP\SERIALCOMM`, read 2026-10-22 |
| VISA | `ASRL4::INSTR`, NI MAX alias **`ASI_Piezo`** | V6: `docs/instrument-libraries.md:168` |
| framing | **115200** baud, 8N1, no flow control; do not pulse DTR/RTS | ASI RS-232 tech note; V6: `tools/motor_asi_io.ps1:1`, `archive/peer/2026-09-12-asi-tiger-readonly-commands.md` |
| terminator | CR (`\r`) on commands; replies end CR LF | same |
| replies | `:A` = command received (not "motion finished"); `:A <data>` for queries; `:N-<n>` = error | ASI serial command docs; V6: `tools/bench/p2_asi_query_limits.log` |
| timing | `/` round trip median 1.13 ms (0.69 ms fixed); LabVIEW `Initialize.vi` uses 115200 baud and a 500 ms timeout; scripts use 800 ms | V6: `docs/camera-acquisition-facts.md` "ASI measured 2026-09-12", `docs/main-vi-startup.md:33` |
| build | `BU X` -> `ADEPT_XYPZ`; axes X, Y (stage) and Z (Z limits +-0.075 mm, presumably the piezo) | V6: `tools/bench/p2_asi_query_limits.log` |

## Driver / SDK

- No vendor DLL. The LabVIEW program uses ASI's VISA driver `C:\Program Files\National Instruments\LabVIEW 2026\
  instr.lib\ASI TG-1000\Public\`: `Initialize.vi`, `Move Axis to Position.vi`, `Move Axis Relative.vi`,
  `Get Current Position.vi`, `Close.vi`. Every one goes through `Send Serial Command.vi`, which takes a **named
  semaphore of size 1** around its write/read pair and **reads by byte count**, not by terminator
  (V6: `docs/motion-path-audit.md:54-60`).
- The lab VI `...\zz_LabView VI\Madcity\ASI_adjust focus-subvi.vi` wraps the focus correction (inputs `VISA resource
  name`, `In position`, `Out position`, control references `+Inc`, `-Inc`, `Focus inc reference`).
- Vendor documentation: <https://docs.asiimaging.com/products/serial_commands>, TG-1000 manual
  <https://www.asiimaging.com/downloads/manuals/TG-1000%20System%20Full.pdf>.

## Command table

Motion and position units are **0.1 um** (10 000 units = 1 mm). `SL` / `SU` are in **mm**.

| command | meaning | arguments + units | response | LabVIEW program use | level + evidence |
|---|---|---|---|---|---|
| `W X` (`WHERE`) | read position of one axis (also `W Y`, `W Z`) | axis letters | `:A -18475` | `Get Current Position.vi`, 5 sites (d12, d73, d90, d146, d148) | **V3** - unchanged after an SL/SU write; follows moves (V6: `tools/bench/p2_asi_set_limits.log`, `tools/motor_asi_io.ps1` send mode) |
| `M X=<n> Y=<n>` (`MOVE`) | absolute move | 0.1 um | `:A` | `Move Axis to Position.vi`, 4 sites (d10 start-up, d88, d151, d167) | **V3** - +-0.4 mm moves reached their targets through the V6 gate on 2026-09-17 (V6: `docs/motor-limit-assurance-plan.md` "Why this exists") |
| `R X=<n>` (`MOVREL`) | relative move | 0.1 um | `:A` | `Move Axis Relative.vi`, 1 site (d73, inside the autofocus case #10407 of the frame loop) | **V1** - V6: `docs/motor-call-site-census.md`, `docs/camera-acquisition-facts.md:167-272` |
| `/` (`STATUS`) | busy? | - | `N` (idle) or `B` (busy) | not seen | **V2** - 50 exchanges, reply `N` (V6: `docs/camera-acquisition-facts.md` "ASI measured 2026-09-12") |
| `SL X=<mm> Y=<mm>` / `SU X=<mm> Y=<mm>` | set the lower / upper firmware limit, **absolute mm, persistent** | mm | `:A` | not seen | **V3** - `SL X=-3.8475 Y=-4.7744`, `SU X=0.1525 Y=-0.7744` read back within 0.5 um, position unchanged (V6: `tools/bench/p2_asi_set_limits.log`) |
| `SL X? Y? Z?` / `SU X? Y? Z?` | read the limits | - | `:A X=-500.000000 Y=-500.000000 Z=-0.075000` | not seen | **V2** - V6: `tools/bench/p2_asi_query_limits.log` |
| `UM X? Y? Z?` | units per mm | - | `:X=10000.000000 Y=10000.000000 Z=10000.000000 A` | not seen | **V2** - same |
| `BU X` (`BUILD`) | firmware build | bare form only | `ADEPT_XYPZ` | not seen | **V2** - same |
| `V` (`VERSION`) | firmware version (card-addressed on Tiger) | - | recorded reply `CH INDEX` (not understood) | not seen | **V2** - same |
| `RB <axis>` (`RDSBYTE`) | raw status byte (may be 0x0A) | axis | one raw byte | not seen | **V0** - ASI docs |
| `\` (`HALT`) | stop all motion | - | `:A` | not seen | **V0** - only the V6 sender's watchdog would send it; never measured |
| `!` HOME, `H` HERE, `Z` ZERO, `HM` SETHOME, `AZ` AZERO, `SS` SAVESET, `SP` SAVEPOS, `~` RESET, `MC`, `@` SPIN, `MM`, `VE`, `SN`/`NR`/`NV` SCAN | homing, origin changes, flash saves, reset, other motion | - | - | not seen | **V0** - ASI docs; **never send** (an origin change moves the SL/SU fence; bare `SAVEPOS` halts, writes flash and hangs the controller until a power cycle) |
| `Initialize.vi` | open the VISA session (115200 baud, 500 ms timeout) | - | - | d10 (start-up, followed by a `Move Axis to Position`), d88 | **V1** - V6: `docs/main-vi-startup.md:33`; what else it sends was not read |
| `ASI_adjust focus-subvi.vi` | the lab's focus correction; moves the focus axis and reads its position (contains a fixed `Wait` whose value is unknown) | control references, `In position` | `Out position` | d43 (the **frame loop**) and d99 | **V1** - V6: `docs/motor-call-site-census.md` "Rule 1c FACT" |
| `Close.vi` | close the session | - | - | end frame d83 (#29815) | **V1** - V6: `docs/main-vi-subvi-identity.md:105` |

## Units, signs and offsets

- `MOVE`, `MOVREL`, `WHERE`: **0.1 um** (`M X=8000` = +0.8 mm). `SL` / `SU`: **mm, absolute**. `UM` confirms 10 000
  units per mm on X, Y and Z.
- Position on 2026-09-18: X = -18 475 (-1.8475 mm), Y = -27 744 (-2.7744 mm), Z = 29 units.
- The limits are absolute coordinates: they move with the coordinate zero (HOME / HERE / ZERO).
- On an axis configured with negative direction, ASI warns that upper and lower may swap; read `SL?` / `SU?` before
  writing, and never write `SL >= SU`.

## Safety envelope and what to restore after a job

| item | value | source |
|---|---|---|
| development envelope X / Y | **the position at session start +- 2 mm**, written into the controller as `SL` / `SU` and read back | `third_party/mt_labview/tools/bench/motor_limits.json` `asi` (mode `relative`, `half_width_mm` 2.0); RULES.md section 3 |
| Z (focus) | no envelope declared ("ASI up/down: no limit") | V6: `docs/motor-limit-assurance-plan.md` "The envelope" |
| release | `SL X=-500 Y=-500`, `SU X=500 Y=500` (the state found before the project), read back | `motor_limits.json` `asi.release` |
| never | home, origin, zero, save, reset class (`ASI_ORIGIN` in V6 `tools/motor_gate.py`) | |

**SL/SU persist across power cycles**, so a job that set them must release them; an abnormal exit leaves them on,
which is the safe direction but must be released before an experiment (RULES.md principle: nothing motor-related may
differ from the original during an experiment).

## Known pitfalls

1. **The LabVIEW program talks to the ASI from inside the frame loop** (d43, about 3.6 times a second at 90 Hz). A
   position query costs about 2 ms of a 6.67 ms budget at 150 Hz. The port must keep this off the acquisition path
   (CLAUDE.md rule 6).
2. **Byte-count reads**: the LabVIEW driver blocks until the VISA timeout when a reply is shorter than expected.
   `WHERE`, `BUILD` and `VERSION` replies vary in length. Read by terminator in the port.
3. **`:A` means "received", not "arrived".** Poll `W` (or `/`) until the position is stable.
4. At a firmware limit the motor stops; the command is not rejected and the target is not documented as clamped.
5. `BU` with arguments (`BU Y=...`, `BU Z+`) and other "query-looking" forms carrying `=`, `+` or `-` are writes.
6. The `sl` / `su` numbers in `motor_limits.json` (`-3.8475 ...`) are the 2026-09-18 absolute window, used only in
   mode `absolute`; the live mode is `relative`.
7. Two callers share the port only through the driver's semaphore; in the port one owner thread should hold the port.

## Open questions for the owner

1. Which axis does the focus correction move - Z (the piezo)? What is the piezo's range and its unit mapping (the
   Z limits read +-0.075 mm)?
2. What does the start-up move on d10 command, from which value (`Set Focus (0->50)`, 51.5 on the panel)?
3. What does `Initialize.vi` send besides opening the port?
4. Should Z get an envelope for development runs?
5. Is the joystick used during experiments, and should the new program lock it out during automated runs?
