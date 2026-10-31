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
| [0015](0015-extension-architecture.md) | Fixed core + extension levels + one public function layer; safety parameters in a protected, versioned rig safety profile | 2026-10-24 |
| [0016](0016-owner-answers-after-wp5.md) | Magnet speed max 15 mm/s; `zero` = 0 mm; protocol end statement (no end -> keep recording); `.tra` frames from the first recorded frame; MATLAB 2026 | 2026-10-25 |
| [0017](0017-force-limit-follows-the-magnet-position-limit.md) | No separate force maximum: the force limit is derived from the magnet position limit through the force table in use | 2026-10-25 |
| [0018](0018-force-input-coerced-to-the-reachable-range.md) | Force from the calibration equation, live; an out-of-range force is coerced (typed or in a protocol), written back with no alarm; the motor position is always coerced | 2026-10-25 |
| [0019](0019-magnet-stall-returns-to-zero.md) | Magnet stall (controller error -1024): return the magnet to 0 mm at once - an extinguisher, not a working feature | 2026-10-25 |
| [0020](0020-rig-core-parameters-register.md) | Stall threshold stays 1.0 mm; rig core parameters in one register, checked and controlled together by the program later | 2026-10-26 |
| [0021](0021-camera-sdk-and-open-limits.md) | Camera through NI-IMAQdx first, SDK swappable later; rotor speed limit 150 (`SPD`); focus = mechanical limits; laser later; MT before MT-TIRF | 2026-10-26 |
| [0022](0022-z-lut-initial-band-and-forget.md) | Initial z-LUT settings at 50x LOW 0 / HIGH 40 / forget 10 (forget removes the inner radii); no further edits to the V6 LabVIEW code | 2026-10-27 |
| [0023](0023-labview-is-the-baseline-not-the-standard.md) | LabVIEW is the baseline, not the standard: at least its performance, better if possible; the exact port stays as the reference; formats stay; alternatives measured on the reference-bead benchmarks | 2026-10-28 |
| [0024](0024-three-z-methods-on-numba-and-cuda.md) | Three Z estimators (current / spline / phase_spline) kept as swappable slots on numpy, numba and CUDA, agreeing to 1e-9; default stays current until the tethered-bead data; the GPU executor works but is not yet faster | 2026-10-29 |
| [0025](0025-motion-gate-approved.md) | The project's motion gate is approved; the focus z window follows the ASI controller's own SL/SU Z limits | 2026-10-30 |
| [0026](0026-program-holds-the-rig-lock-and-shuts-down-visibly.md) | The program takes the shared rig lock itself (not the V6 wrapper) and closes the rig in a visible step-by-step dialog that keeps the lock on a failed cleanup | 2026-10-30 |
| [0027](0027-rotor-limit-is-the-controller-counter-range.md) | The rotor's limit is the controller's own soft-limit registers read at open (today the 24-bit counter range); the program writes nothing to the controller; the profile adopts the readback | 2026-10-30 |
| [0028](0028-camera-through-ebus-sdk.md) | Two camera SDKs chosen in Setup (`camera_sdk`): IMAQdx (default; NI driver, shared with LabVIEW) and JAI's eBUS SDK (.NET API via pythonnet, a C# pointer helper; Pleora driver). The SDK must match the USB3 Vision driver bound; the binding is the owner's system setting | 2026-11-01 |

The behavior specification of the LabVIEW program is in [../spec/README.md](../spec/README.md) and the device manuals are
in [../manuals/README.md](../manuals/README.md).
