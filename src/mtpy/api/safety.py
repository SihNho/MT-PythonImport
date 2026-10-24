"""The rig safety profile (decision 0015 item 5; docs/design/api.md section 3).

The limits live in a versioned JSON file, not in code: `config/safety_profile.json` is the active profile and
`config/safety_profiles/<version>.json` keeps every version that was ever active (who, when, why, and the
re-commissioning report). Each limit entry is

    {"min": number | null, "max": number | null, "unit": "mm", "relative_to": null | "session_start",
     "verified": bool, "source": "where the number comes from"}

A null bound means "not set yet": every request for that quantity is refused until a rig-admin sets it. A
`relative_to: "session_start"` window is checked against the position read at session start (`origin`).
Laser powers are one entry per laser: `laser_power_mW.<laser>`.

Anyone may read the profile. Only the 'rig-admin' caller may propose or activate a change, and activation needs a
re-commissioning report that names every new or changed limit as checked on the rig. Scripts, plug-ins and the AI
gateway get SafetyRefused on any write.
"""
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from . import events
from .errors import NotReady, SafetyRefused

# Repository layout (src/mtpy/api/safety.py -> <repo>/config); MTPY_CONFIG overrides it for an installed copy.
CONFIG = Path(os.environ.get("MTPY_CONFIG", Path(__file__).resolve().parents[3] / "config"))
ADMIN = "rig-admin"
_ENTRY_KEYS = {"min", "max", "unit", "relative_to", "verified", "source"}

_active = None


def _path():
    return CONFIG / "safety_profile.json"


def _history(version):
    return CONFIG / "safety_profiles" / f"{version}.json"


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _validate(p):
    """Raise ValueError unless p is a well-formed profile dict."""
    if not (isinstance(p.get("version"), int) and p["version"] >= 1):
        raise ValueError("profile 'version' must be an integer >= 1")
    for k in ("created", "by", "reason"):
        if not (isinstance(p.get(k), str) and p[k].strip()):
            raise ValueError(f"profile {k!r} must be a non-empty string")
    if not isinstance(p.get("limits"), dict):
        raise TypeError("profile 'limits' must be an object")
    for q, e in p["limits"].items():
        if not isinstance(e, dict) or set(e) != _ENTRY_KEYS:
            raise ValueError(f"limit {q!r} must have exactly the keys {sorted(_ENTRY_KEYS)}")
        for b in ("min", "max"):
            if e[b] is not None and not _is_number(e[b]):
                raise ValueError(f"limit {q!r} {b} must be a number or null")
        if e["min"] is not None and e["max"] is not None and e["min"] > e["max"]:
            raise ValueError(f"limit {q!r} has min > max")
        if e["relative_to"] not in (None, "session_start") or not isinstance(e["verified"], bool):
            raise ValueError(f"limit {q!r}: relative_to must be null or 'session_start', verified a boolean")


def _freeze(o):
    if isinstance(o, dict):
        return MappingProxyType({k: _freeze(v) for k, v in o.items()})
    if isinstance(o, list):
        return tuple(_freeze(v) for v in o)
    return o


def _thaw(o):
    if isinstance(o, MappingProxyType):
        return {k: _thaw(v) for k, v in o.items()}
    if isinstance(o, tuple):
        return [_thaw(v) for v in o]
    return o


def load_active():
    """Read the active profile from disk, make it the one in force, and return its read-only view."""
    global _active
    path = _path()
    if not path.exists():
        raise NotReady(f"no rig safety profile at {path}; every acting call is refused until one exists")
    p = json.loads(path.read_text(encoding="utf-8"))
    _validate(p)
    _active = _freeze(p)
    return _active


def profile():
    """The active profile as a read-only mapping (version, created, by, reason, limits)."""
    return _active if _active is not None else load_active()


def versions():
    """Every profile version kept in the history folder, oldest first."""
    folder = CONFIG / "safety_profiles"
    return sorted(int(f.stem) for f in folder.glob("*.json") if f.stem.isdigit()) if folder.exists() else []


