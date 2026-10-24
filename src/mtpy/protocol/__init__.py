"""Protocol, illumination-sequence and analysis-recipe scripts (docs/format/grammar.md), WP5.

- `grammar`: the deterministic parser (`parse(text, file)` -> `Script`, `ScriptError` with line / column).
- `check`: validation against the public API (statement -> function, argument units) and the rig safety profile,
  before anything runs.
- `engine`: runs a checked protocol step by step on its own thread, ONLY through `mtpy.api`.

Scripts, the GUI and the AI gateway use these through `mtpy.api.protocol`, not directly.
"""
from .grammar import Diagnostic, Script, Stmt, parse

__all__ = ["Diagnostic", "Script", "Stmt", "parse"]
