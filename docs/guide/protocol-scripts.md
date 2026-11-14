# Protocol scripts: how the words become motor motion

Owner 2026-11-05: "material on the script grammar is needed (how near-natural language drives the actual motors)".
This is the user's guide; the full grammar with every key and range is [format/grammar.md](../format/grammar.md).
Korean: [protocol-scripts.ko.md](protocol-scripts.ko.md).

## 1. One line is one action, in order

A protocol is plain text, one statement per line, run from top to bottom. Nothing is interpreted by AI: the program
parses the lines with a fixed grammar (`src/mtpy/protocol/grammar.py`), checks every value (`check.py`), then runs
them one after another (`engine.py`). The Experiment table (rows = parameters, columns = iterations, as the LabVIEW
table) compiles to the same lines; the text box shows them.

```
grammar 0.1
protocol "example"
hold f=1 t=2            # 1 pN for 2 s
ramp from=1 to=5 t=5    # 1 -> 5 pN over 5 s
mark "high force"       # a text event in the data
hold f=5 t=2
zero t=1                # magnet to 0 mm (the top), 1 s
end protocol
```

Units are fixed per key and never written: `f`, `from`, `to` in pN (on `hold` / `ramp`), `t` in s, turns in turns,
`mm` in mm, `um` in um, the `x` / `y` of `stage` in um. `7pN` is an error, so units are never mixed up silently.

## 2. What each statement does on the rig

| Line | The program does |
|---|---|
| `hold f=F t=T` | the force calibration (M270 v3, from the touch position set in Setup) gives the magnet position for F pN; the magnet moves there through the motion gate; then T seconds pass |
| `ramp from=A to=B t=T` | the magnet goes to the position of A, then moves to the position of B at the speed that takes T seconds (`speed=` mm/s or `rate=` pN/s instead of `t=` is allowed; `rate=` is the true loading rate: one magnet move whose speed is set again every 0.1 s from the position read back, rate / the calibration's slope there, so the motor speeds up towards the touch position and slows away from it; where the slope is too small for the rate the speed is capped at the profile's maximum and logged as `coerced`). A speed above the profile's magnet limit is lowered to the limit and logged as `coerced` |
| `move mm=X t=T` | the magnet to X mm directly (no force), then T seconds |
| `zero t=T` | the magnet to 0 mm (the top, no force), T seconds. It does NOT set the tracking zero |
| `rotate from=A to=B f=F t=T` | force F, the rotor to A turns (from its origin), then to B turns at (B-A)/T turns/s; `speed=` turns/s or `spd=` (the rotor's SPD setting, turns/s = SPD x 10 / 500) instead of `t=` is allowed |
| `loading magnet` / `loading force` | a header line (after `protocol`): the ramps are written by magnet speed (`speed=`) or by force rate (`rate=`); a ramp written the other way is a Check warning. The table writes it from its Loading choice |
| `focus um=X` | the focus to X um from its position at the protocol's start (not from the last step); `t=T` adds a wait of T seconds after the move; `speed=V` (um/s, owner 2026-11-14) makes this one move a slow ramp of the piezo: a speed above the one the piezo opened with is lowered to it (`coerced`), a very low one is rounded by the controller, and the old speed is put back after the move. The position is recorded per frame (`/mt/focus_um`, read at 10 Hz) |
| `stage x=X y=Y` | the sample stage to (X, Y) um from its position at the protocol's start (not from the last step; each within +-1000); `t=T` adds a wait. Every move's read-back is an `act` event (`stage_xy_mm`, mm) in the run file; the stage position is recorded per frame (`/mt/stage_x_mm`, `/mt/stage_y_mm`, read at 5 Hz) |
| `autofocus on` / `autofocus off` | the autofocus on or off (no value: the reference bead and the target, a percent of the LUT, are set in the program). Write `autofocus off` before `focus` steps: with the autofocus on, it pulls the focus back (a warning event says so) |
| `record on` / `record off` / `record t=T` | recording into the run file on, off, or on for T seconds |
| `mark "text"` | a text event in the run file |
| `wait t=T` | T seconds, nothing moves |
| `loop n=N ... end` | the enclosed lines N times |
| `end protocol` | the end (the magnet stays where it is) |

A force outside what the magnet can reach inside its position limit is moved to the nearest reachable force and
logged as `coerced` (decision 0018). A time of 0 is allowed (`hold f=5 t=0`: just go there).

## 3. Check before Start

**Check** runs the three layers without moving anything and lists every problem with its line number:
1. the grammar: unknown words, missing keys, a value outside the fixed range of the key;
2. the API and the rig safety profile (Setup shows the file and every limit): a force, position, speed or turn count
   the profile refuses; a speed the profile will lower;
3. the rig's state: devices connected, the force calibration ready (touch position set).

**Start** runs Check first and refuses on any error. Start while a protocol runs ends that one and runs the new one;
the top bar badge shows `PROTOCOL running (name)`.

## 4. While it runs

- **Pause / Resume**: the waits stop counting; a move in progress finishes.
- **Stop** (Experiment): the protocol ends after the current move stops in place. The magnet stays.
- **STOP** (top bar, red): the emergency stop - every motor halts and every move is refused until Acknowledge.
- **Apply edits**: changed values take effect at the next statement boundary; adding, removing or reordering
  statements while it runs is refused (Stop, then Start the new text).
- Every statement and every move is an event in the run file (`events/protocol`, `events/protocol_step`), with
  the line number, so a trace can be read against its protocol afterwards.

## 5. The table

Each column is one step: Force (pN), Wait (s), Loading, Rotor (degree), Rotor speed (SPD), Focus (um). **Focus** (owner 2026-11-12) is the offset from the protocol's start, as `focus um=`: a column whose value differs from the previous one moves the focus after the force change and before the wait. **Loading** (the
choice above the table) is either Motor (mm/s), the magnet loading rate of the LabVIEW experiments, or Force rate
(pN/s), the force loading rate: one or the other for the whole table. A column compiles to: a `ramp` to the force
at the loading value (`speed=` or `rate=`; `hold` when it is 0), a `rotate` by the degrees at the SPD
(turns/s = SPD x 10 / 500), then a `hold` for the wait. Start from table compiles and starts.

