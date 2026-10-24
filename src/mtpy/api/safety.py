"""The rig safety profile (decision 0015 item 5; docs/design/api.md section 3).

The limits live in a versioned JSON file, not in code: `config/safety_profile.json` is the active profile and
`config/safety_profiles/<version>.json` keeps every version that was ever active (who, when, why, and the
re-commissioning report). Each limit entry is

    {"min": number | null, "max": number | null, "unit": "mm", "relative_to": null | "session_start",
     "verified": bool, "source": "where the number comes from"}

A null bound means "not set yet": every request for that quantity is refused until a rig-admin sets it. A
`relative_to: "session_start"` window is checked against the position read at session start (`origin`).
Laser powers are one entry per laser: `laser_power_mW.<laser>`.

Unverified limits: an entry with `"verified": false` is treated like an unset limit (every request refused) unless the
profile has `"allow_unverified": true`. The profile also lists those entries in `"unverified"` (checked against the
flags on load, so the list cannot drift). When unverified limits are allowed, `check()` returns False for them and
every acting call logs an `unverified-limit` warning event.

This module is the READ side and is part of the public API: `profile()`, `check()`, `versions()`, `load_active()`.
Nothing here writes the profile. The write path (propose / activate with re-commissioning) is
`mtpy.admin.safety_admin`, which `mtpy.api` never imports.
"""
import json
import math
import numbers
import os
from pathlib import Path
from types import MappingProxyType

from .errors import NotReady, SafetyRefused

# Repository layout (src/mtpy/api/safety.py -> <repo>/config); MTPY_CONFIG overrides it for an installed copy.
CONFIG = Path(os.environ.get("MTPY_CONFIG", Path(__file__).resolve().parents[3] / "config"))
_ENTRY_KEYS = {"min", "max", "unit", "relative_to", "verified", "source"}

_active = None


def _path():
    return CONFIG / "safety_profile.json"


def _history(version):
    return CONFIG / "safety_profiles" / f"{version}.json"


def _is_number(v):
    """A finite real number (numpy scalars included), not a bool. An int too large for a float (e.g. 10**400) is
    treated as not finite instead of raising OverflowError."""
    if not isinstance(v, numbers.Real) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(float(v))
    except (OverflowError, ValueError):
        return False


def unverified_of(limits):
    """The sorted names of the limits marked `"verified": false`."""
    return sorted(q for q, e in limits.items() if not e["verified"])


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
    if not isinstance(p.get("allow_unverified"), bool):
        raise TypeError("profile 'allow_unverified' must be true or false")
    if p.get("unverified") != unverified_of(p["limits"]):
        raise ValueError(f"profile 'unverified' must list exactly the limits with verified=false: "
                         f"{unverified_of(p['limits'])}")
    if "base_version" in p and not (isinstance(p["base_version"], int) and p["base_version"] == p["version"] - 1):
        raise ValueError("profile 'base_version' must be the integer version - 1")


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
    Returns True when the limit used is verified on the rig, False when it is unverified and the profile allows
    unverified limits (the caller logs the `unverified-limit` warning). Raises SafetyRefused otherwise.
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
    if not e["verified"] and not p["allow_unverified"]:
        raise SafetyRefused(f"{quantity} limit [{e['min']:g}, {e['max']:g}] {unit} is not verified on the rig "
                            f"(rig safety profile v{v}, allow_unverified false); it is treated as unset and every "
                            "request is refused until a rig-admin verifies it or allows unverified limits")
    lo, hi, where = e["min"], e["max"], ""
    if e["relative_to"]:
        if not _is_number(origin):
            raise SafetyRefused(f"{quantity} is limited relative to the {e['relative_to']} position, "
                                f"which was not given (origin={origin!r})")
        lo, hi, where = origin + lo, origin + hi, f" ({e['relative_to']} {origin:g} {unit} + [{e['min']:g}, {e['max']:g}])"
    if not lo <= value <= hi:
        raise SafetyRefused(f"{quantity} {value:g} {unit} is outside the allowed range [{lo:g}, {hi:g}] {unit}"
                            f"{where} of the rig safety profile v{v}")
    return e["verified"]
