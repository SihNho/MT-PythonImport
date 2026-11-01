# 2026-11-01 afternoon: the z-scan settle time verified, and what a killed program leaves behind

Owner, after the PC's unexpected shutdown at 07:53: check the connections, check whether the program comes back
after a sudden end, and remake the LUT ("LUT 새로 만들어서 재확인 ㄱㄱ"). Data:
`G:\l2s_rig_data\2026-11-01_lut_settle` (report.json, analysis.json, cal_settle, piezo_settle_current_numba.h5, frames)
and `G:\l2s_rig_data\2026-11-01_kill_restart` (victim.h5). Scripts: tools/rig_lut_settle.py, tools/rig_kill_victim.py,
tools/rig_kill_restart.py.

## The PC
- Windows event 41 (kernel power): "the system rebooted without cleanly shutting down" at 07:53:29, booted again 13:50:02.
  No minidump, no MEMORY.DMP, no error or warning in the System or Application log in the 25 minutes before: nothing
  the software side can explain (a hang or a power cut; no program of ours was running - the last rig job released
  the lock at 03:31).
- After the boot: the JAI still on NI's driver (oem11.inf 26.3), the six COM ports present, the rig lock free.

## Connection after the reboot
`api.devices.connect` real-motors MT-TIRF: all eight devices connected in 26.5 s (camera through IMAQdx, PI, rotor,
ASI stage and focus, Arduino, light, iXon found at +16 C "off"); disconnect clean; the lock released. Done three
times during the afternoon (13:53, 13:56, 13:58), each clean.

## The z scan with the 0.2 s settle (owner "0.2초로 넣어")
The same four reference beads as on 10-31; the sample had moved (+54, +7) px overnight (found again by correlation,
refined on the new frame; focus still good, light a little dimmer: frame mean 59 vs 85). 60 slices x 100 nm, 10 frames
averaged, 0.2 s after each move: 21 s (8 s without the settle). Then the piezo step run (tracker `current` on numba,
4082 frames at 89.97 Hz, 0 gaps, 0 drops), steps of 3 s each:

| commanded (um) | 0 | +0.5 | +1.0 | +0.5 | 0 | -0.5 | -1.0 | -0.5 | 0 | +0.1 | +0.2 | +0.3 | +0.4 | +0.5 | 0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tracked z, bead 1 (um) | 3.061 | 3.523 | 4.013 | 3.449 | 3.046 | 2.622 | 2.012 | 2.506 | 2.990 | 3.128 | 3.210 | 3.367 | 3.473 | 3.615 | 3.108 |

| LUT | slope (4 beads) | rms residual | zero drift over 45 s |
|---|---|---|---|
| 10-31, no settle (8 s scan) | 1.04 - 1.06 | 49 - 55 nm | 51 - 57 nm |
| 11-01, 0.2 s settle (21 s scan) | **0.992 - 0.994** | 46 - 48 nm | 37 - 42 nm |

The 5 % overshoot of 10-31 is gone: the unsettled scan was the cause, as proposed. The remaining -0.7 % is within what
the hysteresis shows (the 1 um step reads 0.95 um going up, 1.03 um coming down). The 100 nm steps are still irregular
(+128, +82, +157, +106, +142 nm): a property of the piezo / its small-step hysteresis, not of the LUT.

## A program killed mid-run (taskkill /F while recording, 13:58)
- The victim (MT mode, recording at 90 Hz, 545 frames received) was killed; the OS closed its ports.
- **Restart: `api.devices.connect` is refused in 0.1 s** - "STALE lock: holder mtpy (pid 24504) is gone ... a person
  checks the rig (magnet position and PI limits, iXon cooling) and takes the lock over by hand per RULES.md; this
  program never does". That is the rule (RULES.md, decision 0026): the program does not come back on its own after a
  crash; the owner takes the stale lock over (`riglock.py acquire --take-stale --reason ...`) after looking at the rig.
- **The run file survived:** victim.h5 opens, 526 of the 545 frames (the last 0.2 s unflushed), the motor readings,
  the segment and the recording-on event; the recording-off row is missing (never written) - the reader has to treat
  an open recording as ended at the last frame (fault list D4).
- The PI session limits (TMN/TMX) stay in the controller after a kill; the next open sets them again from the safety
  profile; the magnet was at 0 mm and stays there.
