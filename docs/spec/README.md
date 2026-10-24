# Behavior specification

What the LabVIEW program `Min_Track N beads 4.5_KimLabMTroom_3StateClamping.vi` does, written so the Python port
can be built and checked against it. Decision [0009](../decisions/0009-development-method.md) sets the form;
decision [0008](../decisions/0008-odd-behaviors-of-the-original.md) sets what may change.

## Files

| file | step of the experiment flow |
|---|---|
| [0-startup-and-shared.md](0-startup-and-shared.md) | program structure, device start-up, shared state, error handling |
| [1-live-view-and-motors.md](1-live-view-and-motors.md) | live image, manual focus, magnet and rotor commands |
| [2-bead-picking.md](2-bead-picking.md) | clicking beads, overlay, reference bead |
| [3-calibration.md](3-calibration.md) | Z scan, radial profiles, `.cal` file |
| [4-experiment.md](4-experiment.md) | tracking, lost beads, autofocus, cycle schedule (3-state clamping), plots, trace writing |
| [5-save-and-stop.md](5-save-and-stop.md) | stop paths, final save, shutdown |
| [coverage.md](coverage.md) | every front-panel object and every case / event frame, mapped to a feature |
| [questions-for-owner.md](questions-for-owner.md) | what only the owner can answer |

File formats are in [../format/](../format/).

## Feature IDs

`F<step>.<nn>`, e.g. `F4.05`: step 0–5 as in the file names, two-digit number within the step. An ID is never
reused or renumbered; a dropped feature keeps its heading with **Port: drop**.

Each feature is one heading of the form `### F4.05 — <name>`. [tools/spec_coverage.py](../../tools/spec_coverage.py)
reads these headings.

## Feature form

Every feature lists these fields, in this order. A field that does not apply says `none`; a field that is not
known says `unknown — <what would settle it>`.

- **Trigger** — what starts it (button, loop iteration, schedule state, start-up frame).
- **Inputs** — panel controls, files, device readings.
- **Steps** — what happens, in order.
- **Outputs** — indicators, files, values handed to other features.
- **Moves hardware?** — `no`, or which axis / device and by which call.
- **Timing and errors** — loop, rate, waits, what happens on an error.
- **Evidence** — source and level (below).
- **Owner's intent** — the owner's own words when we have them; otherwise `ask` with a question ID.
- **Port** — `port` (reproduce as is), `change` (an intentional change, with the reason), or `drop` (with wiring
  evidence that it is unreachable or with the owner's decision).

## Evidence levels

| level | meaning |
|---|---|
| **wiring** | read from the VI's diagram: nodes, terminals, wires, constants (V6 measurements on the VI) |
| **text** | a label, comment, file name or string; or a meaning inferred from names (marked *inferred*) |
| **owner** | the owner's own statement, with date and source |
| **data** | read from a recorded file (`.tra`, `.cal`, images) |

## Sources

All evidence comes from documents and files already produced by the LabVIEW project (V6). No VI was opened for
this specification. `V6:` below means
`G:\Codes\LabVIEW_Codes\MinLab\zz_LabView VI\AAA_UNIST\2. Tracking\V6_ParallelLoop\`.

- The diagram facts were measured on **the working copy** `Min_Track N beads V6_ParallelLoop.vi` (md5
  `2a78e17c449cacdaf5da389818526859`), cloned from 4.5. The only recorded difference is the fixture insertion of
  four nodes on the frame loop (an `IMAQ Write TIFF File 2` and its path nodes, `V6:docs/fixture-recording.md`);
  they are not part of the original and not specified here. The motion census found the same 170 diagrams and
  the same call sites on the original 4.5 (`V6:docs/motor-call-site-census.md` count table).
- **Diagram numbers** `D<n>` are the V6 Traverse indices 0–169 (`V6:tools/bench/diagram_tree_main.json`,
  `V6:tools/bench/main_vi_netmap.json`). They are an enumeration order, not execution order.
- `uid` numbers are LabVIEW object IDs on that copy.
