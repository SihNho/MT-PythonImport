# 0007 — Abort, crash recovery and the emergency stop

**Decided:** 2026-10-21

## Abort
- **Motors, magnet and laser stay as they are.**
- **A graceful abort** (button or exception) sends a stop command to every axis, so motion halts in place.
- **A hard crash** cannot send anything. The controllers then finish any move already commanded.

## Restart after an abort or a PC crash
1. Detect connections that were not closed and close them. After a PC reboot the ports are already free. A port still held means a previous instance is hung: find it through its pid/lock file and end it.
2. Reconnect and **only query state**: position, limits, errors, whether the reference survives. Nothing moves automatically; a reference move is motion too.
3. Detect unfinished data files and recover what can be recovered.
4. A session-state file, written continuously during a run, records:
   - the open devices;
   - the last commands;
   - the current file;
   - the beads and calibration.
   
   On start-up the application uses it to offer recovery.
5. During an experiment, recovery is done **by the person at the rig, inside the application's recovery screen**. It needs no AI tools and no development lock.

## Emergency stop
- An **on-screen button**, handled by a dedicated safety thread that sends stop commands directly, never queued behind busy loops.
- A keyboard shortcut as a backup, in case the GUI process is busy.

## Open
- Should the laser start in the off state after an abnormal end?
- What does the emergency stop do to the laser?
- A UPS is recommended, because the rig PC has had unexpected shutdowns.
