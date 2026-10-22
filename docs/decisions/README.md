# Design decisions

Each file records one decision: what was decided, why, and what follows from it. These are written for people who join the project later. Dates are when the decision was made.

| # | Decision | Date |
|---|---|---|
| [0001](0001-principles.md) | Project principles: safeguards restrain AI tools, not users; no AI after the project ends; experiments are unrestricted | 2026-10-21 |
| [0002](0002-python.md) | Python as the language; numba and the existing CUDA kernel for hot paths | 2026-10-21 |
| [0003](0003-tracking-port-and-swappable-stages.md) | Port the current tracking algorithm first; make each stage swappable | 2026-10-21 |
| [0004](0004-verification.md) | Verification by numeric tolerance plus experimental A/B runs | 2026-10-21 |
| [0005](0005-camera-sync.md) | The JAI camera as the master clock; the Arduino divides frames for the EMCCD | 2026-10-21 |
| [0006](0006-data-format.md) | Keep `.tra` / `.cal` byte-identical; add HDF5 on a common frame axis | 2026-10-21 |
| [0007](0007-abort-recovery-estop.md) | Abort, crash recovery and the emergency stop | 2026-10-21 |
| [0008](0008-odd-behaviors-of-the-original.md) | What to do with odd behaviors of the original program | 2026-10-21 |
| [0009](0009-development-method.md) | Development method, shared rig, documents | 2026-10-21 |
| [0010](0010-magnet-position-is-raw-force-is-derived.md) | Magnet position is the raw record; force is derived from a recorded calibration table and recomputable | 2026-10-22 |
| [0011](0011-analysis-matlab-first-basic-on-site.md) | Analysis stays in MATLAB; basic on-site analysis in the application, from a GUI-independent library | 2026-10-22 |
| [0012](0012-automation-partial-first.md) | Protocol-driven partial automation now; full automation later, with conditional steps foreseen | 2026-10-22 |
| [0013](0013-mt-tirf-extensible-illumination.md) | MT-TIRF: basics plus extensibility; per-frame illumination sequences (smFRET, ALEX); analysis as plug-ins | 2026-10-22 |
| [0014](0014-ai-gateway.md) | One restricted AI gateway with permission tiers; AI never changes code or touches devices directly | 2026-10-22 |

The behavior specification of the LabVIEW program (`docs/spec/`) and the device manuals (`docs/manuals/`) will follow.
