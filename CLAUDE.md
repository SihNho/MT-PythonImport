# LabVIEW2Scr — core rules (Claude Code and Codex read the same text: CLAUDE.md = AGENTS.md)

The script port of the Kim Lab MT tracking program (LabVIEW -> script language; later the Andor iXon). A SEPARATE
project from V6 (user 2026-10-20: "이거는 별도 프로젝트로 기획하는게 좋겠다"); the language and the plan are the user's
to choose. V6 decision record: V6 `docs/decisions/script_port_is_a_separate_project.md`.

## The rig — read `G:\Codes\rig\RULES.md` first; it applies here in full

User 2026-10-21: "그 규칙들이 LabVIEW2Scr 프로젝트에서도 적용되도록 하면 좋겠음." In short:
1. **The rig state** (분해 / 조립 / 실험중) changes only on the user's word; record it with
   `py G:\Codes\rig\riglock.py set-state ... --by chat --note "<the user's words>"`. 실험중 = touch nothing.
2. **Take the shared lock** (`G:\Codes\rig\riglock.py`) before any device call — camera, PI, ASI, rotor, iXon, laser,
   Arduino — and release it after a verified cleanup. Check `permitted` before each step and at least every 30 s.
   Another live holder -> wait; experiment / stale / error -> stop.
3. **Cleanup always returns the rig to its initial condition** (devices closed, motor limits released with readback),
   also after a failure and when the user declares an experiment mid-job. Cleanup failed -> keep the lock, report.
4. **Motion only through a gate that checks the lock and enforces the envelope.** Until this project has its own gate
   approved by the user, every motion goes through V6 `tools/motor_gate.py` (CLI) and every rig job through V6
   `tools/rig_session.py`. Never open a motor port directly.
5. **Never** change `RIGLOCK_DIR` / `RIGLOCK_TOKEN`, edit `rig_lock.*` by hand, take over a stale lock or break the
   mutex without the user's own words; no recovery during an experiment.
6. **No serial / VISA call on the frame acquisition path.**

## General (same spirit as V6)
- Never start or stop work on your own; the user starts and stops.
- Never modify an original LabVIEW file; numbers out must stay identical to the original unless the user decides
  otherwise (acceptance is numeric).
- Secrets only in user environment variables.
- Answer the user first; write in plain words; state evidence and confidence.
