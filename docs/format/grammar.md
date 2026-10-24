# Protocol, illumination and recipe scripts — grammar, DRAFT v0

Status: **living draft**, written 2026-10-24 at the owner's request: "최종화 하기에는 개발 과정에서 계속 변경이 있을듯. 우선은
현재 상태로 작성해볼것". It will change during phase 5 development; every change bumps the grammar version (section 9).
Sources: [ui-requirements.md](../spec/ui-requirements.md) U10, U18, U19, U24, U36; decisions
[0012](../decisions/0012-automation-partial-first.md), [0013](../decisions/0013-mt-tirf-extensible-illumination.md),
[0015](../decisions/0015-extension-architecture.md); the function layer [design/api.md](../design/api.md).

The scripts are **plain text with a fixed grammar, parsed deterministically by the program** (not interpreted by AI).
The GUI block editor and the script editor show the same file; anything a block can do, a line can do, and vice versa.

## 1. Three kinds of file, one grammar
| Kind | Extension | Says |
|---|---|---|
| Protocol (experiment or screening) | `.mtprot` | what the magnet, rotor, focus, recording do over time, and the rules |
| Illumination sequence | `.mtseq` | which light is on for each EMCCD frame (header / body / footer) |
| Analysis recipe | `.mtrec` | which signals and observables, which spots, which events, what to export |

An **experiment bundle** (`.mtexp`, U36) is a folder or zip of one of each plus presets.

## 2. Lexical rules
- One statement per line. `#` starts a comment. Blank lines are ignored. Indentation is free (shown for reading).
- First non-comment line: `grammar 0.1` (the version the file was written for).
- Keywords are lower case. Names (protocols, observables) are `[A-Za-z][A-Za-z0-9_]*` or a quoted string.
- Arguments are `key=value`, in any order. Numbers are decimal (`7`, `1.5`, `-10`). Booleans `on` / `off`.
- **Units are fixed per key and never written in the value**: forces `f`, `from`, `to` in pN (on `ramp` / `hold`);
  time `t`, `timeout` in s; turns in turns; positions in mm (magnet) or µm (focus); rates in Hz. The key table
  (sections 3-5) states the unit of every key. A value with a unit suffix (`7pN`) is an error, so units cannot be
  mixed up silently.
- Ranges are checked twice: by the grammar (fixed limits in the tables) and by the **rig safety profile** at check time
  (0015). A value outside either is an error, never clamped.

## 3. Protocols (`.mtprot`)

### 3.1 Header
```
grammar 0.1
protocol "Force-extension + rotation"
kind experiment            # experiment | screening
```

### 3.2 Action statements
| Statement | Keys (unit, range) | Meaning |
|---|---|---|
| `zero t=` | t (s, 0.1-600) | magnet to zero force, hold, then set the zero (U12) |
| `ramp from= to= t=` | from, to (pN, 0-profile max); t (s, 0.1-36000) | force ramp |
| `hold f= t=` | f (pN); t (s) | constant force |
| `move mm= t=` | mm (magnet position, mm); t (s, optional) | magnet by position instead of force |
| `rotate from= to= f= t=` | from, to (turns, ±profile max); f (pN); t (s) | rotation at a force |
| `focus um= ` | um (µm, relative to start, ±profile window) | focus step (U35; use sparingly) |
| `record t=` / `record on` / `record off` | t (s) | recording on for a time, or switch |
| `light seq="name"` / `light off` | seq (name of an `.mtseq`) | start / stop an illumination sequence (MT-TIRF) |
| `mark "text"` | | free-text event in the data |
| `wait t=` | t (s) | wait |

### 3.3 Structure
```
loop n=3                   # repeat the enclosed lines n times
  ...
end
if <expr>                  # conditional step (0012); <expr> see section 6
  ...
else
  ...
end
wait until <expr> timeout=120   # wait for a condition; on timeout: continue (default) or `then stop`
on <expr> do               # event handler, active until the protocol ends
  mark "cleaved"
end
stop                       # end the protocol here
```
`repeat n` at the end of a file (as in the mock-up) is shorthand for wrapping the whole list in `loop n=`.

