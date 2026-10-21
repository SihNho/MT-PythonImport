# 0004 — Verification: numeric tolerance plus experiment

**Decided:** 2026-10-21

1. **Offline:** replay recorded frames and compare per-bead XYZ with the LabVIEW output within a stated tolerance. Starting point: 1e-6 px in XY and 1e-4 µm in Z, the tolerances already used for the GPU kernel.
2. **Experimental:** on the same sample, alternate LabVIEW and Python runs (A-B-B-A). Compare:
   - reference-bead noise;
   - force–extension curves (WLC fit parameters);
   - rotation–extension curves;
   - frame loss.
3. **Acceptance rule:** the difference between the two programs must not exceed the difference between two runs of the same program.
4. **Additional acceptance test:** dragging, resizing or covering windows while recording must lose no frames.

Lab members start doing their real experiments with the Python application only after it passes both 1 and 2. The project owner makes that call.
