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
