# HDF5 file, schema v1 — DRAFT

**Status: draft for the owner's review** (plan phase 2). Decision [0006](../decisions/0006-data-format.md) sets the
layers and tables; this page names every field. The `.tra` and `.cal` files are still written, byte-identical
([tra-cal.md](tra-cal.md)); the HDF5 file is written alongside them, one per run.

## Conventions

- File name: the `.tra` base name with `.h5` (e.g. `tra002.h5`); one file per run, not split.
- Text: UTF-8 (unlike `.tra` / `.cal`). Times: seconds as float64 unless stated.
- Every table is a group of **1-D or 2-D datasets of equal first length** (one dataset per column), chunked and
  extendible along the first axis. Plain numeric datasets read directly with MATLAB `h5read`; MATLAB shows 2-D
  datasets transposed (beads × frames).
- Per-bead columns are 2-D: `[n_frames, n_beads]`; bead index 0 = the first click = the reference bead.
- Missing value: NaN for floats, −1 for signed integers. The `.tra` markers (−1 for a lost bead, 5.9 at the top of
  the calibration range) are kept in `raw` and flagged, never silently replaced.
- Every dataset carries the attributes `unit` (string, `1` for dimensionless) and `description`.

## Root

| attribute | dtype | meaning |
|---|---|---|
| `schema_version` | string | `"1.0"` — changes when a field is added (minor) or changed / removed (major) |
| `file_kind` | string | `"mtpy-run"` |
| `created_utc` | string | ISO 8601 time the file was opened |
| `closed_cleanly` | uint8 | 0 while writing, 1 after a normal close (crash detection, decision 0007) |
| `legacy_tra_files` | string array | paths of the `.tra` files of this run |
| `legacy_cal_file` | string | path of the `.cal` file used |

## `/provenance` — how the data were made

| dataset / attribute | dtype | unit | meaning | source |
|---|---|---|---|---|
| `software_name`, `software_version`, `git_commit` | string | — | the application build | package metadata |
| `tracking_stages` | string (JSON) | — | the stage combination used (decision 0003), e.g. `{"xy": "labview-crosscorr", "z": "labview-radial"}` | tracking configuration |
| `parameters` | string (JSON) | — | every run setting, by the original control names where one exists (`Cross length (pixels)`, `Limit of Auto-Focus`, `Frame rate` as autofocus period, …) | GUI state at start |
| `calibration/xy_px` | float64 `[n_beads, 2]` | px | picked bead x, y | `.cal` `x,y pos array` |
| `calibration/stack` | float64 `[n_beads, S, L]` | a.u. | radial-profile stack | `.cal` `cal image array` |
| `calibration/z_step_um` | float64 | µm | slice step, as stored in the `.cal` (single precision widened) | `.cal` |
| `calibration/n_avg` | int32 | 1 | frames averaged per slice | `.cal` |
| `calibration/bandpass_forget` | int32 `[n_beads, 3]` | 1 | per-bead bandpass / forget values | `.cal` |
| `calibration/exp_ref` | int32 `[n_beads]` | 1 | 0 = reference, 1 = experiment (*inferred* meaning) | `.cal` |
| `calibration/nm_per_px` | float64 | nm/px | pixel size | `.cal` `Pixel distance` |
| `calibration/sha256` | string | — | hash of the `.cal` file | computed |
| `rig/camera`, `rig/emccd` | string (JSON) | — | model, serial, ROI, binning, exposure, frame rate as read from the device | device layer |
| `rig/magnet_force_model` | string | — | force calibration used for derived force (e.g. `Magnet2Force v3_for M270`) | configuration |

## `/mt` — one row per JAI frame

