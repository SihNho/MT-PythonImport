# 0009 — Development method, shared rig, documents

**Decided:** 2026-10-21

## Method
- **Where:** git on GitHub, with branches and pull requests. Development happens locally on the rig PC, because hardware access is needed in the end.
- **Review:** an AI assistant reviews code changes; the project owner checks behavior and results. Changes to hardware-safety code are summarized in plain words and confirmed separately.
- **Checks:** pytest and ruff. Six test tiers (see CONTRIBUTING.md). Device drivers default to simulators.
- **AI-assistant tooling (development period only):**
  - **Graphify** (Apache-2.0): a knowledge graph of the repo; its output is local and git-ignored.
  - **Ponytail** (MIT): a "smallest complete change" ruleset, with exceptions for faithful-port code, file formats, the decided architecture and safety code (see `CLAUDE.md`).
  - Both are installed project-scoped. They are not part of the application.
- **Python environment:** the project uses its **own virtual environment**, so packages used by the LabVIEW project's tools on the same PC are never changed.

## The rig is shared
- The LabVIEW project (MT_LabVIEW) keeps running in parallel on the same PC and rig.
- **A shared, machine-readable rig lock** holds the rig state (disassembled / assembled / experiment, changed only on the owner's word) and the current holder. Both projects use it for every development job that touches a device.
- **During an experiment, AI sessions may only read and discuss:** data, logs, troubleshooting, read-only screenshots. Hooks block device access, LabVIEW automation, process kills, lock operations and installs.
- **Until this project has its own approved motion gate,** motion during development goes through the LabVIEW project's gate. The final application keeps its own safety layer but contains no development-lock code (decision 0001).
- **Pieces reused from MT_LabVIEW** (the tracking reference, the CUDA kernel, device notes) stay owned by that project. Copies used here are pinned by hash.

## Documents
- **English by default;** a Korean version is optional.
- **People's documents** live in `docs/` and are permanent:
  - user manual and install guide;
  - device manuals;
  - behavior specification and data formats;
  - maintenance guide;
  - decisions.
- **AI working notes** live in `CLAUDE.md` / `AGENTS.md` and later `dev/`. They are archived when the project ends.
- **Each fact is written in one place.**

## Behavior specification (`docs/spec/`, next)
- One form per feature, laid out along the experiment flow: live view and motors → bead picking → calibration (Z scan → `.cal`) → experiment → save and stop.
- Each form lists:
  - trigger, inputs, steps, outputs;
  - side effects (does it move hardware?);
  - timing and errors;
  - evidence and its level (wiring, text, or owner's statement);
  - the owner's intent;
  - port / change / drop.
- **Coverage is checked mechanically:** every front-panel control and every case/event frame maps to a feature, or is marked unknown.
