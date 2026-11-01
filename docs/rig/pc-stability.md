# The rig PC's unexpected shutdowns (ingested 2026-11-01; owner: it dies while idle, the PSU and the supply are new)

What the Windows System log of the rig PC (20185292-P03, Windows 10 Home 19045) says, what was ruled out, what to
check next, and the heartbeat log that will tell the two remaining families apart. The owner raises it at the
2026-11-02 meeting. Korean summary: [pc-stability.ko.md](pc-stability.ko.md).

## Evidence (System log, 2026-07-04 .. 2026-11-01)
| item | finding |
|---|---|
| Kernel-Power 41 ("rebooted without a clean shutdown") | **18 times in 120 days** (about weekly); every one with `BugcheckCode = 0`: no Windows crash (no blue screen, no minidump) - the machine lost power or hard-stopped and was switched on again later |
| moments of death (event 6008) | 07:53, 00:15, 01:49, 07:52, 22:23, 06:03, 06:34, 02:11, 08:41, 07:12, 04:03, 01:37, 03:17, 09:08, 14:03, 20:17, 09:41, 12:24 - **mostly night / early morning, idle**; none during a tracking job of this project |
| sleep | power plan "High performance"; **0** sleep entries (Kernel-Power 42) and 0 resumes (107) in 120 days: the PC is awake when it dies |
| WHEA-Logger 19 | **one corrected hardware error, 2026-11-01 00:15: processor core, "Internal parity error", APIC 7** - a CPU core caught and corrected a fault; such errors point at the CPU or its power delivery (board VRM, voltage) |
| disk | two I/O retries (disk 51 / 153) on 2026-09-23 only |
| thermal / NTFS / bugcheck records | none |

## Ruled out (owner)
- The power supply unit was replaced with a new one; the PC runs from a separate power conditioner / UPS whose
  other instruments show no trouble. External power and the PSU are not it.
- Sleep / hibernate (log above). The CMOS battery is not a cause of shutdowns (it keeps the clock and BIOS settings
  only).
- This program: it ran at none of the 18 moments; the single-frame 15-95 ms stalls seen in the benches
  ([results/2026-11-01-motion-noise-bead-count-gui.md](../results/2026-11-01-motion-noise-bead-count-gui.md)) are
  ordinary OS / driver pauses with no WHEA record at those times.

## What remains
1. **CPU / board power delivery** (VRM, voltages): the WHEA parity error fits; idle is where the core voltage is
   lowest, so an unstable supply shows up at idle first. Typical outcome: the board, sometimes the CPU.
2. **Memory**: non-ECC errors leave no log; they end in a hang or a reset. Cheap to test and to replace.
3. Unlikely: overheating (idle), a GPU driver hang (would leave a bugcheck).

## Diagnosis order (no BIOS knowledge needed for 1-3)
1. memtest86 from a USB stick overnight (boot-menu key F8 / F11 / F12; no BIOS screens). Errors -> replace the memory.
2. If two or more memory modules: run on one at a time for a week each.
3. Board maker's Windows utility: load BIOS defaults (XMP / overclock off), then update the BIOS.
4. If WHEA parity errors recur after 1-3: board or CPU; the board first (ageing VRM / capacitors). Same socket ->
   CPU, memory and GPU move over.

## The heartbeat log (tools/pc_heartbeat.py)
A line every 10 s (time, uptime, CPU %, free memory, written through to disk) into
`G:\l2s_rig_data\pc_heartbeat\YYYY-MM-DD.log`, 7 days kept, below-normal priority (no effect on tracking: a few ms
per 10 s against a 11 ms frame budget met with a ring buffer). Registered by the owner as a logon task:

```
schtasks /Create /TN "mtpy pc heartbeat" /TR "\"G:\Codes\LabVIEW2Scr\.venv\Scripts\pythonw.exe\" \"G:\Codes\LabVIEW2Scr\tools\pc_heartbeat.py\"" /SC ONLOGON /F && schtasks /Run /TN "mtpy pc heartbeat"
```

Reading it after the next death (`python tools/pc_heartbeat.py --report`): 10 s spacing right up to the last line
= the machine stopped at once (power delivery / board); growing gaps or a CPU spike before the end = it hung or
slowed first (memory / a hang). One or two events decide the direction.

## Why it matters for the experiments
A weekly death at night ends any long recording (LabVIEW or this program) and leaves the rig in whatever state the
devices were in (the PI keeps its position and limits, the iXon keeps cooling, a run file loses its last second).
Long unattended runs are not safe until the cause is found.