### 3.4 Screening rules (in `kind screening`)
```
rule dext_0_7 >= 0.8       # metric, comparison (>= <= > < == !=), threshold
rule angle_deg <= 20
rule circularity >= 0.8
rule multi_tether == 0
rule rel(extension_7pN) within 0.2   # relative to the field median (U10): within ±20 %
```
Each failed rule becomes the bead's reason. Metrics come from the metric library (section 7); new metrics are
plug-ins (0015).

### 3.5 Mid-run edits (U18)
Edits are applied to the file as a new version; the engine applies them from the next step not yet started (from the
next loop for steps already done this loop). The running step is locked. Both versions are stored with the data.

## 4. Illumination sequences (`.mtseq`)
```
grammar 0.1
sequence "Green with red every 10th"
lights 532 637             # columns, in this order (nm, from the rig preset)
ratio n=3                  # JAI frames per EMCCD frame (0005)
header
  frame 532=off 637=off    # dark frame
end
body repeat=100
  frame 532=on 637=off  count=9
  frame 532=off 637=on
end
footer
  frame 532=off 637=on
end
```
- `frame` sets every listed light; `count=` repeats a row. Rows are EMCCD frames.
- Checked before a run: switching time of the chosen back-end vs the EMCCD frame period (U24).
- ShutterManager files (`000`, `010`, ... per line) are imported into this form.

## 5. Analysis recipes (`.mtrec`)
```
grammar 0.1
recipe "Enzyme cleavage time"
signals dd da aa bg baf     # donor-ex donor, donor-ex acceptor, acceptor-ex acceptor, background, bead autofluor.
observable E = fret(dd, da, alpha=0.07, delta=0.05, gamma=1.0)
observable cy3 = present(dd, k=4)     # on/off: above background by k noise sd, step-checked
observable cy5 = present(aa, k=4)
select at_start(cy3 and cy5)          # spots kept
event cleavage when cy3 and fell(cy5)
export events to matlab
export traces E cy3 cy5 to hdf5
```
- `observable` defines a named quantity from signals with library functions (section 7).
- `select` keeps spots; `event ... when ...` records times; `export` sends results.
- The same file runs live (on the incoming data) or afterwards on a saved run.

## 6. Expressions (in `if`, `wait until`, `on`, `rule`, `select`, `event`)
```
expr    := term { ("and" | "or") term }
term    := ["not"] factor
factor  := comparison | call | name | "(" expr ")"
comparison := value op value       op: >= <= > < == !=
value   := number | name | call
call    := name "(" args ")"
```
Names refer to live quantities: `force_pN`, `extension_um`, `z_um(bead)`, `turns`, `t_s` (since protocol start),
observables from the recipe, and counts such as `fraction(event cleavage)`. Example:
`wait until fraction(event cleavage) >= 0.5 timeout=1800`.

## 7. Library functions (first set)
| Function | Meaning |
|---|---|
| `fret(dd, da, alpha=, delta=, gamma=)` | corrected FRET efficiency (formula to match smCamera, pending; U28) |
| `present(sig, k=)` | on / off by threshold and step detection |
| `fell(x)` / `rose(x)` | true at the frame where a boolean switches off / on |
| `mean(x, t=)` / `sd(x, t=)` | running mean / standard deviation over t seconds |
| `rel(x)` | x relative to the median over the field |
| `at_start(expr)` | expr evaluated at the start of recording |
| `fraction(event e)` | share of selected spots / beads with event e so far |
Metrics for screening (`dext_0_7`, `angle_deg`, `circularity`, `multi_tether`, `hat_symmetry`, `z_noise_7pN`, ...)
are defined in the metric library with their units; the list grows by plug-ins.

## 8. Errors
`<file>:<line>:<column>: <message>` with a plain-language message and the allowed range when a value is outside it,
e.g. `fe-ramp.mtprot:6:12: 'to' is 12 pN; the rig safety profile allows 0-10 pN`. A file with any error cannot run.
The checker also reports the run time, number of EMCCD frames, total light-on time and data size before a run.

## 9. Versioning
- The grammar version in the first line selects the parser. A new version keeps older files readable (with
  warnings) for at least one release.
