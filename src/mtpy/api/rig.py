"""The shared rig lock, held by the program itself (decision 0026; `G:\\Codes\\rig\\RULES.md` 2).

Owner 2026-10-30: the program controls the rig on its own - its limits are inside (safety profile + motion gate) and
it must not depend on the V6 `rig_session.py` wrapper or the chat hooks, which stay for shell scripts. So
`api.devices.connect` with a real backend calls `acquire()`: the process takes the lock as holder "mtpy" (or adopts
the token a wrapper already put in `RIGLOCK_TOKEN`, so running inside the wrapper still works), a thread re-checks
`permitted` every HEARTBEAT_S and engages the emergency stop when it is lost, and `release()` gives the lock back only
after `disconnect` has closed every device without error (RULES.md 3: cleanup failed -> keep the lock, report).
The rig state (assembled / disassembled / experiment) is only read here; it changes on the user's word alone.

    api.rig.status()     # {"held": bool, "own": bool, "holder": ..., "rig_state": ...}
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

from . import estop, events
from .errors import NotReady

RIG_DIR = r"G:\Codes\rig"
HOLDER = "mtpy"
HEARTBEAT_S = 30.0
WORK_STATES = ("assembled", "disassembled")        # = devices.gate.MOTOR_STATES; experiment never
_lock = threading.Lock()
_held = {"token": None, "own": False, "stop": None}


def _riglock():
    if RIG_DIR not in sys.path:
        sys.path.insert(0, RIG_DIR)
    import riglock
    return riglock


def acquire(purpose):
    """Hold the rig lock for this process. Adopts a wrapper's RIGLOCK_TOKEN; otherwise acquires as HOLDER. NotReady
    when the rules refuse (experiment, another live holder, stale lock - never taken over here). Whether LabVIEW is
    open is not the program's business (owner 2026-11-04: that rule lives in the chat hooks); a device another
    program holds fails to open with the driver's own error."""
    with _lock:
        if _held["token"]:
            return
        rl = _riglock()
        token = os.environ.get("RIGLOCK_TOKEN")
        own = not token
        if own:
            try:
                token = rl.acquire(HOLDER, purpose)
            except rl.Refused as e:
                events.log("rig_lock", action="refused", reason=str(e))
                raise NotReady(f"rig lock refused: {e}. A stale lock means a program ended without its cleanup: a person "
                               "checks the rig (magnet position and PI limits, iXon cooling) and takes the lock over by "
                               "hand per G:/Codes/rig/RULES.md; this program never does") from e
            os.environ["RIGLOCK_TOKEN"] = token          # the drivers' gate reads it from here
        if not rl.permitted(token, WORK_STATES):
            if own:
                rl.release(token)
                os.environ.pop("RIGLOCK_TOKEN", None)
            raise NotReady("rig lock held but work not permitted (rig state or recovering holder)")
        stop = threading.Event()
        _held.update(token=token, own=own, stop=stop)
        threading.Thread(target=_heartbeat, args=(token, stop), name="rig-lock-heartbeat", daemon=True).start()
        events.log("rig_lock", action="adopted" if not own else "acquired", purpose=purpose)


RECOVERY_DIR = Path(RIG_DIR) / "recovery"


def stale():
    """The stale lock, if the rig lock is held by a process that no longer runs (a program that died without its
    cleanup: a power loss, a kill), else None."""
    st = _riglock().status()
    h = st.get("holder")
    return h if h and st.get("holder_alive") is False else None


def recover_stale(reason):
    """Take a STALE rig lock over and release it, on the user's own words (`reason`, e.g. the GUI's "Take over"
    click), so the program can connect again without a person editing the lock (owner 2026-11-04: "I cannot ask the
    agent every time"). Refused (NotReady) unless the lock is stale, the rig is not in an experiment and `reason` is
    given. What it does: riglock's take-over (logged with the reason), a recovery record in G:/Codes/rig/recovery/
    (the dead holder, the reason, what the next connect re-checks: every device is opened fresh, the PI session
    limits are rewritten at open and released at close with read-back - devices/pi.py), riglock.recovered with that
    record, release. The devices themselves are not touched here; the next connect opens them and reads them back.
    RULES.md 5 still holds: a lock held by a live process is never taken."""
    if not isinstance(reason, str) or not reason.strip():
        raise NotReady("a stale lock is taken over only on the user's own words: give the reason")
    rl = _riglock()
    h = stale()
    if h is None:
        st = rl.status()
        raise NotReady("no stale lock to recover: " + ("the lock is free" if not st.get("holder") else
                       f"the lock is held by a live process ({st['holder'].get('name')} pid {st['holder'].get('pid')})"))
    if (rl.status().get("rig_state") or {}).get("value") == "experiment":
        raise NotReady("rig state is experiment: no recovery during an experiment")
    with _lock:
        if _held["token"]:
            raise NotReady("this process already holds the lock")
        token = rl.acquire(HOLDER, "recovery of a stale lock", take_stale=True, reason=reason)
        rec = RECOVERY_DIR / time.strftime("%Y%m%d_%H%M%S_mtpy")
        rec.mkdir(parents=True, exist_ok=True)
        note = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": reason, "old_holder":
                {k: h.get(k) for k in ("name", "pid", "since", "purpose", "host")}}
        files = {}
        for item, text in (("devices_closed", ("the holder process is gone, so its device handles are closed by the OS; "
                                              "the next connect opens every device fresh and reads it back")),
                           ("limits_released", ("no PI command was sent during this take-over; the PI session limits "
                                               "are rewritten at the next open and released at close with read-back "
                                               "(mtpy.devices.pi), so a limit left by the dead session cannot survive "
                                               "the next session"))):
            p = rec / f"{item}.json"
            p.write_text(json.dumps({**note, "note": text}, indent=1), encoding="utf-8")
            files[item] = str(p)
        try:
            rl.recovered(token, files)
        finally:
            rl.release(token)
    events.log("rig_lock", action="stale_taken_over", reason=reason, old_holder=note["old_holder"], record=str(rec))
    return {"old_holder": note["old_holder"], "record": str(rec)}


def _heartbeat(token, stop):
    while not stop.wait(HEARTBEAT_S):
        try:
            ok = _riglock().permitted(token, WORK_STATES)
            reason = "permitted() false: experiment declared or lock lost"
        except Exception as e:  # noqa: BLE001 - fault list D5 (2026-10-31): a raising check must not end the monitor silently
            ok, reason = False, f"permitted() raised {type(e).__name__}: {e}"
        if not ok:
            events.log("rig_lock", action="lost", reason=reason)
            estop.engage("rig lock lost")
            return


def release():
    """Give the lock back (only an own lock; an adopted wrapper token is left to the wrapper)."""
    with _lock:
        token, own, stop = _held["token"], _held["own"], _held["stop"]
        if not token:
            return
        stop.set()
        _held.update(token=None, own=False, stop=None)
        if own:
            os.environ.pop("RIGLOCK_TOKEN", None)
            try:
                _riglock().release(token)
            except Exception as e:
                events.log("rig_lock", action="release_failed", reason=str(e))
                raise
            events.log("rig_lock", action="released")


def status():
    st = _riglock().status()
    return {"held": _held["token"] is not None, "own": _held["own"], "holder": st.get("holder"),
            "holder_alive": st.get("holder_alive"), "rig_state": (st.get("rig_state") or {}).get("value")}
