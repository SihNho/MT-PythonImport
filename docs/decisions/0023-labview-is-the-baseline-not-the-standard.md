# 0023 — LabVIEW is the baseline, not the standard: at least its performance, better if possible

**Decided:** 2026-10-28 (owner, in chat)

Owner:
- "내가 LabVIEW 이야기한 것은 일종의 스탠다드였는데, 지금은 생각이 조금 달라짐."
- "만약 LabVIEW보다 더 accuracy 좋고 빠른 분석이 있다면 그렇게 가는 것도 괜찮아보임"
- "최소 LabVIEW 만큼의 퍼포먼스, 그 이상이면 좋음"

## Decision
1. **The acceptance criterion changes.** Until now the program had to give the same numbers as LabVIEW (0003, 0004,
   0008). From now on it must perform **at least as well as LabVIEW, and better where it can**: accuracy, noise,
   and speed. This covers every computation, not only tracking: tracking, calibration, force.
2. **The exact port of the current method stays**, as the reference implementation. It is the baseline every
   alternative is compared with, and it re-analyses old data the LabVIEW way. Phase 3 delivered it; nothing is
   removed.
3. **The existing file formats stay byte-identical** (0006): `.tra` / `.cal` are read by the MATLAB analysis.
   Values from a better method are written in the same formats.
4. **"At least as good" is measured, not argued.** The benchmarks are the ones the reference-bead session gave
   ([results/2026-10-26-refbead.md](../results/2026-10-26-refbead.md)):
   - tracking noise floor from the difference of two fixed beads (x, y, z);
   - z-scan self-consistency (error and slope against the commanded z), and the step response;
   - z bias across the field;
   - speed per bead and per frame;
   - and, last, the experimental validation of phase 9 (ABBA against LabVIEW on the same sample).
   An alternative becomes the default only when it is not worse on any of these, and the change is its own
   recorded decision (0003 item 5 unchanged). The first case is 0022: within the current method, the LUT settings
   0 / 40 / 10 beat the LabVIEW panel defaults at 50x.
5. **Order of work.** Phases 6-7 (camera and motors on the rig) run on the current method first. Phase 10b
   (tracking alternatives) starts in parallel, offline, on the recorded reference-bead data; no rig time is needed
   until a candidate wins.

## Follows
- plan.md: phase 9's criterion reads "not worse than LabVIEW" instead of "equal within the run-to-run spread";
  phase 10b may start now, offline.
- 0004 (verification) and 0008 (odd behaviours) stay in force for the reference implementation; for an adopted
  alternative, the tolerance is against the benchmark of item 4, not against LabVIEW's numbers.
