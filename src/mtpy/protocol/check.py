"""Validation of a parsed protocol BEFORE anything runs (docs/format/grammar.md sections 2, 8, 10; WP5).

Three layers, each reported as `Diagnostic`s with the statement's line and the argument's column:

1. **API**: every statement maps to functions of the public layer (`API_MAP`). A function the API does not have yet
   (e.g. `api.light.load_sequence` for `light seq=`, `api.events.rule` for `if` / `wait until` / `on`) makes the
   statement an error: the protocol cannot run until that function exists. Each key's fixed unit must match the unit
   in the API parameter's name (`f` in pN -> `force_pN`).
2. **Rig safety profile** (read only, `api.safety.check`): every value that would reach an acting call, and the
   magnet speed limit every magnet move needs (`api.magnet.move_to` always checks `magnet_speed_mm_s`). A value the
   API would refuse fails here, with the step named.
3. **Rig state** (`devices=True`, done by `api.protocol.run` right before starting): the devices are connected, a
   position-to-force table is loaded and covers every force (and its position is inside the profile's magnet
   travel), the focus target from the current position is inside the window, and acquisition runs when the protocol
   records. Values that depend on what happens during the run are still checked by the API at each step.

Nothing here moves anything or logs an acting event.
"""
import inspect
import math

import numpy as np

from mtpy import api
from mtpy.api.errors import ScriptError

from .grammar import PROTOCOL_KEYS, Diagnostic

# statement (or statement:form) -> [(api function, {grammar key: API parameter that carries the value})]
API_MAP = {
    "zero": [("magnet.move_to", {})],
    "ramp": [("magnet.set_force", {"from": "force_pN", "to": "force_pN"})],
    "hold": [("magnet.set_force", {"f": "force_pN"})],
    "move": [("magnet.move_to", {"mm": "position_mm"})],
    "rotate": [("magnet.set_force", {"f": "force_pN"}), ("rotor.rotate", {"from": "turns", "to": "turns"}),
               ("rotor.position", {}), ("devices.info", {})],
    "focus": [("focus.move_to", {"um": "z_um"}), ("focus.position", {})],     # um relative -> absolute z_um
    "record": [("acq.set_recording", {})],
    "light:seq": [("light.load_sequence", {}), ("light.start_sequence", {})],
    "light:off": [("light.stop_sequence", {})],
    "mark": [("acq.mark", {}), ("events.log", {})],
    "wait:time": [],
    "wait:until": [("events.rule", {}), ("events.wait_for", {})],
    "if": [("events.rule", {})],
    "on": [("events.rule", {}), ("events.on", {})],
    "loop": [],
    "stop": [],
    "rule": [("screen.run", {})],
}
UNIT_IN_NAME = {"pN": "_pN", "mm": "_mm", "um": "_um", "turns": "turns", "s": "_s"}
MAGNET_MOVES = ("zero", "ramp", "hold", "move", "rotate")
FORCE_KEYS = {"ramp": ("from", "to"), "hold": ("f",), "rotate": ("f",)}


def _resolve(path):
    obj = api
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def walk(body):
    """Every statement of a body, nested blocks included, in source order."""
    for st in body:
        yield st
        yield from walk(st.body)
        if st.orelse:
            yield from walk(st.orelse)


class _Report:
    def __init__(self, script):
        self.script, self.errors, self.warnings = script, [], list(script.warnings)

    def err(self, st, col, msg):
        self.errors.append(Diagnostic(self.script.file, st.line, col or st.col, msg))

    def warn(self, st, col, msg):
        self.warnings.append(Diagnostic(self.script.file, st.line, col or st.col, msg, "warning"))


def _api_layer(rep, st):
    key = f"{st.kind}:{st.form}" if f"{st.kind}:{st.form}" in API_MAP else st.kind
    for fn_path, params in API_MAP.get(key, []):
        fn = _resolve(fn_path)
        if fn is None:
            form = f" {st.form}" if st.form in ("until", "seq", "off") else ""
            what = "rule" if st.kind == "rule" else f"'{st.kind}{form}'"
            msg = (f"{what} needs api.{fn_path}, which api {api.VERSION} does not have yet; this statement is parsed "
                   "but cannot run")
            if st.kind == "rule":
                rep.warn(st, st.col, f"{msg}: the rule is NOT evaluated (a screening run executes the actions only)")
            else:
                rep.err(st, st.col, msg)
            return False
        sig = inspect.signature(fn).parameters
        for gkey, param in params.items():
            if param not in sig:
                rep.err(st, st.col, f"api.{fn_path} has no parameter {param!r} for '{gkey}'")
                continue
            unit = PROTOCOL_KEYS[st.kind][gkey].unit
            if not param.endswith(UNIT_IN_NAME.get(unit, "\0")):
                rep.err(st, st.col, f"'{gkey}' is in {unit} but api.{fn_path} takes {param!r}")
    return True


def _profile(rep, st, key, quantity, value, origin=None, why=""):
    try:
        api.safety.check(quantity, value, origin)
    except api.SafetyRefused as e:
        arg = st.args.get(key)
        unit = api.safety.profile()["limits"].get(quantity, {}).get("unit", "")
        label = f"'{key}'" if arg is not None else f"the {key}"
        rep.err(st, arg.col if arg else st.col, f"{label} is {value:g} {unit}{why}; {e}")
        return False
    return True


