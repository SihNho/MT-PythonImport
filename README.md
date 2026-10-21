# MT-PythonImport

A Python port of the Kim Lab (UNIST) **magnetic-tweezers (MT) bead-tracking and experiment-control software**, which today runs as a LabVIEW program.

> **Status: design phase.** Decisions and specifications are being written. There is no runnable code yet. The LabVIEW program stays in use for experiments until this port has been validated against it.

## Why

The current program is a large LabVIEW VI. It runs on a single PC and handles six jobs: camera acquisition, bead tracking, magnet and rotor motors, the piezo stage, the force-clamp schedule, and data saving.

It works, but it is hard to maintain and hard to extend. Two problems are known:
- frames are lost at high frame rates and with many beads;
- adding a second camera for MT-TIRF (an Andor iXon EMCCD and a Coherent OBIS laser) would be difficult.

The goal of this port:
- **The same results.** Tracking output must match the LabVIEW program within a stated tolerance, then be confirmed by experiment.
- **Maintainable by people.** Plain Python, documented, tested. After the project ends it must be fully usable and maintainable without any AI tools.
- **Extensible.** Clean interfaces for devices, tracking algorithms, experiment protocols and data formats.

## Planned design (summary)

| Part | Plan |
|---|---|
| Language | Python. Hot paths in numba; an existing CUDA kernel for many beads |
| Tracking | First a faithful port of the current algorithm (Croquette-style XY, radial-profile/phase Z). Each stage can be swapped so alternatives can be compared one by one |
| Devices | One interface per device type, each with a simulator. Camera interface supports several cameras at once |
| Timing | The JAI camera is the master clock. An Arduino counts its frames and triggers the EMCCD every N frames. The PC never generates triggers |
| Data | The existing `.tra` / `.cal` files are reproduced byte-identical (existing MATLAB analysis keeps working), plus a new HDF5 file on a common frame axis |
| Safety | Emergency stop in the UI. After a crash, device state is only queried on restart; nothing moves automatically |

Details and reasons: [docs/decisions/](docs/decisions/).

## Hardware (current rig)

| Device | Interface |
|---|---|
| JAI SP-5000M-USB camera | NI-IMAQdx (C API via ctypes) |
| PI C-863 / M-126 magnet stage | serial, PI GCS text commands |
| Autonics PMC-2HS rotor | serial text commands |
| ASI Tiger stage / piezo | serial text commands |
| Andor iXon Ultra EMCCD (planned, MT-TIRF) | Andor SDK2 (`atmcd64d.dll`) |
| Coherent OBIS laser (planned) | serial / modulation input |
| Arduino UNO-compatible (planned, frame sync) | hardware counter / trigger |

## Repository layout

```
docs/            documents for people (permanent)
  decisions/       design decisions and why they were made
  format/          data file formats
CLAUDE.md        working rules for AI assistants during development (AGENTS.md is the same text)
CONTRIBUTING.md  how to collaborate
```

Planned additions: `src/` (the package), `tests/`, `docs/spec/` (behavior specification of the LabVIEW program), `docs/manuals/` (one manual per device), `docs/install/`.

## Relation to other repositories

- [MT_LabVIEW](https://github.com/SihNho/MT_LabVIEW): the ongoing LabVIEW work (parallelization, GPU tracking). It continues in parallel, and this port reuses its verified pieces: the NumPy reference of the tracking kernel, the CUDA kernel, and the device notes.

## License

To be decided before code is added.
