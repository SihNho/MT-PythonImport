# HDF5 file, schema v1 — DRAFT

**Status: draft for the owner's review** (plan phase 2). Decision [0006](../decisions/0006-data-format.md) sets the
layers and tables; this page names every field. The `.tra` and `.cal` files are still written, byte-identical
([tra-cal.md](tra-cal.md)); the HDF5 file is written alongside them, one per run.

**Updated 2026-10-24** to follow decision 0006 "Later notes" (the `metadata` group), 0010 (magnet position raw, force
derived), 0012 (protocol engine), 0013 / 0015 (illumination sequence, extensions, rig safety profile) and
[ui-requirements.md](../spec/ui-requirements.md) U8, U12-U18, U22, U24, U28, U33, U36. What changed from the first
draft: the old `/provenance` group became `/metadata` (devices / presets / run, plus the `.cal` content); new
`/beads` and `/events` groups; per-bead `role` instead of "bead index 0 = reference"; the scheduler columns follow the
protocol engine; per-spot raw fluorescence signals. **Still draft:** field names, the event payloads and the
fluorescence spot layout are proposals; nothing here is fixed until the owner agrees and a reader / writer passes
its tests. Open items are at the end.

## Conventions

- File name: the `.tra` base name with `.h5` (e.g. `tra002.h5`); one file per run, not split.
- Text: UTF-8 (unlike `.tra` / `.cal`). Times: seconds as float64 unless stated.
- Every table is a group of **1-D or 2-D datasets of equal first length** (one dataset per column), chunked and
  extendible along the first axis. Plain numeric datasets read directly with MATLAB `h5read`; MATLAB shows 2-D
  datasets transposed (beads × frames).
- Per-bead columns are 2-D: `[n_frames, n_beads]`; the column index is the bead's index in `/beads` (the `.tra` /
  `.cal` order). **The column index says nothing about the bead's role**: the reference bead is not necessarily the
  first click ([rig-facts.md](../rig-facts.md): in the fixture it is identified from the data, because it does not
  follow the magnet). Each bead's role is stored in `/beads/role`.
- Per-spot fluorescence columns are 2-D: `[n_emccd_frames, n_spots]`, indexed by `/fluorescence/spots`.
- Every per-frame record carries the **absolute JAI buffer number** (decision 0005), which is the common time axis of
  `/mt`, `/fluorescence` and `/events`.
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
| `run_id` | string | unique id of the run (UUID); the same id is in any separate fluorescence / image file and in the JSON copy, so the files of one run are linked (0006 "Later notes") |

## `/metadata` — devices, presets, run (0006 "Later notes", U16)

Kept apart from the MT and fluorescence tables. Written at start; a value that changes during the run is written
again as a `settings_change` event (see `/events`) with its time and buffer number, so `/metadata` always holds the
values **at start** and the events hold the history. A human-readable JSON copy of the whole group is written next to
the file (`<base>.meta.json`). MATLAB: the extended-mode reader returns it as the struct `meta`.

Complex content is stored as UTF-8 JSON strings (one dataset per item), so new fields do not change the HDF5 layout.

### `/metadata/devices/<name>/` — one group per device (U8, U15)

`<name>` is `jai`, `ixon`, `pi_magnet`, `asi`, `rotor`, `arduino`, `laser_532`, `laser_637`, `light_switch`, ...;
only devices present in the run.

| dataset | dtype | meaning | source |
|---|---|---|---|
| `identity` | string (JSON) | model, serial number, firmware, port, driver / SDK version (Arduino: firmware version query, as a CH340 has no serial) | device layer |
| `preset_name` | string | the device-settings preset applied (U15) | settings |
| `preset` | string (JSON) | the preset's values as applied | settings |
| `readback` | string (JSON) | the settings **as read back** from the device after applying (can differ from the preset); cameras: frame rate, exposure, gain, acquisition / trigger mode, ROI, binning, pixel format; iXon adds EM gain, readout speed, pre-amp gain, cooling set point and temperature, frame transfer | device layer |
| `limits` | string (JSON) | controller limits set and read back, allowed motion range | device layer, safety profile |
| `calibration` | string (JSON) | calibration in use: name, version, date, content or hash (e.g. the magnet force table, 0010) | configuration |
| `backend` (`light_switch` only) | string (JSON) | the chosen back-end (mechanical shutter / AOM / laser modulation) and its settings (open / close delay, TTL polarity, power, modulation mode) (U24) | settings |

### `/metadata/presets/` — full content, not just names (U13, U15)