def _magnet_speed(rep, st):
    lim = api.safety.profile()["limits"].get("magnet_speed_mm_s")
    probe = lim["max"] if lim and lim["max"] is not None else 0.0
    try:
        api.safety.check("magnet_speed_mm_s", probe)
    except api.SafetyRefused as e:
        rep.err(st, st.col, f"'{st.kind}' moves the magnet, and api.magnet.move_to checks the magnet speed against the "
                            f"rig safety profile: {e}")


def _profile_layer(rep, st):
    a = {k: v.value for k, v in st.args.items()}
    if st.kind in MAGNET_MOVES:
        _magnet_speed(rep, st)
    for k in FORCE_KEYS.get(st.kind, ()):
        _profile(rep, st, k, "magnet_force_pN", a[k])
    if st.kind == "zero":
        _profile(rep, st, "magnet target", "magnet_position_mm", 0.0, why=" (zero moves the magnet to 0 mm)")
    elif st.kind == "move":
        _profile(rep, st, "mm", "magnet_position_mm", a["mm"])
    elif st.kind == "rotate":
        for k in ("from", "to"):           # turns relative to the session-start position, as the profile window
            _profile(rep, st, k, "rotor_turns", a[k], origin=0.0, why=" from the session-start position")
        speed = abs(a["to"] - a["from"]) / a["t"]
        _profile(rep, st, "t", "rotor_speed_turns_s", speed, why=f" -> rotor speed {speed:g} turns/s")
    elif st.kind == "focus":
        _profile(rep, st, "um", "focus_z_um", a["um"], origin=0.0, why=" from the focus position at the start")


def _connected(name):
    st = api.devices.status().get(name)
    return st is not None and st["state"] in ("connected", "slow")


def _state_layer(rep, st, focus_z0):
    a = {k: v.value for k, v in st.args.items()}
    needs = {"zero": "magnet", "ramp": "magnet", "hold": "magnet", "move": "magnet", "rotate": "magnet",
             "focus": "focus"}.get(st.kind)
    for dev in ([needs] if needs else []) + (["rotor"] if st.kind == "rotate" else []):
        if not _connected(dev):
            rep.err(st, st.col, f"'{st.kind}' needs the {dev}, which is not connected (api.devices.status())")
            return
    if st.kind in FORCE_KEYS:
        table = api.magnet.force_table()
        if table is None:
            rep.err(st, st.col, f"'{st.kind}' sets a force, and no position-to-force table is loaded "
                                "(api.magnet.use_force_table, decision 0010)")
            return
        f, pos = table["force_pN"], table["position_mm"]
        for k in FORCE_KEYS[st.kind]:
            if not f[0] <= a[k] <= f[-1]:
                rep.err(st, st.args[k].col, f"'{k}' is {a[k]:g} pN; the force table {table['name']!r} covers "
                                            f"[{f[0]:g}, {f[-1]:g}] pN")
            else:
                _profile(rep, st, k, "magnet_position_mm", float(np.interp(a[k], f, pos)),
                         why=f" -> magnet position from the table {table['name']!r}")
    if st.kind == "focus" and focus_z0 is not None:
        z0, origin = focus_z0
        _profile(rep, st, "um", "focus_z_um", z0 + a["um"], origin=origin,
                 why=f" from the focus now at {z0:g} um")
    if st.kind == "record" and not api.acq.running():
        rep.err(st, st.col, "'record' needs acquisition running: api.acq.start() before the protocol")


def check(script, devices=False):
    """Validate a parsed protocol. Returns {"ok", "errors", "warnings" (Diagnostics), "min_duration_s"}.

    devices=True adds the rig-state layer (connected devices, force table, focus position, acquisition running); it
    only reads. min_duration_s: the sum of every hold / wait / ramp / record time with the loops expanded (moves not
    counted)."""
    if script.kind != "protocol":
        raise ScriptError([Diagnostic(script.file, 1, 1, f"a {script.kind} cannot run as a protocol")])
    rep = _Report(script)
    focus_z0 = None
    if devices and any(s.kind == "focus" for s in walk(script.body)) and _connected("focus"):
        focus_z0 = (api.focus.position(), api.devices.info("focus")["origin"])
    for st in list(walk(script.body)) + list(script.rules):
        if not _api_layer(rep, st) or st.kind == "rule":
            continue
        _profile_layer(rep, st)
        if devices:
            _state_layer(rep, st, focus_z0)
    return {"ok": not rep.errors, "errors": rep.errors, "warnings": rep.warnings,
            "min_duration_s": duration(script.body)}


def duration(body):
    total = 0.0
    for st in body:
        if st.kind == "loop":
            total += st.args["n"].value * duration(st.body)
        elif st.kind in ("zero", "ramp", "hold", "move", "rotate", "wait", "record") and "t" in st.args:
            total += st.args["t"].value
    return total if math.isfinite(total) else float("inf")


def require_ok(report):
    """Raise ScriptError when the report has errors."""
    if not report["ok"]:
        raise ScriptError(report["errors"], report["warnings"])
