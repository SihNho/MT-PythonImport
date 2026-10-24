# Walking skeleton (WP6) - how to run it

Simulators and files only: no camera, motor, serial port or LabVIEW is touched, and no rig lock is needed. The run
uses a TEST-ONLY rig safety profile that lives only in its output folder; the shipped `config/` is never written
(its sha256 is checked before and after).

## Run
```
.venv\Scripts\python.exe tools\walking_skeleton.py --out <empty folder>            # protocol run
.venv\Scripts\python.exe tools\walking_skeleton.py --out <empty folder> --estop    # e-stop during a magnet move
```
Options: `--fixture <folder>` with `img*.tif` and `cal002` (default: the G: fixture of `tests/conftest.py`, or the
folder named by `MTPY_DATA` + `\test`). Without a `cal002` the run stops at its first check (beads need a `.cal`).
About 10-15 s per run. Each check prints `PASS` / `FAIL`; the last line is `RESULT {...}` (ok, number of checks, the
failed ones, frames, file paths); exit code 0 when everything passed.

As a test: `.venv\Scripts\python.exe -m pytest tests\test_walking_skeleton.py` (both variants; skips without the
fixture).

## What it leaves in the output folder
- `config/` - the copy used as the active profile folder, with the TEST-ONLY `safety_profiles/4.json`;
- `<name>.mtprot` - the protocol that ran (`skeleton` or `skeleton_estop`);
- `<name>.h5` and `<name>.meta.json` - the run file and its metadata copy;
- `<name>-000` - the `.tra` export; `<name>.cal` - the `.cal` export (byte-identical to `cal002`).

A second run into the same folder is refused before anything is written (`<out>/config` exists; a config folder is
never deleted or replaced), and so is any `--out` whose `config` would be, lie inside or contain the repository's
`config/`: use a new folder outside the repository's `config/`.

## Steps and checks
See the module docstring of `tools/walking_skeleton.py` and "Implemented in WP6" in
[docs/design/api.md](../docs/design/api.md). Not covered here (hardware / other tools): the 15 mm/s magnet check on the
rig and the MATLAB 2026 run of `matlab/read_mtpy_h5.m`.