def check(quantity, value, origin=None):
    """Refuse `value` for `quantity` unless the active profile allows it. Never clamps.

    origin: the position read at session start, required for a `relative_to: "session_start"` window.
    Example: `check("magnet_position_mm", 12.0)`; `check("stage_x_mm", 10.3, origin=10.0)`.
    """
    p = profile()
    v = p["version"]
    e = p["limits"].get(quantity)
    if e is None:
        raise SafetyRefused(f"{quantity} is not in the rig safety profile v{v}; every request for it is refused")
    unit = e["unit"]
    if not _is_number(value):
        raise SafetyRefused(f"{quantity} {value!r} is not a finite number")
    if e["min"] is None or e["max"] is None:
        raise SafetyRefused(f"{quantity} has no limit set in the rig safety profile v{v} "
                            f"(min {e['min']}, max {e['max']}); a rig-admin must set it first")
    lo, hi, where = e["min"], e["max"], ""
    if e["relative_to"]:
        if not _is_number(origin):
            raise SafetyRefused(f"{quantity} is limited relative to the {e['relative_to']} position, "
                                f"which was not given (origin={origin!r})")
        lo, hi, where = origin + lo, origin + hi, f" ({e['relative_to']} {origin:g} {unit} + [{e['min']:g}, {e['max']:g}])"
    if not lo <= value <= hi:
        raise SafetyRefused(f"{quantity} {value:g} {unit} is outside the allowed range [{lo:g}, {hi:g}] {unit}"
                            f"{where} of the rig safety profile v{v}")


def _require_admin(action):
    who = events.caller()
    if who != ADMIN:
        events.log("refused", request={"safety_profile": action})
        raise SafetyRefused(f"only the rig-admin settings screen may {action} the rig safety profile, not {who!r}")


@dataclass(frozen=True)
class Pending:
    """A proposed profile, not yet active. `changed`: the new or changed limits the re-commissioning must check."""
    profile: object
    base_version: int
    changed: tuple


@dataclass(frozen=True)
class RecommissioningReport:
    """What the guided re-commissioning found: `checked[quantity] is True` for each limit moved to and read back."""
    by: str
    checked: dict
    notes: str = ""
    t: float = field(default_factory=time.time)


def propose_change(new_limits, by, reason):
    """Propose a new set of limits (the whole `limits` object). Returns a Pending; nothing changes until activate()."""
    _require_admin("change")
    cur = profile()
    p = {"version": cur["version"] + 1, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by, "reason": reason,
         "limits": json.loads(json.dumps(new_limits))}
    _validate(p)
    old = _thaw(cur["limits"])
    changed = tuple(sorted(q for q, e in p["limits"].items() if old.get(q) != e))
    events.log("safety_profile", request={"action": "propose", "version": p["version"], "changed": list(changed)})
    return Pending(_freeze(p), cur["version"], changed)


def activate(pending, recommissioning_report):
    """Make a pending profile active after its re-commissioning. Every changed limit must be checked in the report.
    The old version stays in the history folder; the new one is written there and becomes the active file."""
    global _active
    _require_admin("activate")
    cur = profile()
    if pending.base_version != cur["version"]:
        raise SafetyRefused(f"the proposal was made against profile v{pending.base_version}, "
                            f"but v{cur['version']} is active now; propose again")
    r = recommissioning_report
    if not isinstance(r, RecommissioningReport):
        raise SafetyRefused("activation needs a RecommissioningReport")
    missing = [q for q in pending.changed if r.checked.get(q) is not True]
    if missing:
        raise SafetyRefused(f"the re-commissioning report does not show these new limits as checked: {missing}")
    p = _thaw(pending.profile)
    p["recommissioning"] = {"by": r.by, "t": r.t, "checked": dict(r.checked), "notes": r.notes}
    _history(cur["version"]).parent.mkdir(parents=True, exist_ok=True)
    if not _history(cur["version"]).exists():          # keep the outgoing version even if it was never archived
        _history(cur["version"]).write_text(json.dumps(_thaw(cur), indent=2), encoding="utf-8")
    if _history(p["version"]).exists():
        raise SafetyRefused(f"profile v{p['version']} already exists in the history; versions are never overwritten")
    text = json.dumps(p, indent=2)
    _history(p["version"]).write_text(text, encoding="utf-8")
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(_path())
    _active = _freeze(p)
    events.log("safety_profile", request={"action": "activate", "version": p["version"]},
               extra={"changed": list(pending.changed)})
    return _active