- Every run stores the files used, their grammar version and a hash (0015 item 4).

## 10. Mapping to the API
Each statement is one or a few calls of the public function layer ([design/api.md](../design/api.md)), e.g.
`ramp` -> `api.magnet.set_force(...)` steps; `light seq=` -> `api.light.load_sequence` + `start_sequence`;
`on <expr> do` -> `api.events.on(...)`. A Python experiment script (level 3) can do anything a script can and more.

## 11. Examples
**3-state force clamp × 10 (replaces LabVIEW's CycleSchedule):**
```
grammar 0.1
protocol "3-state clamp x10"
kind experiment
zero t=5
record on
loop n=10
  hold f=0.5 t=30
  hold f=3 t=30
  hold f=7 t=10
end
record off
```
**Single-biotin screening (owner's criteria, U10):**
```
grammar 0.1
protocol "Single-biotin (SiHyeong)"
kind screening
zero t=5
ramp from=0 to=7 t=10
hold f=7 t=5
rotate from=-10 to=10 f=1.5 t=40
rule dext_0_7 >= 0.8
rule angle_deg <= 20
rule circularity >= 0.8
rule multi_tether == 0
```

## 12. WP5 decisions (implemented 2026-10-24, grammar 0.1, `mtpy.protocol`; open to change with the draft)
Where the draft left a point open, WP5 chose the simplest safe option. Each is marked so it can be revisited.
1. **Header.** The first non-comment line is `grammar 0.1`; the second names the script (`protocol` / `sequence` /
   `recipe` + a word or a quoted string). A file with an `.mt*` extension must match its kind (`.mtprot`, `.mtseq`,
   `.mtrec`). `kind` is optional (default `experiment`), at most once, before the first action.
2. **Ranges the draft did not give** (grammar check; the rig safety profile is checked on top): `hold`, `wait`,
   `move` t 0-36000 s; `record t=` and `rotate t=` 0.1-36000 s; every force >= 0 pN; `loop n=` / `repeat n` whole
   numbers 1-10000; `wait until ... timeout=` more than 0 and at most 86400 s; `ratio n=` 1-65536 (as
   `api.sync.set_ratio`); `body repeat=` and `count=` 1-10^7. `rotate` needs `from` != `to`.
3. **Expressions:** `and` binds tighter than `or`; `not` applies to one term; `within` is a comparison only in
   `rule`. A call argument may be `key=value` or `event <name>`.
4. **Errors:** every error of the file is reported (not only the first), sorted by line and column; the column of a
   bad value is the value's. A block opener with an error still opens its block, so its `end` matches. A frame must
   set every listed light (`'frame' needs 637=`).
5. **What runs:** `zero`, `ramp`, `hold`, `move`, `rotate`, `focus`, `record`, `mark`, `wait t=`, `loop`,
   `repeat`, `stop`. The checker maps each statement to public API functions by name; `light seq=` / `light off`
   (`api.light.load_sequence` / `start_sequence` / `stop_sequence`), `if`, `wait until`, `on`
   (`api.events.rule` / `wait_for` / `on`) are parsed but **fail the check** because those functions do not exist
   yet; they become runnable when the API has them (no change to the checker's rule).
6. **Screening rules** are parsed but **not evaluated** (no `api.screen`, no metric library yet): a check warning,
   and the run's `protocol` start event says `rules_evaluated: false`. Metric names are not checked yet.
7. **`zero t=`** moves the magnet to 0 mm (top, the lowest force) and holds t; it does **not** set the tracking zero
   (`api.tracking.zero` does not exist yet) - the step's end event says so. Owner to confirm what "zero force" means
   (0 mm, or the force table's lowest force).
8. **`ramp`** is a staircase through `api.magnet.set_force`: first `from`, then ceil(t / ramp step) increments
   (ramp step 0.5 s by default, `api.protocol.run(ramp_step_s=)`), each after its interval and each waited for until
   it arrives; the real duration is t plus the move times.
9. **`hold f= t=`**: t counts from the arrival at f. **`move mm= t=`**: t is the hold after arrival (not the move
   duration); the speed is the controller's, checked by `api.magnet.move_to`.
10. **`rotate from= to= f= t=`**: from / to are turns relative to the session-start position (the frame of the
    profile's `rotor_turns` window). The engine sets the force, goes to `from`, then to `to`, both at speed
    |to - from| / t, which is always passed explicitly so `rotor_speed_turns_s` is always checked.
11. **`focus um=`** is relative to the focus position read when the protocol starts.
12. **`record`** needs acquisition already running (`api.acq.start`); the protocol never starts or stops
    acquisition. The recording name is the protocol name; `record t=` is on, t, off.
13. **`mark`** uses `api.acq.mark` (with the frame position) while acquisition runs, else a `mark` event.
14. **Check before the run, in three layers:** the API (functions and the unit in each parameter's name), the rig
    safety profile (every value; every magnet move also needs a usable `magnet_speed_mm_s` maximum, so with profile v1
    every magnet statement fails the check), and at `run()` the rig state (devices connected, a force table loaded that
    covers every force and maps it inside the magnet travel, the focus target from the current position, acquisition
    running for `record`). Values that depend on the run are checked again by the API at each step.
15. **Run behaviour:** one protocol at a time, on its own thread, only through `mtpy.api`, caller
    `script:<name>@<first 12 hex of the sha256>`. A refused step ends the run (`refused`); a device error, time-out
    or other API error ends it (`failed`); nothing is skipped. Each move is waited for up to 120 s
    (`motion_timeout_s`). **Pause** stops the protocol clock in holds, waits and ramp intervals (within ~20 ms); a
    move already sent finishes. **Stop** cancels the running move in place and changes nothing else (0007). The
    **emergency stop** ends the run as `aborted`; it is never resumed, also not after the release. Review
    l2s-wp5-r1: the whole run is inside `api.estop.run_scope`, so after an emergency stop no request of the run is
    sent, even one made after the release (both the run's and the request's generation must be current, before and
    after each send); a second `run()` while one runs is refused (NotReady + `refused` event) and never replaces it.
16. **Mid-run edits (section 3.5, minimal; restricted by review l2s-wp5-r1):** only **in-place value edits** are
    allowed: the new version must keep the count, kind, form and nesting of every statement (values such as `n=`,
    `f=`, `t=`, a mark text may change). `api.protocol.edit(draft)` refuses any structural change - a statement
    inserted, deleted or moved anywhere, also an identical repeated line and also a step added after the running
    position - with a `ScriptError` naming the line and a `protocol_edit` refused event; it then checks the new
    version fully (rig state; the focus reference is the one the run started with, and a focus step in a run that had
    none is refused). `apply_edits()` hands it to the engine, which applies it at the next step or loop-pass boundary
    (re-checking the structure): steps not started take it now, steps done in this loop pass from the next pass, the
    running step is locked. Both texts are in the `protocol_edit` event; the version number counts applied edits.
    Structural edits and statement identity are for the phase 8 editor.
17. **Events:** `protocol` (start with the text and sha256, pause, resume, stop_requested, end with the state),
    `protocol_step` (phase start / end / refused / failed / stopped / aborted / completed, with step number, line,
    statement, loop pass, protocol version and target) and `protocol_edit` (applied / refused). While recording they
    reach the HDF5 `/events` like every other event.

## 13. Open
- Exact metric names and the event-rule functions (grows with use).
- Whether `on ... do` may move hardware (today: yes, through the safety layer) or only mark / stop.
- Block-editor representation of `if` / `on` (visual design, phase 8).
- How a protocol references an illumination sequence and a recipe inside a bundle (paths vs names).
- smCamera's FRET formula for `fret()`.
- (WP5) What `zero` means as a magnet target (0 mm or the table's lowest force), and when the tracking zero is set.
- (WP5) Whether `stop` / the end of a protocol should switch recording off (today: left as it is, 0007).
- (WP5) Structural mid-run edits (insert / delete / move a step, also adding steps after the running one) are
  refused today, so U18 is only partly met (values only); owner to confirm that this is enough until phase 8.
- (WP5) `zero` is not accepted as meeting U12 (it sets no tracking zero); owner to confirm its meaning.
