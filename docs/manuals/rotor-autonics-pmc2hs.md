# Autonics PMC-2HS rotor controller (magnet rotation)

## Purpose on the rig

Rotates the magnets about the optical axis, which twists the tethered molecule (turns are the experiment's twist
coordinate; the user drives to -7200 deg = 20 turns and -14400 deg = 40 turns in practice). A pulse-driven motor on
the **X axis of a two-axis Autonics PMC-2HS** motion controller; the Y axis is not known to be connected.

## Connection

| item | value | evidence |
|---|---|---|
| interface | USB virtual COM port, FTDI FT232R (VID_0403 PID_6001, FTDI serial `AI03Q9JZA`), port **COM5** | `Get-PnpDevice -Class Ports`, read 2026-10-22 |
| VISA | `ASRL5::INSTR`, NI MAX alias **`Rotor`** | V6: `docs/instrument-libraries.md:170` |
| framing | **9600** baud (controller default; range 9600..115200), 8 data bits, no parity, 1 stop bit, no flow control | Autonics manual DRW170814AB 8.1 p. 67; V6: `docs/rotor-protocol.md` "Protocol facts" |
| terminator | CR (`\r`, 0x0D) on commands and replies; arguments separated by a space, axes by a comma; characters `0-9 A-Z space CR` only | manual 8.2-8.3 pp. 67-70 |
| replies | **motion and setting commands have no reply**; queries reply one line | same |
| timing | FTDI latency timer 16 ms (driver default); scripts use a 1500 ms read timeout; the LabVIEW driver times out after 2 s | V6: `docs/motion-path-audit.md:30-34`, `tools/motor_rotor_io.ps1:40` |
| model | PMC-2HS (two-axis, proved by the `POS` reply). Whether it is the -232 or -USB variant is not verified | V6: `tools/bench/hw_rotor_read.log` |

## Driver / SDK

- No vendor DLL. The LabVIEW program uses the lab's VISA driver `C:\Program Files\National Instruments\LabVIEW 2026\
  instr.lib\Autonics Motor\` - exactly three VIs: `Configure.vi` (opens the VISA session and writes an initial
  constant string), `SetCommand.vi` (one Ring selects the operation) and `Close.vi`.
- `SetCommand.vi` Ring: `MovePos` (absolute, sends `PAB`), `MovePosRel` (relative, `PIC`), `Get Position` (Ring value 2,
  `POS`), `SetSpeed` (`SPD`). Its `Baseline Startpoint` = **200 turns** is a driver constant, not on the connector pane,
  identical at all 9 call sites (V6: `docs/instrument-libraries.md` "RESOLVED 2026-09-14").
- Primary source: Autonics PMC-1HS/PMC-2HS user manual DRW170814AB, chapter 8 "Serial Communication Commands"
  (pp. 67-78), <https://autonics.se/wp-content/uploads/2018/03/pmc_1_2_hs_en_drw170814ab_20171218_he_20180109.pdf>.

## Command table

`<x>` is the X-axis value in **signed decimal pulses**; a single value addresses X only.

