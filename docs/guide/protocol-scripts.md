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
`mm` in mm, `um` in um. `7pN` is an error, so units are never mixed up silently.

## 2. What each statement does on the rig

| Line | The program does |
|---|---|
| `hold f=F t=T` | the force calibration (M270 v3, from the touch position set in Setup) gives the magnet position for F pN; the magnet moves there through the motion gate; then T seconds pass |
| `ramp from=A to=B t=T` | the magnet goes to the position of A, then moves to the position of B at the speed that takes T seconds (`speed=` mm/s instead of `t=` is allowed). A speed above the profile's magnet limit is lowered to the limit and logged as `coerced` |
| `move mm=X t=T` | the magnet to X mm directly (no force), then T seconds |
| `zero t=T` | the magnet to 0 mm (the top, no force), T seconds. It does NOT set the tracking zero |
| `rotate from=A to=B f=F t=T` | force F, the rotor to A turns (from its origin), then to B turns at (B-A)/T turns/s |
| `focus um=X` | the focus by X um from the run's start |
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

Each column is one step: Force (pN), Wait (s), Motor (mm/s), Rotor (degree), Rotor speed (SPD). A column
compiles to: a `ramp` to the force at the motor speed (or `hold` when the speed is 0), a `rotate` by the degrees at
the SPD (turns/s = SPD x 10 / 500), then a `hold` for the wait. Start from table compiles and starts.
