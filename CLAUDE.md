# LabVIEW2Scr — core rules (Claude Code and Codex read the same text: CLAUDE.md = AGENTS.md)

The script port of the Kim Lab MT tracking program (LabVIEW -> script language; later the Andor iXon). A SEPARATE
project from V6 (user 2026-10-20: "이거는 별도 프로젝트로 기획하는게 좋겠다"); the language and the plan are the user's
to choose. V6 decision record: V6 `docs/decisions/script_port_is_a_separate_project.md`.

## The rig — read `G:\Codes\rig\RULES.md` first; it applies here in full

User 2026-10-21: "그 규칙들이 LabVIEW2Scr 프로젝트에서도 적용되도록 하면 좋겠음." In short:
1. **The rig state** (`분해` disassembled / `조립` assembled / `실험중` experiment) changes only on the user's word;
   record it with `py G:\Codes\rig\riglock.py set-state ... --by chat --note "<the user's words>"`.
   Experiment = touch nothing.
2. **Take the shared lock** (`G:\Codes\rig\riglock.py`) before any device call — camera, PI, ASI, rotor, iXon, laser,
   Arduino — and release it after a verified cleanup. Check `permitted` before each step and at least every 30 s.
   Another live holder -> wait; experiment / stale / error -> stop.
3. **Cleanup always returns the rig to its initial condition** (devices closed, motor limits released with readback),
   also after a failure and when the user declares an experiment mid-job. Cleanup failed -> keep the lock, report.
4. **Motion only through a gate that checks the lock and enforces the envelope.** The program has its own: the motion
   gate (decision 0025) and the rig lock taken by `api.devices.connect` (decision 0026); it never runs under the V6
   wrapper. Shell scripts and agent jobs still go through V6 `tools/motor_gate.py` (CLI) and V6 `tools/rig_session.py`.
   Never open a motor port directly.
5. **Never** change `RIGLOCK_DIR` / `RIGLOCK_TOKEN`, edit `rig_lock.*` by hand, take over a stale lock or break the
   mutex without the user's own words; no recovery during an experiment.
6. **No serial / VISA call on the frame acquisition path.**

## General (same spirit as V6)
- Never start or stop work on your own; the user starts and stops.
- Never modify an original LabVIEW file; numbers out must stay identical to the original unless the user decides
  otherwise (acceptance is numeric).
- Secrets only in user environment variables.
- Answer the user first; write in plain words; state evidence and confidence.
- **Language:** chat with the user in Korean. Documents, code, comments and commit messages are in English. Korean
  is allowed only inside quotes (verbatim user words, data strings) or in a `*.ko.md` translation; the hook
  `.claude/hooks/english_only.py` enforces this.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
- Local setup on the rig PC: graphify lives in its own venv, not on PATH. Call it as
  `"$USERPROFILE/tools/graphify-venv/Scripts/graphify.exe"`. `graphify-out/` is git-ignored (local only).

## ponytail (smallest complete change)

Always apply the ruleset below (Ponytail by Dietrich Gebert, MIT; skills in `.claude/skills/ponytail*`).

@.claude/rules/ponytail.md

**Project exceptions — these are never "simplified":**
- Code that reproduces the LabVIEW program's computation, including its quirks (single precision, the out-of-range
  index, round-half-even), and code that writes the existing `.tra` / `.cal` formats. The numbers must stay
  identical (decisions 0003, 0004, 0008).
- The architecture recorded in `docs/decisions/` counts as asked for: device interfaces with simulators, swappable
  tracking stages, the safety layer, crash recovery.
- Hardware safety: motion limits, envelope checks, cleanup, the emergency stop.