| command | meaning | arguments + units | response | LabVIEW program use | level + evidence |
|---|---|---|---|---|---|
| `POS` | read both position counters | - | `POS hhhhhhhh,hhhhhhhh` - X then Y, 8 hex digits each, two's complement (`FFFFFFF6` = -10 pulses) | `SetCommand.vi` `Get Position`; only d115 wires `Pos_degree` (the one read-back) | **V3** - `POS 000186A0,00000000` (X = 100 000); after `PIC -10` read `FFFFFFF6` (V6: `tools/bench/hw_rotor_read.log`, `archive/bench-2026-09-14-rotor-sign/hw_rotor_signed_test.log`) |
| `PAB <x>` | absolute move | target pulses | none | `SetCommand.vi` `MovePos`: pulses = deg / 0.72 + 500 x 200 | **V3** - `PAB 0` returned the rotor to 0.0 deg (V6: `tools/bench/hw_rotor_visible.log`) |
| `PIC <x>` | relative move; `-` = CCW | step pulses | none | `SetCommand.vi` `MovePosRel`: pulses = deg / 0.72 | **V3** - `PIC -10` -> -7.2 deg; `PIC -1500` -> -1080.0 deg; `PIC 125` / `PIC -125` reached 100 125 / 100 000 (V6: `tools/bench/hw_rotor_visible.log`, `tools/bench/motor_gate.log` 2026-10-19 11:55) |
| `SPD <x>` | set the drive speed | 1..8000; drive pps = value x speed multiplier (1..500, default 10) | none | `SetCommand.vi` `SetSpeed`, value = panel `Rot Speed` (default 100), sent with every rotation | **V2** - with `SPD 100` the rotor ran ~850-880 pps, consistent with multiplier 10 (V6: `tools/bench/hw_rotor_visible.log`, `docs/rotor-protocol.md` "Speed default") |
| `SPD` (no argument) | query the drive speed | - | `SPD x,y` (manual: `[LF][CR]` ending) | not seen | **V0** - manual p. 69; never read on this rig |
| `CLL X` | clear the active position counter (no motion) | - | none | not seen | **V3** - counter 100 000 -> 0 without motion on 2026-09-14 (V6: `docs/rotor-sign-diagnosis.md` "Hardware acceptance"); refused by the V6 gate |
| `CLR X` | clear the actual position counter | - | none | not seen | **V0** - manual pp. 68-69 |
| `STO X` | decelerating stop | - | none | not seen | **V0** - manual p. 70; only the V6 sender's watchdog would send it |
| `HOM X` / `OGE X` | home search (moves; the soft limit does not act) / force-end it | - | none | not seen | **V0** - manual p. 70; never send |
| `ERD X` | error bits (bit 9 / 8 = software limit - / + error) | - | hex | not seen | **V0** - manual |
| `VER`, `SCI`, `INR X`, `IDC X` | version, port settings, input / status reads | - | text | not seen | **V0** - manual pp. 67-76 (`SCI` with arguments writes the port settings) |
| `IHR X<addr>` / `IXR X<addr>` | read 2- / 4-byte EEPROM parameter | hex address | hex data | not seen | **V0** - manual pp. 76-77 |
| `IHS X<addr>,<data>` / `IXS X<addr>,<data>` | **write** EEPROM parameter (soft limits, speed multiplier, home offset ...) | hex | echo | not seen | **V0** - manual pp. 76-77; soft-limit addresses `7A` / `7B` are inferred, not confirmed |
| `JOG`, `PRG`, `PST`, `PRS`, `EDP`, `PSP`, `SSM`, `OUT`, `RST` | continuous drive, stored programs, stored speeds, outputs, reset motion IC | - | - | not seen | **V0** - manual; never send (unbounded or bypasses the envelope) |
| `Configure.vi` | open the VISA session `Rotor` and write an initial constant string | - | - | 1 site (d92) | **V1** - V6: `docs/motor-call-site-census.md`; the constant's content was not read |
| `Close.vi` | close the session | - | - | end of run | **V1** - V6: `docs/instrument-libraries.md:166-170` |

## Units, signs and offsets

- **0.72 deg per pulse, 500 pulses per turn** (driver constant, confirmed on hardware).
- Counter range -8 388 608 .. +8 388 607 pulses (about +-16 777 turns). Negative values are legal.
- **The LabVIEW zero is a +200-turn offset in the controller counter.** `Pos_degree = 0.72 x pulses - 360 x 200`, and
  `MovePos` adds 500 x 200 = 100 000 pulses. So controller counter **100 000 (`000186A0`) = 0 deg in LabVIEW**;
  -7200 deg = counter 90 000; -14 400 deg = 80 000.
- The counter was cleared to 0 on 2026-09-14 and later restored: the V6 gate read **100 000** on 2026-10-19
  (`V6: tools/bench/motor_gate.log`). Read `POS` before relying on either convention.
- Sign: a negative `PIC` is CCW (manual). A `PIC -1500` turned the rotor the way the user expected for -3 turns
  ("direction confirmed by eye", V6: `docs/rotor-sign-diagnosis.md` 20:28 entry); which way that is as seen from the
  camera was not recorded.

## Safety envelope and what to restore after a job

| item | value | source |
|---|---|---|
| development envelope | **start position +- 2500 pulses (+-5 turns)**, X axis only, `SPD` <= 100 | `third_party/mt_labview/tools/bench/motor_limits.json` `rotor`; RULES.md section 3 |
| how it is enforced | by the gate, **not** by the controller: session start reads `POS` (after one dummy read); every `PAB` target and every fresh `POS + PIC` target must lie inside the window; two identical `POS` reads before a move; poll `POS` every 300 ms and send `STO X` outside window +-25 | V6: `tools/motor_gate.py`, `tools/motor_rotor_io.ps1`, `docs/rotor-protocol.md` "Envelope design" |
| never | `CLL`, `CLR`, `HOM`, `OGE`, `RST`, `IHS`, `IXS`, programs, `JOG`, `SSM`, `OUT` - they move or bypass the envelope | `tools/motor_gate.py` `ROTOR_FENCE` |

