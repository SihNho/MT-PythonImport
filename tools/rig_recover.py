"""Recover the rig lock left by a dead program, without the agent (owner 2026-11-04: "I cannot ask the agent every
time"). Shows the lock's state; when it is STALE (its holder no longer runs) asks for a yes, takes it over on your
words, records the recovery in G:\\Codes\\rig\\recovery\\ and releases it. A lock held by a live process, or the rig in
an experiment, is left alone. The GUI offers the same at Connect.

    python tools/rig_recover.py            # interactive
    python tools/rig_recover.py --yes "<why>"   # no prompt; the reason is logged with the take-over
"""
import sys

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")

from mtpy.api import rig
from mtpy.api.errors import NotReady


def main():
    st = rig.status()
    print("rig lock:", "free" if not st["holder"] else f"held by {st['holder'].get('name')} (pid {st['holder'].get('pid')}, "
          f"since {st['holder'].get('since')}, {'alive' if st.get('holder_alive') else 'DEAD - stale'})")
    print("rig state:", st["rig_state"])
    if not rig.stale():
        print("nothing to recover." if not st["holder"] else "the holder is alive: close that program instead.")
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--yes":
        reason = sys.argv[2]
    else:
        print("The holder is gone (a crash or a power loss ended it without cleanup). Look at the rig first if unsure.")
        ans = input("Take the lock over? type yes: ").strip().lower()
        if ans != "yes":
            print("left as is.")
            return 1
        reason = input("why / what you checked (logged with the take-over): ").strip() or "owner via rig_recover.py"
    try:
        res = rig.recover_stale(f"owner via rig_recover.py: {reason}")
    except NotReady as e:
        print("refused:", e)
        return 2
    print("taken over and released; record:", res["record"])
    print("the lock is free: start the program and Connect (every device is opened fresh and read back).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