| dataset | dtype | meaning |
|---|---|---|
| `rig` | string (JSON) | objective, pixel size (with source: nominal / measured), focal-shift factor **with its source** (assumed 0.88 = 1.33/1.515, or measured), correction-collar settings, camera settings, JAI camera position and TIRF-angle stage position (U31), magnet-position-to-force table id |
| `sample` | string (JSON) | bead type and diameter, DNA construct name and contour length, dye position (bp), sample type, buffer, temperature, surface coating type and batch (U33) |
| `protocol` | string (JSON) | screening template and experiment protocol (0012, U19): the script text and its parsed steps |
| `channel_layout` | string (JSON) | 1 / 2 / 3 fluorescence channels, each named and defined ([mapping.md](mapping.md), U22) |
| `analysis_recipe` | string (JSON) | the analysis recipe(s) in use, e.g. "smFRET basic" (U36) |
| `<kind>_name` | string | the preset's name and version, for each of the above |

### `/metadata/run/`

| dataset | dtype | unit | meaning | source |
|---|---|---|---|---|
| `user` | string | — | who ran it | login / settings |
| `start_utc`, `end_utc` | string | — | ISO 8601 | host clock |
| `software_name`, `software_version`, `git_commit` | string | — | the application build | package metadata |
| `tracking_stages` | string (JSON) | — | the stage combination used (decision 0003), e.g. `{"xy": "labview-crosscorr", "z": "labview-radial"}` | tracking configuration |
| `parameters` | string (JSON) | — | every run setting, by the original control names where one exists (`Cross length (pixels)`, `Limit of Auto-Focus`, `Frame rate` as autofocus period, …) | GUI state at start |
| `frame_rate_hz` | float64 `[3]` | Hz | the frame-rate triple: **preset / read back / measured** from the camera timestamps (U15); attribute `warning` when they disagree. The frame rate can never be missing | settings, device, computed at close |
| `safety_profile` | string (JSON) | — | the active rig safety profile: version, who / when / why, full content (0015 item 5) | safety layer |
| `extensions` | string (JSON) | — | every script, plug-in and recipe used: kind, name, version, sha256 and **full content** (0015 item 4) | extension loader |
| `force_table` | string (JSON) | — | the force calibration used for derived force: name (e.g. `Magnet2Force v3_for M270`), version, content or hash (0010) | configuration |
| `maps` | string (JSON) | — | id **and full content** of every map used (channel <-> channel, JAI <-> EMCCD; [mapping.md](mapping.md), U22) | map library |
| `illumination_planned` | string (JSON) | — | the illumination sequence loaded into the Arduino: header / body / footer, one column per light (0013, U24) | sequence editor |
| `illumination_executed` | string (JSON) | — | what the Arduino reports at the end: triggers issued, body repeats, firmware count; the per-frame result is `/fluorescence/excitation` (U28: excitation comes from the sequence **actually executed**) | Arduino, read at end |
| `sync` | string (JSON) | — | N, k, Arduino firmware version, JAI buffers vs EMCCD frames / N total check (0005) | sync |
| `fret_corrections` | string (JSON) | — | FRET correction factors used for derived FRET (`alpha` leakage, `delta` direct excitation, `gamma`), with their source; FRET can be recomputed with others (U28) | analysis recipe |

### `/metadata/calibration/` — the `.cal` content (was `/provenance/calibration`)

| dataset / attribute | dtype | unit | meaning | source |
|---|---|---|---|---|
| `xy_px` | float64 `[n_beads, 2]` | px | picked bead x, y | `.cal` `x,y pos array` |
| `stack` | float64 `[n_beads, S, L]` | a.u. | radial-profile stack | `.cal` `cal image array` |
| `z_step_um` | float64 | µm | slice step, as stored in the `.cal` (single precision widened) | `.cal` |
| `n_avg` | int32 | 1 | frames averaged per slice | `.cal` |
| `bandpass_forget` | int32 `[n_beads, 3]` | 1 | per-bead bandpass / forget values | `.cal` |
| `exp_ref` | int32 `[n_beads]` | 1 | 0 = reference, 1 = experiment (*inferred* meaning); kept as written, `/beads/role` is the authority | `.cal` |
| `nm_per_px` | float64 | nm/px | pixel size as stored in the `.cal` — **not used by tracking and possibly stale** (84 nm/px from the 100x objective, [rig-facts.md](../rig-facts.md)); the rig preset holds the current value and its source | `.cal` `Pixel distance` |
| `sha256` | string | — | hash of the `.cal` file | computed |
| `error_vs_height` | float64 `[n_beads, S]` | µm | per-calibration error-vs-height map, when measured (U34); absent otherwise | calibration scan |

