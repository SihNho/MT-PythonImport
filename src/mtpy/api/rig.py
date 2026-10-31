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
import os
import subprocess
import sys
import threading

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


def labview_running():
    """True when LabVIEW.exe runs: the program refuses to open the rig beside it instead of closing it (RULES.md 28)."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq LabVIEW.exe", "/FO", "CSV", "/NH"],
                             check=False, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "LabVIEW.exe" in out


def acquire(purpose):
    """Hold the rig lock for this process. Adopts a wrapper's RIGLOCK_TOKEN; otherwise acquires as HOLDER. NotReady
    when the rules refuse (experiment, another live holder, stale lock - never taken over here) or LabVIEW runs."""
    with _lock:
        if _held["token"]:
            return
        rl = _riglock()
        token = os.environ.get("RIGLOCK_TOKEN")
        own = not token
        if own:
            if labview_running():
                raise NotReady("LabVIEW is running: close it first; the program never closes it itself")
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
            "rig_state": (st.get("rig_state") or {}).get("value")}