Nothing is written to the controller, so nothing has to be released. Restore after a job: the counter convention
(never clear it), port closed. Where the rotor is left at the end of a job is **not decided** (the V6 gate leaves it
where it is).

## Known pitfalls

1. **The first read after opening the port times out** (2 s, empty), and its late reply is consumed by the next read.
   Send one dummy `POS`, wait ~200 ms, flush, then read (V6: `docs/instrument-libraries.md:316-321`).
2. **The original parses `POS` as unsigned** (`Hexadecimal String To Number`, U32): `FFFFFFF6` becomes
   +3 092 376 445.92 deg. That is why the +200-turn offset exists. Parse as U32 then reinterpret as signed 32-bit
   (or subtract 2^32 when bit 31 is set). A Type Cast of the ASCII text is not a hex parse.
3. **Writes have no acknowledgement.** Completion = the target reached and two consecutive identical `POS` reads.
4. **Clearing the counter moves the zero.** With the counter at 0 the original program's first absolute move becomes a
   200-turn trip. Restore with `PIC 100000` only if the original will run again (and only through the gate).
5. `HOM` ignores the soft limit; `RST`'s effect on the counter is undocumented.
6. The EEPROM soft limits exist (disabled by default) but are not installed: EEPROM wear, unconfirmed addresses, and
   unknown activation (live or after reset).
7. Two FTDI FT232R ports exist (COM5 rotor, COM6 unknown). Identify the rotor by its FTDI serial `AI03Q9JZA`, not by
   COM number. The strings `Rot, COM3 9600` / `Rot, COM2 115200` in the VI are a legacy ring, not this machine.

## Controller soft limits - read on the rig 2026-10-30 (`tools/rotor_limits_probe.py`, read-only)

Owner: "로터도 하드웨어 리밋 따라가자". Manual DRW170814AB p. 78 confirms the addresses: `IXR X7A` soft limit +, `IXR X7B`
soft limit - (4-byte pulses), `IHR XE4` operation mode 2 (REG72; digit 6 "Soft Limit" 0 = enable, 1 = disable, the
manual itself marks the logic as reversed), `IHR XE6` speed multiplier. Behaviour (3.2.6): when enabled and the
position passes a limit the controller decelerates to a stop, `ERD` bits 9 / 8 report it, and the only way out is a
move in the other direction; home search ignores the limit.

| query | reply | meaning |
|---|---|---|
| `POS` | `POS 000186A0,00000000` | 100 000 pulses = 200 turns (the usual rest position) |
| `IXR X7A` | `IXR X7A, 007FFFFF` | soft limit + = +8 388 607: factory default, not in use |
| `IXR X7B` | `IXR X7B, FF800000` | soft limit - = -8 388 608: factory default, not in use |
| `IHR XE4` | `IHR XE4, 0800` | operation mode 2 word; how its digits map onto the 16-bit word is not confirmed |
| `IHR XE6` | `IHR XE6, 000A` | speed multiplier 10 - confirms the driver's assumption (open question 2 closed) |
| `ERD X` | `ERD X4000` | error word 0x4000 (bit 14 "program error" by the manual's table; the rotor works, meaning unclear) |
| `VER` | `VER 20081001-0000001-1-1` | firmware |

So today the controller holds no effective limit: "following the hardware limit" needs the limits set in the
controller first (its own panel / teaching unit, or a one-time parameter write with the owner's word and a readback).
The driver (`autonics.py`) now reads 7A / 7B / E4 at every open, cuts the session window to the controller's limits
when they are set, refuses to open when the rotor already sits outside them, and reports them in `limits()`
(`controller_soft_limits_in_use`). At the factory defaults the profile window (+-5 turns) is the only limit.

## Open questions for the owner

1. Exact model (PMC-2HS-232 or -USB), and is anything connected to the Y axis?
2. ~~The speed multiplier stored in the controller~~ read 2026-10-30: 10.
3. What initial string does `Configure.vi` send?
4. Where should the rotor be left at the end of a job (in place, or back to the start position)?
5. ~~Should the controller's EEPROM soft limit be installed for the released program?~~ Decision 0027 (2026-10-30):
   the limit is whatever the controller holds, read at every open - today its counter range; the program writes
   nothing. The profile adopts the readback with `tools/rotor_limits_probe.py --adopt` (not yet run).
6. Which physical direction (seen from the camera) is positive degrees?
