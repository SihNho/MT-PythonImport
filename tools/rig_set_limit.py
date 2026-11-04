"""Set one limit of the rig safety profile on the owner's word (the owner is the rig-admin), e.g. the rotor speed
that profile v9 left unset, so every rotation is refused with "rotor_speed_turns_s has no limit set ... a rig-admin
must set it first" (rig 2026-11-05):

    python tools/rig_set_limit.py rotor_speed_turns_s --max 2 --reason "owner 2026-11-05: SPD 100 = 2 turns/s"

Goes through the admin flow (propose, a re-commissioning report naming the quantity, activate): the profile's
version goes up by one and the old one stays in config/safety_profiles/. The program reads the profile when it
starts: restart the GUI afterwards. Only the quantity named changes; min and max not given are kept."""
import argparse
import time

from mtpy.admin import safety_admin as admin
from mtpy.api import events, safety


def set_limit(quantity, lo=None, hi=None, reason="", by="rig-admin (owner, tools/rig_set_limit.py)"):
    with events.as_caller("rig-admin"):
        s = admin.open_admin_session(reason)
        lim = safety._thaw(safety.profile()["limits"])
        if quantity not in lim:
            raise SystemExit(f"no quantity {quantity!r}; the profile has: {sorted(lim)}")
        q = dict(lim[quantity])
        if lo is not None:
            q["min"] = lo
        if hi is not None:
            q["max"] = hi
        q.update(verified=True, source=f"{by} {time.strftime('%Y-%m-%d %H:%M')}: {reason}")
        lim[quantity] = q
        pend = admin.propose_change(s, lim, by=by, reason=reason)
        p = admin.activate(s, pend, admin.RecommissioningReport(by=by, checked={quantity: True}))
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("quantity")
    ap.add_argument("--min", type=float, default=None)
    ap.add_argument("--max", type=float, default=None)
    ap.add_argument("--reason", required=True, help="the owner's words, kept in the profile's source and the event log")
    a = ap.parse_args(argv)
    if a.min is None and a.max is None:
        ap.error("give --min and / or --max")
    p = set_limit(a.quantity, a.min, a.max, a.reason)
    print(f"profile v{p['version']}: {a.quantity} = {p['limits'][a.quantity]}")


if __name__ == "__main__":
    main()
