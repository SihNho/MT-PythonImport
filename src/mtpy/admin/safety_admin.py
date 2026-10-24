"""The write path of the rig safety profile (decision 0015 item 5): propose a change, then activate it after the
guided re-commissioning check. Not part of the public API; `mtpy.api` never imports this module.

Every write needs an `AdminSession`, which only `open_admin_session(reason)` creates. In this phase that function
refuses when the current caller context is a script, a plug-in or the AI gateway, and accepts 'gui' and
'rig-admin'. This is a guard against mistakes, NOT real protection: any Python code in the same process can set its
own caller name or import this module. Real protection - binding `open_admin_session` to a GUI login with the
rig-admin role, and file permissions on `config/` - is phase 8 work (docs/design/api.md section 3).

Every step is logged as a `safety_profile` event (who = caller, when = event time, why = the session reason and the
proposal's reason).
"""
import json
import time
from dataclasses import dataclass, field

from mtpy.api import events, safety
from mtpy.api.errors import SafetyRefused

_ALLOWED_CALLERS = ("gui", "rig-admin")
_KEY = object()          # only this module can build an AdminSession or a _Pending


def _require_trusted_caller(action):
    who = events.caller()
    if who not in _ALLOWED_CALLERS:
        events.log("refused", request={"safety_profile": action}, reason=f"caller {who!r} may not {action}")
        raise SafetyRefused(f"only the rig-admin settings screen may {action} the rig safety profile, not {who!r}")
    return who


class AdminSession:
    """The admin token. Create it with `open_admin_session(reason)`, never directly."""

    def __init__(self, key, who, reason):
        if key is not _KEY:
            raise SafetyRefused("an AdminSession is created only by open_admin_session(reason)")
        self.who, self.reason, self.t = who, reason, time.time()


def open_admin_session(reason):
    """Open an admin session for changing the rig safety profile. To be bound to a GUI login in phase 8.

    Refused (SafetyRefused) when the current caller is a script, a plug-in, the AI gateway or undeclared code, or
    when no reason is given. Example: `with as_caller("gui"): s = open_admin_session("magnet mount replaced")`.
    """
    who = _require_trusted_caller("open an admin session for")
    if not (isinstance(reason, str) and reason.strip()):
        raise SafetyRefused("an admin session needs a reason")
    s = AdminSession(_KEY, who, reason)
    events.log("safety_profile", request={"action": "open_admin_session"}, reason=reason)
    return s


def _require_session(session, action):
    _require_trusted_caller(action)
    if not isinstance(session, AdminSession):
        events.log("refused", request={"safety_profile": action}, reason="no admin session")
        raise SafetyRefused(f"{action} the rig safety profile needs an AdminSession from open_admin_session()")


@dataclass(frozen=True)
class RecommissioningReport:
    """What the guided re-commissioning found: `checked[quantity] is True` for each limit moved to and read back."""
    by: str
    checked: dict
    notes: str = ""
    t: float = field(default_factory=time.time)


class _Pending:
    """A proposed profile, not yet active. Built only by propose_change(); activate() re-checks everything."""

    def __init__(self, key, profile):
        if key is not _KEY:
            raise SafetyRefused("a pending profile is created only by propose_change()")
        self.profile = profile


def _changed(old_limits, new_limits):
    """The limits that are new or differ from the active profile (removed ones need no check: they refuse)."""
    return sorted(q for q, e in new_limits.items() if old_limits.get(q) != e)


def propose_change(session, new_limits, by, reason, allow_unverified=None):
    """Propose a new set of limits (the whole `limits` object). Returns a pending proposal; nothing changes until
    activate(). allow_unverified: None keeps the active profile's setting."""
    _require_session(session, "change")
    cur = safety.profile()
    limits = json.loads(json.dumps(new_limits))
    p = {"version": cur["version"] + 1, "base_version": cur["version"],
         "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by, "reason": reason,
         "allow_unverified": cur["allow_unverified"] if allow_unverified is None else allow_unverified,
         "unverified": safety.unverified_of(limits) if isinstance(limits, dict) else None, "limits": limits}
    safety._validate(p)
    changed = _changed(safety._thaw(cur["limits"]), p["limits"])
    events.log("safety_profile", request={"action": "propose", "version": p["version"], "changed": changed},
               reason=reason, session_reason=session.reason)
    return _Pending(_KEY, safety._freeze(p))


def activate(session, pending, recommissioning_report):
    """Make a pending profile active after its re-commissioning.

    The candidate is re-validated and its diff against the ACTIVE profile is recomputed here; the report must show
    every new or changed limit as checked. A candidate not based on the active version is refused. The old version
    stays in the history folder; the new one is written there and becomes the active file.
    """
    _require_session(session, "activate")
    if not isinstance(pending, _Pending):
        raise SafetyRefused("activate() needs a proposal from propose_change()")
    r = recommissioning_report
    if not isinstance(r, RecommissioningReport):
        raise SafetyRefused("activation needs a RecommissioningReport")
    cur = safety.profile()
    p = safety._thaw(pending.profile)
    try:
        safety._validate(p)
    except (TypeError, ValueError) as e:
        raise SafetyRefused(f"the proposed profile is not valid: {e}") from e
    if p.get("base_version") != cur["version"] or p["version"] != cur["version"] + 1:
        raise SafetyRefused(f"the proposal was made against profile v{p.get('base_version')}, "
                            f"but v{cur['version']} is active now; propose again")
    changed = _changed(safety._thaw(cur["limits"]), p["limits"])
    missing = [q for q in changed if r.checked.get(q) is not True]
    if missing:
        raise SafetyRefused(f"the re-commissioning report does not show these new limits as checked: {missing}")
    p["recommissioning"] = {"by": r.by, "t": r.t, "checked": dict(r.checked), "notes": r.notes}
    hist_old, hist_new = safety._history(cur["version"]), safety._history(p["version"])
    hist_old.parent.mkdir(parents=True, exist_ok=True)
    if not hist_old.exists():                           # keep the outgoing version even if it was never archived
        hist_old.write_text(json.dumps(safety._thaw(cur), indent=2), encoding="utf-8")
    if hist_new.exists():
        raise SafetyRefused(f"profile v{p['version']} already exists in the history; versions are never overwritten")
    text = json.dumps(p, indent=2)
    hist_new.write_text(text, encoding="utf-8")
    tmp = safety._path().with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(safety._path())
    active = safety.load_active()
    events.log("safety_profile", request={"action": "activate", "version": p["version"]}, changed=changed,
               allow_unverified=p["allow_unverified"], session_reason=session.reason)
    return active
