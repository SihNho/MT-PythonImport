# Shutdown sequence (decision 0026; owner 2026-10-30: "종료할 때 기계 disconnect 해주는 프로토콜")

What happens when the operator presses Disconnect or closes the window while devices are connected. The sequence is
`mtpy.gui.shutdown.steps()`; the API side is `api.devices.close(name)` / `disconnect()` with `CLOSE_ORDER`.

| # | step | done when | on failure |
|---|---|---|---|
| 1 | stop the protocol | `protocol.wait` returns | sequence stops |
| 2 | stop acquisition | `acq.stop` returned; the run file is closed | sequence stops |
| 3 | close magnet (PI) | at 0 mm within 0.01 mm, TMN/TMX back to 0/52, port closed | limits NOT released; the port and the session limits are kept, and the retry homes again on the same session (never a re-open or a reference move; fault list D1, owner 2026-10-31) |
| 4 | close rotor (Autonics) | port closed (position kept) | retry |
| 5 | close stage (ASI X/Y) | SL/SU released, port closed | retry |
| 6 | close focus (ASI Z) | SL/SU Z unchanged since open, port closed | retry |
| 7 | close emccd (iXon) | acquisition aborted, shutter closed, cooler off, sensor warmer than -20 C, ShutDown | sensor still cold after 15 min: cooler stays off, retry waits again |
| 8 | close camera (JAI) | IMAQdx session closed | retry |
| 9 | close arduino, light | ports closed | retry |
| 10 | release the rig lock | every device gone from `devices.status()`; `riglock.release` | not reached while any step failed |

Rules: one step at a time on a worker thread; the dialog ticks each step and the window stays open. The first
failure stops the sequence and the dialog shows the error with **Retry** (runs the remaining steps again; a device
whose service thread ended with the failure is rebuilt, opened and closed again) and **Close anyway**. "Close anyway"
ends the program with the rig lock still held by a process that is now gone: the lock file then reads STALE, which is
the recovery path of `G:\Codes\rig\RULES.md` (a person checks the devices and limits before taking it over). The event
log records `gui closed_uncleaned` with the devices left.

Order rationale: the magnet first (the only device that can hold force on the sample), motors before cameras (their
cleanup writes to controllers and must be seen), the iXon before the JAI (its warm-up is the long step, the JAI close
is instant), the lock last.

Not in this version: a live sensor-temperature readout during the iXon step (the step label says what it waits for),
a timeout on a hung step (the service's own reply timeout applies), and recovery after a crash.
