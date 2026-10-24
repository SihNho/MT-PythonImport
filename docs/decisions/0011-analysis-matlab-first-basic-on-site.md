# 0011 — Analysis stays in MATLAB; the application offers basic on-site analysis

**Decided:** 2026-10-22 (owner, chat)

Owner: "분석은 Matlab에서 하는 것이 기본. 다만, 현장에서 기본적인 분석이 가능했으면 좋겠음."

## Decision
1. **MATLAB remains the main analysis tool.** The application's job is complete, well-described data: `.tra` / `.cal`
   byte-compatible with LabVIEW (0006) plus HDF5 with metadata (presets, events, calibration tables), readable by
   MATLAB's `h5read`; the MATLAB readers in `matlab/` are maintained with the formats.
2. **Basic on-site analysis in the application**, for decisions at the rig: force-extension curve with the eWLC fit
   ([ui-requirements.md](../spec/ui-requirements.md) U12), rotation (hat) curve, reference-bead noise and Allan
   deviation, segment means and step checks, the screening metrics (U10).
3. **The analysis functions live in a library separate from the GUI**, so the same calculations run from scripts and
   tests.

## Consequences
- No result computed only in the GUI: anything shown on screen can be reproduced from the saved data by the library.

## Later notes (not changes to the decision)
- The FRET pipeline and the merged MATLAB package (MT + FRET) extend this decision:
  [ui-requirements.md](../spec/ui-requirements.md) U28.
