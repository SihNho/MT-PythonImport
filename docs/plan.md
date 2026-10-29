# Plan

Agreed with the project owner on 2026-10-22; **revised 2026-10-24** on the owner's word ("1. 다시 진행", after the
2026-10-24 lint found that the plan no longer matched decisions 0010-0015 and the requirements U1-U37). The order of
phases 0-9 is kept; their contents are completed, phase 10 is split, and a requirement-to-phase table is added. No
dates are set. Each phase has a completion criterion and says whether the rig is needed. Until phase 9 is passed, lab
experiments keep using the LabVIEW program.

```
0 foundation -> 1 preservation & manuals -> 2 specifications -> 3 offline core -> 4 calibration
                                                                    |
                                                                    +-> 5 API, device layer, data & protocol engine (simulators)
                                                                              -> 6 camera on the rig -> 7 motors & protocols on the rig
                                                                                                                  |
                                                                                    8 GUI <-----------------------+
                                                                                      |
                                                                    9 experimental validation, MT (ABBA) -> released for MT experiments
                                                                                      |
                                       10a MT-TIRF   10b tracking alternatives   10c automation & AI gateway -> 11 handover
```

| Phase | Content | Deliverables | Done when | Rig |
|---|---|---|---|---|
| **0. Foundation** (done) | Decisions, repository, hooks (English only, experiment-time guard), Graphify, Ponytail, shared rig lock | `docs/decisions/` 0001-0009 (now 0001-0015) | Done | none |
| **1. Preservation & manuals** (done) | Hardware-access code copied from MT_LabVIEW with provenance; SDK manifest; one manual per device | `third_party/MANIFEST`, `docs/manuals/` | Every device has a command table with verification levels | none |
| **2. Specifications** (done; kept current) | Behaviour spec along the 5-step flow; data formats; owner interviews; **owner requirements U1-U37** | `docs/spec/`, `docs/format/`, `docs/spec/ui-requirements.md` | Every panel control and case/event frame maps to a feature; the owner confirms | none |
| **3. Offline core** (done) | Tracking port, `.tra` / `.cal` readers / writers (Python, MATLAB), numba speed test | `src/mtpy/` track, fast, lvfiles; replay tests | Matches LabVIEW within tolerance (0004); 80 beads < 6 ms per frame | none |
| **4. Calibration** (in progress) | Build `.cal` from a z scan; record the JAI camera position with each calibration and invalidate the LUT when it changes (U31) | `src/mtpy/calib.py` | Matches a LabVIEW-made `.cal` | one recorded z-scan stack |
| **5. API, device layer, data & protocol engine** | **Public function layer** per [design/api.md](design/api.md) (0015); **rig safety profile** (protected, versioned; 0015 item 5); device services with simulators, settings changeable at runtime (U17), device status / details / reconnect / self-check (U8); presets with read-back (U13, U15); HDF5 writer with the `metadata` group and event tables (0006, [format/hdf5-v1.md](format/hdf5-v1.md), U14, U16); **protocol / sequence / recipe grammar spec** and engine with mid-run edits and conditional steps (0012, U18, U19); threads, ring buffers, emergency stop, recovery (0007) | `src/mtpy/api`, `src/devices/`, simulators, `docs/format/grammar.md` | Simulator runs pass: acquire → track → save with metadata; a protocol (incl. 3-state clamp) runs and is edited mid-run; emergency stop; reconnect; safety-profile refusal | none |
| **6. Camera on the rig** (done 2026-10-29 for the camera path; [results/2026-10-29-phase6-camera.md](results/2026-10-29-phase6-camera.md)) | Live tracking and saving with the JAI; camera presets applied and read back; per-frame timestamps and frame-rate triple (U15) | `src/mtpy/devices/jai.py`, rig preset `{"backend": "real"}`, GUI Setup backend | Frame loss at 150 Hz compared with MT_LabVIEW (0 of 44 984 vs 15-21 % at 90 Hz); dragging windows loses no frames (0 in three drags). Open: the same with beads tracked, a 30 min soak | camera (assembled, lock) |
| **7. Motors & protocols on the rig** | Motor, rotor, focus through the API (MT_LabVIEW's gate during development); **design the project's own motion gate** and get it approved; protocols on hardware (force ramps, rotation, 3-state clamp, autofocus); screening protocols (U7, U10, U19); sticking detection (U33) | own gate | Motion and protocol tests pass; the owner approves the gate | motors (inside the envelope, lock) |
| **8. GUI** | PySide6 + pyqtgraph in its own process, following the mock-up ([mockups/](mockups/2026-10-23-main-window/README.md)): one-screen layout, step bar, status bar and e-stop, any-axis live graphs, numeric entry (U1-U6, U30); bead finding and screening (U7, U10, U23); presets and save dialogs (U13, U20, U21); **basic on-site analysis**: eWLC fit, zero and re-zero, excluded segments, Allan / noise (0011, U12, U14); troubleshooting guide, rule-based first (U9); English UI (U11) | the application | The whole MT experiment flow runs in the app | camera and motors |
| **9. Experimental validation, MT** | Same sample, alternating LabVIEW and Python runs (ABBA) | validation report | Python not worse than LabVIEW (0023): for the reference implementation, difference between programs ≤ difference between repeated runs of one program; for an adopted alternative, equal or better on the 0023 benchmarks. **The owner decides the release for MT experiments** | whole rig (owner-led) |
| **10a. MT-TIRF** | iXon through the API; Arduino light gating and illumination sequence editor (0005, 0013, U24); channel layout and maps, CH-CH and JAI-EMCCD (U22, [format/mapping.md](format/mapping.md)); fluorescence spots, signal identification, bead-autofluorescence ROI (U25, U33); raw signals, observables, FRET with corrections, analysis recipes (U28, U36); FRET + extension overlay (U29); MT-TIRF screening and flow (U-discussion of 2026-10-24); merged MATLAB package (MT + FRET, U28); export of smCamera-compatible `.trace` | MT-TIRF mode of the app | TIRF sync verified; a FRET run and an event-type run (e.g. enzyme cleavage) work end to end; MT-TIRF ABBA or equivalent check agreed with the owner | whole rig |
| **10b. Tracking alternatives** (may start now, offline; 0023) | Candidates measured so far ([methods/tracking-benchmarks-explained.md](methods/tracking-benchmarks-explained.md)): radial-profile variants (`polar3`, `area4`), QI, FFT-phasor, MagTrack; slice spacing; benchmarked on the recorded reference-bead data ([results/2026-10-26-refbead.md](results/2026-10-26-refbead.md)) | decision records | One decision per adopted alternative (0003, 0023 item 4), with new calibrations and a rig check | per step (offline first) |
| **10c. Automation & AI gateway** | Full automation on top of the protocol engine (0012); the AI gateway with permission tiers (0014); plug-in and scripting APIs documented with examples (0015) | gateway, plug-in docs | Gateway tiers tested on the simulator; a plug-in and an experiment script run end to end | per step |
| **11. Handover** | User manual, install guide, maintenance guide, API and plug-in docs; remove the development scaffolding (lock, hooks); **a Windows executable of the application** (owner 2026-10-29: "최종적으로는 exe 파일 형식을 원함"; PyInstaller or Nuitka, numba cache handled at build or in the user folder, GPU executor optional, device DLLs beside the exe) | final documents, the exe | People can install, run and change it without AI tools; the rig is shown to be in its pre-project state | check only |

## Rig measurements to schedule (assembled state, lock)
Collected in the 2026-10-22..24 discussions; each needs the owner's go.
- 50x pixel size (measured, not nominal) — and for 60x when MT-TIRF starts.
- Slow piezo scan of a reference bead: z error vs height (calibration quality map, U34).
- Exposure time × tracking method noise, reference and tethered beads ([methods](methods/tracking-benchmarks-explained.md) 6a).
- 50x vs 60x comparison for MT alone (not urgent; the running nucleosome project keeps 50x).
- Defocus vs fluorescence intensity (U35) and M-270 autofluorescence on the EMCCD (U22) — after the iXon is connected.

## Requirement → phase
| Requirements / decisions | Phase |
|---|---|
| 0015 API + safety profile; U8, U13, U14 (data side), U15, U16, U17, U18, U19; 0006, 0010, 0012 | 5 |
| U15 camera side | 6 |
| U7, U10, U19 (on hardware), U33; own motion gate | 7 |
| U1-U6, U9, U11, U12, U14 (UI), U20, U21, U23, U30; 0011 | 8 |
| U22, U24, U25, U27-U29, U32, U34-U36; 0013 | 10a |
| tracking alternatives; 0003 | 10b |
| 0014; full automation (0012); U37 / 0015 plug-in docs | 10c |
| U31 (camera position) | 4 (record with calibration) and 7 / 10a (hardware choice) |

## Notes
- **In parallel:** phase 4 and phase 5 (no hardware); within phase 5, the grammar spec and the API can be written
  before the device services.
- **The rig is needed only from phase 6.** Until then the work cannot collide with experiments or MT_LabVIEW.
- **Reused from MT_LabVIEW** (owned there, pinned by hash here): the NumPy tracking reference, the CUDA DLL, the camera
  ctypes layer, the motor protocols, the recorded frames.
- **Open:** does a recorded z-scan stack for phase 4 exist? Unchecked.
- **Order revised 2026-10-29 (owner): phase 8 (GUI) is built first on the simulators, then phases 6 and 7 on the rig**
  ("지금 그냥 프로그램 빌드를 해보는건 어떤지?", "GUI 빌드 해보고 Phase 6, 7 까지 진행해보면 좋겠다. (모터 리밋은 확실히 체크하고)").
  Design, protocol and detail are to be fixed by running the program. The motor limits get an explicit check in
  phase 7. The tethered-bead calibration and the ABBA comparison (phases 4 / 9) follow when a sample allows;
  the channel mounted on 2026-10-29 (H2A tailless, heavily aggregated) serves as a basic bench only. Phase 10a
  continues alongside as the MT-TIRF hardware is finished.
- Change log: 2026-10-22 agreed; 2026-10-24 revised (phases 4, 5, 7, 8 completed with 0010-0015 and U1-U37; phase 10
  split into 10a / 10b / 10c; rig-measurement list; requirement-to-phase table).