## 6. Examples: the piezo and the stage (2026-11-12 / 13)

**Piezo steps at a fixed force** (the bead calibration's accuracy). `focus um=` counts from the position at the
protocol's start; the focus position is recorded per frame in the run file (`/mt/focus_um`). A piezo move changes the
z of the reference bead and of the tethered bead together, so compare each bead's z change with the piezo's.

```
grammar 0.1
protocol "piezo steps at 10 pN"
loading force
autofocus off          # otherwise the autofocus pulls the focus back
record on
hold f=10 t=30
focus um=0.1 t=10      # 100 nm above the start, then 10 s
focus um=0.2 t=10
focus um=0.3 t=10
focus um=0 t=10        # back to the start
record off
autofocus on
end protocol
```

`autofocus on` uses the target set on the Run page (percent of the LUT, default 30) and the tracked reference bead;
without a reference bead the protocol fails at that line.

**Stage x / y moves** (e.g. a known step under a tracked reference bead gives the pixel size). `stage x= y=` also
counts from the position at the protocol's start, each within +-1000 um; every move's read-back is an `act` event
(`stage_xy_mm`, mm). Keep the step to a few um so the bead stays inside its tracking ROI. The table has no `stage`,
`autofocus` or `record` row: write them in the script.

```
grammar 0.1
protocol "pixel size"
record on
wait t=5
stage x=5 y=0 t=5      # 5 um in x from the start, then 5 s
stage x=0 y=0 t=5
stage x=0 y=5 t=5
stage x=0 y=0 t=5
record off
end protocol
```