| dataset | dtype | unit | meaning | source |
|---|---|---|---|---|
| `buffer_number` | uint64 | 1 | absolute camera buffer number (decision 0005) | camera driver |
| `frame` | int64 | 1 | `buffer_number − first buffer number` — identical to `.tra` column 0 | computed |
| `lost_before` | uint32 | 1 | frames lost between this row and the previous one (0 = none) | buffer numbers |
| `t_host` | float64 | s | host clock when the frame was received, from the run start | host clock |
| `t_camera` | uint64 | camera ticks | camera timestamp, if the camera provides one (*open*: tick unit) | camera driver |
| `magnet_mm` | float64 | mm | last magnet position read — identical to `.tra` column 1 | motor thread |
| `magnet_t` | float64 | s | host time of that magnet reading | motor thread |
| `rotor_deg` | float64 | deg | last rotor angle read (signed) — `.tra` column 2 | rotor thread |
| `rotor_t` | float64 | s | host time of that rotor reading | rotor thread |
| `focus_pos` | float64 | ASI internal units | last focus position read | ASI thread |
| `focus_t` | float64 | s | host time of that focus reading | ASI thread |
| `x_px`, `y_px` | float64 `[n, n_beads]` | px | bead position — `.tra` columns 3 + 3i, 4 + 3i | tracking |
| `z_um` | float64 `[n, n_beads]` | µm | bead height (the `.tra` header's "nm" is wrong, decision 0008) — `.tra` column 5 + 3i | tracking |
| `cal_slice` | int32 `[n, n_beads]` | 1 | index of the closest calibration slice (`pos in cal image out`); −1 = lost | tracking |
| `bead_good` | uint8 `[n, n_beads]` | 1 | the kernel's good flag | tracking |
| `bead_lost` | uint8 `[n, n_beads]` | 1 | 1 when the kernel returned the lost marker | tracking |
| `reseed` | uint8 | 1 | 1 when this frame started from the calibration positions (F4.05) | tracking |
| `autofocus_move` | float64 | ASI internal units | relative focus move commanded at this frame, NaN if none (F4.06) | scheduler |
| `schedule_column` | int32 | 1 | current `CycleSchedule` column, −1 outside cycling (F4.08) | scheduler |
| `schedule_cycle` | int32 | 1 | current cycle number, −1 outside cycling | scheduler |
| `clamp_state` | uint8 | 1 | scheduler state (enum stored as attribute `states`; names fixed after Q4.08) | scheduler |
| `emccd_frame` | int64 | 1 | EMCCD frame exposed during this JAI frame, −1 if none | sync (decision 0005) |
| `laser_state` | uint8 | 1 | laser on / off (enum attribute) | laser thread |

## `/fluorescence` — one row per EMCCD frame (absent without an EMCCD)

| dataset | dtype | unit | meaning | source |
|---|---|---|---|---|
| `emccd_frame` | int64 | 1 | EMCCD frame number from 0 | iXon driver |
| `jai_first_buffer`, `jai_last_buffer` | uint64 | 1 | first and last JAI buffer number during its exposure | sync |
| `t_host` | float64 | s | host time of arrival | host clock |
| `exposure_s` | float64 | s | exposure time | iXon driver |
| `laser_state` | uint8 | 1 | laser state during the exposure | laser thread |
| `images` | uint16 `[n, H, W]` | counts | raw EMCCD frames (saved in full, decision 0006 item 6) | iXon driver |
| `image_index` | int64 | 1 | row in `images` (allows images to live in a separate file, *open*) | writer |

## `/derived` — optional, recomputable

| dataset | dtype | unit | meaning |
|---|---|---|---|
| `force_pN` | float64 `[n]` | pN | force from `magnet_mm` and `rig/magnet_force_model` |
| `extension_nm` | float64 `[n, n_beads]` | nm | z minus baseline, reference bead subtracted (F4.10) |

Derived data carry the attribute `recipe` (JSON: function and parameters). A reader never needs them.

## Open items

1. **Crash tolerance — undecided** (decision 0006 item 5). Options: (a) HDF5 SWMR mode with a flush every N frames;
   (b) an append-only raw binary stream during the run, converted to HDF5 at the end and on recovery; (c) plain
   chunked HDF5 with periodic `flush` plus a repair step. To be chosen with a crash test in phase 5.
2. Per-bead ROI images (decision 0006 item 6) — not in v1.
3. A command / event log (schedule transitions, commanded targets, button presses) — needed for force-clamp
   analysis? Decision 0007's session-state file records commands; whether a copy belongs here is for the owner.
4. Units of the ASI focus axis (internal units → µm) and of `t_camera`.
5. The meaning of the three `bandpass_forget` values and of `exp_ref` (inferred) — confirm before v1 is fixed.
