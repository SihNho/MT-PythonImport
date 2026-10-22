# 0006 — Data format

**Decided:** 2026-10-21

1. **The existing files are reproduced byte-identical.** `.tra` (traces) and `.cal` (calibration) stay exactly as LabVIEW writes them, so existing analysis code (LabVIEW loaders, MATLAB scripts) keeps working. The layouts are described in [docs/format/tra-cal.md](../format/tra-cal.md).
2. **A new HDF5 file is added alongside** (MATLAB reads it natively with `h5read`):
   - **layers:** raw data / common time axis / derived data / provenance (software version, algorithm combination, parameters, calibration);
   - **MT table:** one row per JAI frame. It holds today's columns plus the absolute buffer number, the EMCCD frame index, the laser state, the motor read times and a lost-frame flag;
   - **fluorescence table:** one row per EMCCD frame, with its first and last JAI frame, exposure, laser state and image location;
   - a `schema_version` field and a written specification of every field (name, unit, type).
3. **Readers in Python and MATLAB.** A *legacy* mode returns today's matrix; an *extended* mode returns the tables plus metadata.
4. **Basic analysis moves into the application;** advanced analysis stays in MATLAB, connected through the format. Existing MT analysis methods are not changed by this project. Changing them would be a separate decision.
5. **Files must survive a crash:**
   - flush to disk at a short interval;
   - use a crash-tolerant writing scheme (or write a raw stream first and convert it);
   - detect and recover unfinished files on restart.
6. **Raw JAI frames are not saved in full** (about 200 MB/s at 150 Hz). Whether to save per-bead ROIs is still open. iXon frames are saved raw.

## Later notes (not changes to the decision)
- **2026-10-22, owner:** "저장하는 데이터에 장비의 정보들이 같이 저장되면 좋겠음. MT 데이터나 형광 데이터에 직접 들어가지
  않지만 메타데이터로 두고 나중에 Matlab 분석에서도 참고할 수 있도록". This makes the provenance layer concrete: a
  `metadata` group in every HDF5 file, kept apart from the MT and fluorescence tables:
  - `devices/<name>/`: identity (model, serial, firmware, port, driver / SDK version), settings **as read back** from
    the device, safety limits, calibration in use (table name, version, content);
  - `presets/`: the full content of the rig, sample, protocol and device-settings presets in use
    ([ui-requirements.md](../spec/ui-requirements.md) U13, U15), not just their names;
  - `run/`: user, start / end time, software version (git commit), tracking-stage combination (0003), frame-rate
    triple (preset / read-back / measured, U15), zero and re-zero events (U12, U14), device errors (U8);
  - written at start, and again with a timestamp whenever a value changes during the run.
  - A human-readable JSON copy of the same metadata is written next to the files, for a quick look without tools.
  - Fluorescence files carry the same run ID and metadata, so MT and fluorescence data of one run are linked.
  - MATLAB: the extended-mode reader returns this as a struct `meta` beside the data.
