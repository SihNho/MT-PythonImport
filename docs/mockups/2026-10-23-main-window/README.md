# Main-window mock-up (2026-10-23, version 2)

Source of the clickable mock-up at https://claude.ai/artifact/Hg7YRQbKfDN8jZyEDeMLHd (private until shared). Mock data
only; no device code.

- `Main.dc.html` - the one artboard (a "Design Component" page: markup plus a `class Component extends DCLogic` script).
- `canvas.json` - the canvas index of that artifact.

It does **not** open as a plain web page: it needs the artifact runtime (`support.js`) the canvas provides. It is kept
here as the record of the design (layout, steps, controls, wording) for the PySide6 GUI of plan phase 8. Requirements
it covers: [ui-requirements.md](../../spec/ui-requirements.md) U1-U21 (see its "Next" section for what is missing).
