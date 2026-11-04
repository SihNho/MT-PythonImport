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
schtasks /Create /TN "mtpy pc heartbeat" /TR "G:\Codes\LabVIEW2Scr\.venv\Scripts\pythonw.exe G:\Codes\LabVIEW2Scr\tools\pc_heartbeat.py" /SC ONLOGON /F
schtasks /Run /TN "mtpy pc heartbeat"
```

(Two lines, no inner quotes: Windows PowerShell 5.1 has no `&&` and mangles `\"`; the paths have no spaces.)

Reading it after the next death (`python tools/pc_heartbeat.py --report`): 10 s spacing right up to the last line
= the machine stopped at once (power delivery / board); growing gaps or a CPU spike before the end = it hung or
slowed first (memory / a hang). One or two events decide the direction.

## First death under the heartbeat (2026-11-01 23:58)
The PC died at 23:58:15-25 on 2026-11-01 (event 6008: last alive 23:58:15; heartbeat's last line 23:58:25) and was
switched on at 11:43 the next day. The heartbeat kept its 10-s spacing to the last line with no gap anywhere in
the 4 h before; CPU 0.2-2.2 %, 52 GB free: the machine was idle (the bench had ended at 23:20) and **stopped at
once** - no slowdown, no hang, no WHEA record. By the reading above this is the power-delivery / board family,
not memory or a hang. One event; a second one of the same shape settles it. (The 07:53 death of 11-01 preceded
the heartbeat.)

## Two more deaths (2026-11-03 07:34 and 20:14) - one of them under load
- **11-03 07:34** (owner away): heartbeat 10-s lines to 07:34:04, CPU 0.3-0.5 %, idle - the same instant stop as
  11-01 23:58. Rebooted 11:25.
- **11-03 20:14**: the heartbeat's last line 20:14:02 shows **CPU 72.7 %**: the GUI 248-Hz bench block was running
  (its 16th run had just started; the rig lock was held). So the deaths are **not idle-only**; the pattern is the same
  (no gap, no slowdown, no WHEA). Rebooted 11-04 13:18. The rig was left mid-run (focus / stage / magnet possibly
  away from their start, the lock stale) - see STATUS 11-04.
Four deaths in three days, all instant: the board / CPU power-delivery family. The owner decided to replace the
board (11-04: "메인보드 아무래도 교체해야겠는데").

## The PC and what a replacement board must have (inventory 2026-11-04)
| part | now |
|---|---|
| board | **ASRock H410M-HVS** (micro-ATX, LGA1200, Intel H410, BIOS P1.20 of 2020-07; a budget board: 2 DIMM slots, retailer listings say a 5-phase VRM, no independent VRM review found) |
| CPU | Intel Core i5-10500 (6 cores, 10th gen, 65 W) |
| memory | 2 x 32 GB Samsung DDR4-2667 UDIMM (M378A4G43AB2-CWE), non-ECC |
| GPU | NVIDIA GeForce RTX 2060 (PCIe x16) |
| cards | SUNIX 2-port serial PCIe card (the ASI / PI serial lines) |
| drives | Samsung 860 EVO 250 GB SATA SSD (system), Toshiba 4 TB SATA HDD |
| camera | JAI SP-5000M-USB on USB 3 (the board's own controller) |

**Keep CPU, memory, GPU, drives; replace the board only** (same socket LGA1200). Requirements:
1. LGA1200 with a chipset that runs a 10th-gen CPU: **B560 / H570 / Z590** (500 series, 10th gen supported out of
   the box) or B460 / H470 / Z490 (400 series). Avoid H410 / H510 (the same budget class as the failing board).
2. A sturdier VRM than a 5-phase budget board: the mid-range micro-ATX boards (8+ phases with heatsinks).
3. Slots: one PCIe x16 for the RTX 2060 **and one free PCIe x1 / x4 for the SUNIX serial card**; at least 2 SATA;
   4 DIMM slots (room to go to 128 GB later, and a different pair of slots if a slot is suspect).
4. USB 3.x on the rear panel for the JAI camera (any 500-series board has it); M.2 optional (a later system-drive
   upgrade).
5. Form factor: micro-ATX fits the present case; ATX only if the case takes it (check before buying).
Candidates (LGA1200 is discontinued; new-old stock or lightly used; Korean listings seen 2026-11-04): **ASRock B560M
Pro4** (4 DIMM, x16 + x1 + x4-wired x16, 6 SATA), **MSI MAG B560M Mortar** (4 DIMM, 12-phase, x16 + x1 + x4),
**ASUS TUF Gaming B560M-Plus**, **Gigabyte B560M DS3H**; Z590 micro-ATX boards of the same makers if cheaper on the
day. Used asking prices for the first two were about 100 000 KRW on Bunjang; new prices on Danawa were not readable
from here - check `B560M Pro4` / `MAG B560M Mortar` there.
If the deaths continue on the new board, the CPU is next (the 11-01 WHEA parity error came from a core); then the
memory (memtest86 overnight is still cheap and worth doing before the swap).
Sources: [Danawa search](https://search.danawa.com/dsearch.php?k1=B560M), [Bunjang B560M](https://m.bunjang.co.kr/keywords/b560m),
[Newegg MSI B560M Mortar](https://www.newegg.com/p/N82E16813145332), [ASRock H410M-HVS listing (5-phase)](https://www.morele.net/plyta-glowna-asrock-h410m-hvs-r2-0-7893093/).

## Why it matters for the experiments
A weekly death at night ends any long recording (LabVIEW or this program) and leaves the rig in whatever state the
devices were in (the PI keeps its position and limits, the iXon keeps cooling, a run file loses its last second).
Long unattended runs are not safe until the cause is found.
