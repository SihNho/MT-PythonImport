# Rig core parameters (one register)

Owner 2026-10-26: "리그 핵심 파라미터 일환으로 둬야할듯. 리그 핵심 파라미터들은 따로 관리해서 추후 프로그램 통제할 때 한번에
확인 및 통제 가능하게 모아둬야할듯" (decision [0020](../decisions/0020-rig-core-parameters-register.md)).

Every value that sets how the rig moves, stops, sees or converts numbers is listed here once, with where it lives,
who may change it and how it was verified. The program will later read this register at start-up, compare it with
what the devices report, and show and control all of it on one screen (0020). Until then this page is the reference.
When a value changes, change it here first (new row date, old value kept in the history column or git).

Columns: **Where** = where the value actually takes effect (controller RAM / controller non-volatile / rig safety
profile / preset / session); **Changed by** = who may change it; **Verified** = how and when it was checked on the rig.

## Magnet axis (PI C-863.11 + stage `6234-9-4102`)

| Parameter | Value | Where | Changed by | Verified | Source |
|---|---|---|---|---|---|
| Position limit (soft, TMN / TMX) | **0 .. 40.9 mm** (0 = ceiling, farthest from the sample; 40.94 = travel end / touch; 39 mm until profile v8) | controller RAM (SPA 0x30 / 0x15, set and released every session) + rig safety profile v9 (owner 2026-10-31 '모터 리밋은 40.9 까지 잡아두자') | rig re-commissioning only (0015 item 5) | 0..39 at the rig 2026-09-18 (owner); TMX 40.9 written and read back at the PI open 2026-10-31; read back every session | V6 `tools/bench/motor_limits.json`; profile v5 |
| Speed maximum | **15 mm/s** (VEL; controller already at 15) | rig safety profile v5 + controller RAM (VEL) | rig re-commissioning only | 2026-10-25: VEL? 15, 0->30->0 mm clean (card pivel15r); speed write 10 <-> 15 takes effect (card pivelsw) | 0016; V6 `tools/bench/pi_vel15_check_20261025.log`, `pi_velsw_check_20261025.log` |
| **Stall threshold (Maximum Position Error, 0x8)** | **1.0 mm** - kept as is (owner 2026-10-26: "우선은 1.0 mm로 두자.") | controller (not written by us) | owner decision; a change is a controller parameter write | read 2026-10-25 (card pistall); normal lag measured 2026-10-25 (card pistall2): max **about 0.05 mm** (+-0.02; 0.15 with one slow sample) at the end of acceleration, 0.02-0.05 mm at constant speed = about 1/20 of the threshold | V6 `tools/bench/pi_stall_params_20261025.log`, `pi_lag_20261025.log` |
| What a stall does | controller servo off + error -1024; program returns to 0 mm once, error window + record, else lock (0019) | program | - | simulator only (a real stall is not provoked: it would damage the piezo stage) | 0019 |
| Acceleration / deceleration | 300 / 300 mm/s^2 (controller maxima 500 / 500, 0x4A / 0x4B) | controller | not changed by us | read 2026-10-25 | `pi_stall_params_20261025.log` |
| Maximum closed-loop velocity (0xA) | 50 mm/s (controller setting; the stage's own datasheet not found) | controller | not changed by us | read 2026-10-25 | same |
| Travel (controller geometry) | reference -> positive limit 51.5 mm (0x2F); negative limit -> reference 0.5 mm (0x17); limit -> hard stop 0.1 mm (0x63); release value TMX 52 | controller | not changed by us | read 2026-10-25 | same |
| Referencing | FNL (negative limit switch = 0 mm) at every session start, then a 2 mm commanded-vs-readback check | gate / program | - | every session | V6 `docs/rules/hardware.md` |
| Stage model | **unknown** (CST? = `6234-9-4102`; "M-126.PD1" in old VI strings is probably another room's) | - | - | open | `docs/manuals/pi-c863.md` |
| Firmware | C-863.11 1.3.0.7 | controller | - | read | same |

## Force (derived from the magnet position, 0010 / 0017 / 0018)

| Parameter | Value | Where | Changed by | Verified | Source |
|---|---|---|---|---|---|
| Force equation (M-270, LabVIEW `Magnet2Force v3_for M270.vi`, case "1, Default") | F_pN = 48.8162 e^(-d/1.13483) + 22.8394 e^(-d/3.68428) - 0.45845, d = touch - pos (mm) | program (force calibration object) | a new force calibration | VI run vs formula at 16 points, max rel. dev. 2e-16 (card m2feq2, 2026-10-25) | V6 `tools/bench/m2feq2_report.md` |
| 'Mag pos when touched to glass' (touch) | per session, entered by the user | session | user | - | 0018 |
| Force limit | none of its own: follows the magnet position limit; out-of-range force / position coerced, motor value coerced at the last step | program | - | tests (simulator) | 0017, 0018 |

## Rotor (Autonics PMC-2HS X axis)

| Parameter | Value | Where | Changed by | Verified | Source |
|---|---|---|---|---|---|
| Rotation range | +-5 turns from the session-start position | gate envelope (V6) / profile v5 (**unverified** -> refused by the program) | rig re-commissioning | not verified for the application | V6 `motor_limits.json` rotor; profile v5 |
| Speed | gate caps SPD at 100 (native units); turns/s maximum not set (**unverified**) | gate / profile | rig re-commissioning | open | same |

## XY stage (ASI)

| Parameter | Value | Where | Changed by | Verified | Source |
|---|---|---|---|---|---|
| XY window | session-start position +-2.0 mm (SL / SU), never homed | controller (set / released per session) + profile v5 | rig re-commissioning | owner 2026-10-15; read back every session | V6 `motor_limits.json` asi |
| Focus (z) window | not set (**unverified** -> refused) | profile v5 | rig re-commissioning | open | profile v5 |

## Camera and optics (see also [../rig-facts.md](../rig-facts.md))

| Parameter | Value | Where | Changed by | Verified | Source |
|---|---|---|---|---|---|
| Camera | JAI SP-5000M-USB, 1280 x 1024 (binning 2); presets "Experiment 90 Hz", "Force calibration (max fps)" | camera preset | user (presets) | - | rig-facts.md; ui-requirements U-camera presets |
| Objective | MT 50x oil (nucleosome project); MT-TIRF 60x / 1.50 | rig preset | owner | - | rig-facts.md |
| Pixel size | **about 203 nm/px at 50x, measured** (X 204.6 / Y 200.5 at 35 um; camera rotated about 2.3 deg against the stage); `.cal` 84 nm/px is stale (100x) and unused by LabVIEW | rig preset | measurement | 2026-10-26, ASI single-axis moves vs bead displacement | [results/2026-10-26-refbead.md](../results/2026-10-26-refbead.md) section 1 |
| Focal-shift factor | 0.88 (source not recorded) | rig preset, applied in analysis | owner | open | rig-facts.md |
| z calibration | 60 slices x 100 nm | calibration | user | - | rig-facts.md |
| **z LUT band-pass and forget radius (50x)** | **initial values LOW 0 / HIGH 40 / forget 10 px** (LabVIEW panel so far 0 / 25 / 20); the user still picks them per bead, as now | calibration settings, stored per bead in the `.cal`; `mtpy.calib.DEFAULT_*` | user (per calibration) | offline 2026-10-27: z noise 7.25 -> 4.64 nm (fixed beads, 50x) | decision 0022; results 2026-10-26-refbead.md section 3b |

## Open
- Machine-readable form and start-up comparison with the devices (0020 item 2) - not built yet.
- Stage model; pixel size at 50x; focal-shift source; rotor and focus windows.
