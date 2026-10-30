# 0026 — The program holds the rig lock itself and shuts the rig down visibly

**Decided:** 2026-10-30 (owner, in chat): "이제 프로그램 작성 시작되었으니, 해당 프로그램은 V6 rig session hook을 통하면 안될듯. 지금은 자체 프로젝트만으로 통제 해야하고 ... 프로그램 내부에 자체적인 limit이 있어야지 훅을 통한 통제는 없어야함. (물론 개발하다가 프로그램이 아닌 shell script 직접 작성하는 경우는 훅이 살아있어야겠고) rig confine하는 방법이 분리되어야 할 시점으로 보임" and "프로그램 사용 마치고 종료할 때 기계 disconnect 해주는 프로토콜 필요할듯"; chosen "Shutdown + lock".

## Decision
1. **Two ways to confine the rig, kept apart.** The program (`mtpy`, the GUI) is confined by its own code: the
   safety profile, the motion gate (0025), the emergency stop, and now the shared rig lock taken by the program
   itself. Shell scripts and agent jobs stay under V6 `tools/rig_session.py` and the chat hooks as before
   (`G:\Codes\rig\RULES.md`); this project's CLAUDE.md rule 4 ("until this project has its own gate ... V6") is
   satisfied and its wording updated.
2. **The lock in the program** (`src/mtpy/api/rig.py`): `api.devices.connect` with any backend but `sim` acquires
   the shared lock as holder `mtpy` (same `G:\Codes\rig\rig_lock.json`, same `riglock.py`); a wrapper's
   `RIGLOCK_TOKEN` is adopted instead when present, so the old way still works. Refused (experiment state, another
   live holder, a stale lock - never taken over by the program) -> `NotReady`, nothing opened. LabVIEW running ->
   refused too; the program never closes LabVIEW. A thread re-checks `permitted` every 30 s and engages the
   emergency stop when it is lost (RULES.md 2). `disconnect` releases the lock only after every device closed
   without error; a failed cleanup keeps the lock (RULES.md 3) so the lock file says the rig is not clean.
3. **Shutdown is a visible sequence** (`src/mtpy/gui/shutdown.py`, [design/shutdown.md](../design/shutdown.md)):
   stop protocol -> stop acquisition -> close each device in `api.devices.CLOSE_ORDER` (magnet home + limits
   released first; the iXon's warm-up wait shows as its step) -> release the lock. Disconnect and closing the
   window both run it in a modal dialog; the first failure stops it, the dialog stays open with Retry (a failed
   device is reopened and closed again) or "Close anyway", which leaves the lock held and is logged.
4. The rig state (assembled / disassembled / experiment) is still read only; it changes on the user's word.
5. Open: once the program is released for experiments, whether it should still hold the lock (RULES.md CR-5 says
   the experiment software is outside the lock) is the owner's call then; during development it holds it.

## Consequences
- `MT Tracker (rig).cmd` runs the GUI directly; the lock log is the program's event list and the rig lock file.
- Tests never touch the real lock: `tests/conftest.py` `fake_riglock` (autouse) stands in for `riglock.py`.
- Crash recovery (the program dies with devices open) is still the stale-lock path of RULES.md, done by a person.