(The first draft's `rig/camera`, `rig/emccd` and `rig/magnet_force_model` moved to `/metadata/devices/` and
`/metadata/run/force_table`.)

## `/beads` — one row per bead (column index of the per-bead datasets)

| dataset | dtype | unit | meaning | source |
|---|---|---|---|---|
| `bead_id` | int32 | 1 | stable bead id within the run (also used in `/events` and `/fluorescence/spots`) | picking |
| `tra_column` | int32 | 1 | the bead's position in the `.tra` / `.cal` order (0-based) | picking |
| `role` | string (enum) | — | **`reference`** (surface-stuck, non-magnetic), **`tethered`** (DNA-tethered magnetic bead) or **`candidate`** (picked, not yet accepted by screening); value at the end of the run, changes are `role_change` events | user / screening |
| `role_source` | string | — | how the role was set: `user`, `screening` (U10), `identified from data` (e.g. does not follow the magnet, as bead 1 of the fixture) | user / analysis |
| `screening` | string (JSON) | — | screening metrics and result per rule, if screening ran (U7, U10) | screening |
| `pick_xy_px` | float64 `[2]` | px | where the bead was picked | picking |

## `/mt` — one row per JAI frame

| dataset | dtype | unit | meaning | source |
|---|---|---|---|---|
| `buffer_number` | uint64 | 1 | absolute camera buffer number (decision 0005) | camera driver |
| `frame` | int64 | 1 | `buffer_number − first buffer number` — identical to `.tra` column 0 | computed |
| `lost_before` | uint32 | 1 | frames lost between this row and the previous one (0 = none) | buffer numbers |
| `t_host` | float64 | s | host clock when the frame was received, from the run start | host clock |
| `t_camera` | uint64 | camera ticks | the camera's own per-frame timestamp (U15: with `buffer_number` it keeps the frame rate recoverable); attribute `tick_hz`. If the camera gives none (the JAI SP-5000M-USB has no hardware timestamp feature, decision 0005), the driver's per-buffer timestamp is stored and the attribute `source` says which (*open*: tick unit) | camera driver |
| `magnet_mm` | float64 | mm | last magnet position read — identical to `.tra` column 1. **This is the raw record; force is never stored as raw** (0010), only in `/derived` with the table id | motor thread |
| `magnet_t` | float64 | s | host time of that magnet reading | motor thread |
| `rotor_deg` | float64 | deg | last rotor angle read (signed) — `.tra` column 2 | rotor thread |
| `rotor_t` | float64 | s | host time of that rotor reading | rotor thread |
| `focus_pos` | float64 | ASI internal units | last focus (piezo) position read; recorded every frame so bead z can be corrected for any piezo move (U35) | ASI thread |
| `focus_t` | float64 | s | host time of that focus reading | ASI thread |
| `x_px`, `y_px` | float64 `[n, n_beads]` | px | bead position — `.tra` columns 3 + 3i, 4 + 3i | tracking |
| `z_um` | float64 `[n, n_beads]` | µm | bead height (the `.tra` header's "nm" is wrong, decision 0008) — `.tra` column 5 + 3i | tracking |
| `cal_slice` | int32 `[n, n_beads]` | 1 | index of the closest calibration slice (`pos in cal image out`); −1 = lost | tracking |
| `bead_good` | uint8 `[n, n_beads]` | 1 | the kernel's good flag | tracking |
| `bead_lost` | uint8 `[n, n_beads]` | 1 | 1 when the kernel returned the lost marker | tracking |
| `reseed` | uint8 | 1 | 1 when this frame started from the calibration positions (F4.05) | tracking |
| `autofocus_move` | float64 | ASI internal units | relative focus move commanded at this frame, NaN if none (F4.06) | scheduler |
| `protocol_step` | int32 | 1 | index of the running protocol step in the protocol version in force, −1 outside a protocol (0012). In the LabVIEW-compatible mode this is the `CycleSchedule` column (F4.08) | protocol engine |
| `protocol_loop` | int32 | 1 | current loop (repeat) number, −1 outside a protocol; the LabVIEW cycle number | protocol engine |
| `protocol_version` | int32 | 1 | which protocol version is in force (0 = as started; +1 per applied mid-run edit, U18; the versions are in the `protocol_edit` events) | protocol engine |
| `clamp_state` | uint8 | 1 | LabVIEW-compatible scheduler state; dataset absent when the general engine runs (enum stored as attribute `states`; names fixed after Q4.08) | scheduler |
| `emccd_frame` | int64 | 1 | EMCCD frame exposed during this JAI frame, −1 if none | sync (decision 0005) |
| `light_state` | uint8 | 1 | bit mask of the lights on during this frame, from the illumination sequence actually executed (bit order in attribute `lights`, e.g. `["532", "637"]`) (U24) | sync / sequence |

## `/fluorescence` — one row per EMCCD frame (absent without an EMCCD)

| dataset | dtype | unit | meaning | source |
|---|---|---|---|---|
| `emccd_frame` | int64 | 1 | EMCCD frame number from 0 | iXon driver |
| `jai_first_buffer`, `jai_last_buffer` | uint64 | 1 | first and last JAI buffer number during its exposure | sync |
| `t_host` | float64 | s | host time of arrival | host clock |
| `exposure_s` | float64 | s | exposure time | iXon driver |
| `excitation` | uint8 | 1 | bit mask of the lights on during the exposure, from the illumination sequence **actually executed** (bit order in attribute `lights`), not from a separate text file (U24, U28) | sync / sequence |
| `sequence_part` | uint8 | 1 | 0 header, 1 body, 2 footer; with `sequence_row`, the row of the sequence that produced this frame | sync / sequence |
| `sequence_row` | int32 | 1 | row within that part | sync / sequence |
| `images` | uint16 `[n, H, W]` | counts | raw EMCCD frames (saved in full, decision 0006 item 6; needed so corrections such as bead autofluorescence can be redone, U33) | iXon driver |
| `image_index` | int64 | 1 | row in `images` (allows images to live in a separate file with the same `run_id`, *open*) | writer |

### `/fluorescence/spots` — one row per spot

| dataset | dtype | unit | meaning |
|---|---|---|---|
| `spot_id` | int32 | 1 | stable spot id within the run |
| `bead_id` | int32 | 1 | the tethered bead this spot belongs to, −1 if none (U25) |
| `roi` | string (JSON) | px | geometry per channel of the molecule ROI, the local background ROI and the bead-autofluorescence ROI, in raw EMCCD coordinates, and the map id used to place them (U22, U33) |
| `selection` | string (JSON) | — | how the spot was chosen (score, rule, user) (U25, U36) |

### `/fluorescence/signals` — raw per-spot signals, one row per EMCCD frame (U36, U33)

Always stored when spots exist, whatever the experiment's observables are; FRET is only one derived value. A signal
that is not measured on a frame (its excitation was off) is NaN on that frame.

| dataset | dtype | unit | meaning |
|---|---|---|---|
| `donor_exc_donor` | float64 `[n, n_spots]` | counts | donor-channel intensity on donor-excited (532 nm) frames, background not subtracted |
| `donor_exc_acceptor` | float64 `[n, n_spots]` | counts | acceptor-channel intensity on donor-excited frames |
| `acceptor_exc_acceptor` | float64 `[n, n_spots]` | counts | acceptor-channel intensity on acceptor-excited (637 nm) frames |
| `background` | float64 `[n, n_spots, n_channels]` | counts | local background per channel (per pixel × ROI area, as stated in attribute `method`) |
| `bead_af` | float64 `[n, n_spots]` | counts | bead autofluorescence ROI intensity; a rise flags the bead entering the TIRF field (U33) |

Attributes: `roi_sum_method`, `channels` (names from the channel layout). The bead-AF coefficient k and its method
are stored with the derived corrected signals, not here.

## `/events` — everything that happened during the run, one table per kind

Raw data are never changed: re-zeros, bridges and exclusions are events, and the display and exports apply them
(U14). Undo / edit adds a new event that supersedes an old one (`supersedes` = its `event_id`).

Common columns in every table:

| dataset | dtype | unit | meaning |
|---|---|---|---|
| `event_id` | int64 | 1 | unique within the run |
| `buffer_number` | uint64 | 1 | JAI buffer number at the event (the common time axis) |
| `t_host` | float64 | s | host time from the run start |
| `caller` | string | — | who caused it: GUI user name, script / plug-in name, protocol, AI gateway (0014), device service |
| `supersedes` | int64 | 1 | event replaced by this one, −1 if none |
| `note` | string | — | free text |

Tables and their own columns:

| table | own columns | source |
|---|---|---|
| `zero` | `bead_ids` (JSON list or "all"), `mode` (`zero force` / `set zero here` / `bridge a step` / `fit z0` / `surface contact` / `LabVIEW 7 pN rule`), `window_s`, `old_value_um`, `new_value_um`, `reason` (frame jump / bubble / other bead / other) | U12, U14 |
| `exclusion` | `bead_ids`, `t0_buffer`, `t1_buffer`, `reason` (bubble / passing bead / sticking / settling / other) | U14, U33, U35 |
| `role_change` | `bead_id`, `old_role`, `new_role`, `role_source` | picking, screening |
| `device_error` | `device`, `kind` (disconnected / error / slow / reconnect), `message`, `hint` | U8 |
| `settings_change` | `path` (e.g. `devices/jai/readback/exposure`), `old` (JSON), `new` (JSON), `class` (immediate / short pause / guarded while recording) | U17 |
| `protocol_step` | `step`, `loop`, `protocol_version`, `phase` (start / end / skipped), `target` (JSON: commanded magnet position, rotation, hold time, ...) | 0012 |
| `protocol_edit` | `old_steps` (JSON), `new_steps` (JSON), `new_version`, `applies_from` (now / next loop) | U18 |
| `light` | `light`, `state` (on / off), `cause` (sequence / manual / auto-close when not recording) | U24 |
| `mark` | `text` (user marks and `api.acq.mark`) | [api.md](../design/api.md) |
| `rule` | `rule` (name and expression), `spot_id` / `bead_id`, `values` (JSON), e.g. sticking detected (U33) or "Cy5 disappears while Cy3 stays" (U36) | event rules |

## `/derived` — optional, recomputable

| dataset | dtype | unit | meaning |
|---|---|---|---|
| `force_pN` | float64 `[n]` | pN | force from `magnet_mm` and the table in `/metadata/run/force_table`; attribute `force_table_id` (0010) |
| `z_corrected_um` | float64 `[n, n_beads]` | µm | z × focal-shift factor from the rig preset (attribute `factor`, `factor_source`); raw `z_um` is kept (U13) |
| `extension_nm` | float64 `[n, n_beads]` | nm | z minus the zero from the `zero` events, reference bead(s) subtracted, excluded segments NaN (U12, U14, F4.10); attribute `zero_mode` |
| `z_sigma_um` | float64 `[n, n_beads]` | µm | per-frame z uncertainty (local LUT sensitivity + noise, U34) |
| `fret_e` | float64 `[n_emccd, n_spots]` | 1 | FRET efficiency with the factors in `/metadata/run/fret_corrections` (U28) |
| `bead_af_corrected` | float64 `[n_emccd, n_spots, n_channels]` | counts | molecule signal − background − k × bead AF; attributes `k`, `method` (U33) |
| `observables/<name>` | float64 | — | other observables of the analysis recipe (stoichiometry, presence, ...) (U36) |

Derived data carry the attribute `recipe` (JSON: function, parameters and the recipe / plug-in version). A reader never
needs them.

## Open items

1. **Crash tolerance — undecided** (decision 0006 item 5). Options: (a) HDF5 SWMR mode with a flush every N frames;
   (b) an append-only raw binary stream during the run, converted to HDF5 at the end and on recovery; (c) plain
   chunked HDF5 with periodic `flush` plus a repair step. To be chosen with a crash test in phase 5.
2. Per-bead ROI images (decision 0006 item 6) — not in v1.
3. ~~A command / event log — needed?~~ **Resolved** by the owner's requirements: re-zero / exclusion events (U14),
   device errors (U8), mid-run protocol edits (U18), light changes (U24) and setting changes (U17) are all stored with
   the data; see `/events`. (Decision 0007's session-state file stays separate; it is for recovery, not analysis.)
4. Units of the ASI focus axis (internal units → µm) and of `t_camera` (and which timestamp the JAI / IMAQdx path
   actually provides).
5. The meaning of the three `bandpass_forget` values and of `exp_ref` (inferred) — confirm before v1 is fixed.
6. The exact FRET correction formula smCamera uses (from the owner's example data, U28), which fixes the names and
   meaning of the factors in `fret_corrections`.
7. Spot signals: whether `background` is stored per pixel or per ROI sum, and the acceptor-excited donor channel
   (not requested; add if the FRET correction needs it).
8. Whether `images` stay in this file or in a companion file with the same `run_id` (size), and the JSON copy's name.
9. Map storage: maps are JSON files ([mapping.md](mapping.md), still a proposal); the data file stores their content as
   JSON in `/metadata/run/maps`.
