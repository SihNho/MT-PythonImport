# Plan

Agreed with the project owner on 2026-10-22. The order is fixed; no dates are set. Each phase has a completion criterion and says whether the rig is needed. Until phase 9 is passed, lab experiments keep using the LabVIEW program.

```
0 foundation -> 1 preservation & manuals -> 2 specifications -> 3 offline core -> 4 calibration
                                                                    |
                                                                    +-> 5 device layer & simulators -> 6 camera on the rig -> 7 motors & scheduler
                                                                                                                                  |
                                                                                    8 GUI <---------------------------------------+
                                                                                      |
                                                                    9 experimental validation (ABBA) -> released for experiments
                                                                                      |
                                                     10 extensions (tracking alternatives, MT-TIRF) -> 11 handover
```

| Phase | Content | Deliverables | Done when | Rig |
|---|---|---|---|---|
| **0. Foundation** (done) | Decisions, repository, hooks (English only, experiment-time guard), Graphify, Ponytail, shared rig lock | `docs/decisions/` 0001–0009 | Done | none |
| **1. Preservation & manuals** | Copy the existing hardware-access code from MT_LabVIEW with its provenance. Write the SDK / library manifest and one manual per device | `third_party/MANIFEST`, `docs/manuals/` (camera, PI, rotor, ASI, iXon, OBIS, Arduino) | Every device has a command table with a verification level for each entry | none (iXon: SDK response only) |
| **2. Specifications** | Behavior specification along the 5-step experiment flow. Data format specification (`.tra` / `.cal` confirmed, HDF5 v1). Interviews with the owner | `docs/spec/`, `docs/format/` | Every front-panel control and every case/event frame maps to a feature (mechanical check); the owner confirms | none (VI reads only through MT_LabVIEW's guarded paths) |
| **3. Offline core** | Package skeleton and its own venv. Tracking port from the NumPy reference. `.tra` / `.cal` writers and readers (Python, MATLAB). numba speed test | `src/` tracking module, replay tests | Matches LabVIEW on recorded frames within tolerance (decision 0004). **Meets the 150 Hz budget (6 ms) → Python confirmed for good** | none |
| **4. Calibration** | Build `.cal` from a Z scan | calibration module | Matches a LabVIEW-made `.cal` | one recorded Z-scan image stack, if none exists yet |
| **5. Device layer & simulators** | Device interfaces with simulators. Threads, ring buffers, GUI in a separate process. Emergency stop, recovery state machine, session-state file | `src/devices/`, simulators | Simulator runs pass: acquire → track → save, emergency stop, reconnect | none |
| **6. Camera on the rig** | Live tracking and saving with the real JAI camera | | Frame loss at 150 Hz compared with MT_LabVIEW; **dragging windows loses no frames** | camera only (assembled state, lock) |
| **7. Motors & scheduler** | Motor control (through MT_LabVIEW's gate during development), 3-state clamping, autofocus. **Design the project's own motion gate and get it approved** | scheduler module, own gate | Motion tests pass; the owner approves the own gate | motors (inside the envelope, lock) |
| **8. GUI** | PySide6 + pyqtgraph in a separate process; bead picking; experiment-flow screens | the application | The whole 5-step experiment flow runs in the app | camera and motors |
| **9. Experimental validation** | Same sample, alternating LabVIEW and Python runs (ABBA) | validation report | Difference between programs ≤ difference between repeated runs of one program. **The owner decides the release for experiments** | whole rig (owner-led) |
| **10. Extensions** | Tracking alternatives (QI, phasor, …); basic analysis tools; MT-TIRF (iXon, Arduino sync, laser, fluorescence data) | | One decision record per adopted alternative; TIRF sync verified | per step |
| **11. Handover** | User manual, install guide, maintenance guide. Remove the development scaffolding (lock, hooks) | final documents | People can install, run and change it without AI tools; the rig is shown to be in its pre-project state | check only |

## Notes
- **In parallel:** phases 1 and 2 (documents); phases 3 and 5 (no hardware needed).
- **The key gate is the speed test at the end of phase 3.** If Python + numba misses 150 Hz, the tracking core's implementation is reconsidered.
- **The rig is needed only from phase 6.** Until then the work cannot collide with experiments or MT_LabVIEW.
- **Reused from MT_LabVIEW** (owned there, pinned by hash here): the NumPy tracking reference, the CUDA DLL, the camera ctypes layer, the motor protocols, the recorded frames.
- **Open:** does a recorded Z-scan stack for phase 4 exist? Unchecked.
