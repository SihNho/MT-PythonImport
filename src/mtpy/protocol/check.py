"""Validation of a parsed protocol BEFORE anything runs (docs/format/grammar.md sections 2, 8, 10; WP5).

Three layers, each reported as `Diagnostic`s with the statement's line and the argument's column:

1. **API**: every statement maps to functions of the public layer (`API_MAP`). A function the API does not have yet
   (e.g. `api.light.load_sequence` for `light seq=`, `api.events.rule` for `if` / `wait until` / `on`) makes the
   statement an error: the protocol cannot run until that function exists. Each key's fixed unit must match the unit
   in the API parameter's name (`f` in pN -> `force_pN`).
2. **Rig safety profile** (read only, `api.safety.check`): every value that would reach an acting call, and the
   magnet speed limit every magnet move needs (`api.magnet.move_to` always checks `magnet_speed_mm_s`). A value the
   API would refuse fails here, with the step named. A force (decision 0017: no separate maximum force) is converted
   to a magnet position through the loaded force table and checked against the magnet position limit
   (`api.magnet.force_position`); with no table loaded it cannot be checked here (a warning without `devices`).
3. **Rig state** (`devices=True`, done by `api.protocol.run` right before starting): the devices are connected, a
   position-to-force table is loaded for every force step, the focus target from the current position is inside the
   window, and acquisition runs when the protocol records. Values that depend on what happens during the run are
   still checked by the API at each step.

Nothing here moves anything or logs an acting event.
"""
import inspect
import math

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
    "end_protocol": [("acq.running", {}), ("acq.set_recording", {})],      # decision 0016 item 3
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


def _loaded_table():
    try:
        return api.magnet.force_table()
    except api.NotReady:            # no magnet service (devices not connected)
        return None


def _forces(rep, st, a, devices):
    """Decision 0017: each force through the loaded table to a position inside the magnet position limit."""
    if st.kind not in FORCE_KEYS:
        return
    if _loaded_table() is None:
        if not devices:             # with devices the rig-state layer reports the missing table as an error
            rep.warn(st, st.col, f"'{st.kind}' sets a force, and no position-to-force table is loaded: the force is "
                                 "not checked against the magnet position limit until one is (decision 0017)")
        return
    for k in FORCE_KEYS[st.kind]:
        try:
            api.magnet.force_position(a[k])
        except api.SafetyRefused as e:
            rep.err(st, st.args[k].col, f"'{k}' is {a[k]:g} pN; {e}")


def _profile_layer(rep, st, devices=False):
    a = {k: v.value for k, v in st.args.items()}
    if st.kind in MAGNET_MOVES:
        _magnet_speed(rep, st)
    _forces(rep, st, a, devices)
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
    if st.kind in FORCE_KEYS and api.magnet.force_table() is None:      # the forces: profile layer (0017)
        rep.err(st, st.col, f"'{st.kind}' sets a force, and no position-to-force table is loaded "
                            "(api.magnet.use_force_table, decision 0010)")
        return
    if st.kind == "focus" and focus_z0 is not None:
        z0, origin = focus_z0
        _profile(rep, st, "um", "focus_z_um", z0 + a["um"], origin=origin,
                 why=f" from the focus now at {z0:g} um")
    if st.kind == "record" and not api.acq.running():
        rep.err(st, st.col, "'record' needs acquisition running: api.acq.start() before the protocol")


_NO_RUN = object()


def check(script, devices=False, run_focus_z0=_NO_RUN):
    """Validate a parsed protocol. Returns {"ok", "errors", "warnings" (Diagnostics), "min_duration_s"}.

    devices=True adds the rig-state layer (connected devices, force table, focus position, acquisition running); it
    only reads. run_focus_z0 (a mid-run edit, review l2s-wp5-r1): the focus reference of the RUNNING protocol (the
    position read when it started, the one the engine uses), or None when that run has no reference - then a focus
    statement is refused. Without it the focus position read now is the reference (a new run).
    min_duration_s: the sum of every hold / wait / ramp / record time with the loops expanded (moves not counted)."""
    if script.kind != "protocol":
        raise ScriptError([Diagnostic(script.file, 1, 1, f"a {script.kind} cannot run as a protocol")])
    rep = _Report(script)
    focus_z0 = None
    has_focus = any(s.kind == "focus" for s in walk(script.body))
    if run_focus_z0 is not _NO_RUN and run_focus_z0 is None:
        for st in walk(script.body):
            if st.kind == "focus":
                rep.err(st, st.col, "a focus step cannot be added by a mid-run edit: the running protocol has no "
                                    "focus reference (it had no focus step when it started); stop and start it again")
    elif devices and has_focus and _connected("focus"):
        z0 = api.focus.position() if run_focus_z0 is _NO_RUN else run_focus_z0
        focus_z0 = (z0, api.devices.info("focus")["origin"])
    for st in list(walk(script.body)) + list(script.rules):
        if not _api_layer(rep, st) or st.kind == "rule":
            continue
        _profile_layer(rep, st, devices)
        if devices:
            _state_layer(rep, st, focus_z0)
    return {"ok": not rep.errors, "errors": rep.errors, "warnings": rep.warnings,
            "min_duration_s": duration(script.body)}


def structure_diff(old, new):
    """None when `new` has the same structure as `old` (count, kind, form and nesting of every statement; values may
    differ), else (line in new, reason). Review l2s-wp5-r1: a mid-run edit may change values only - a statement
    inserted, deleted or moved (also an identical repeated line) cannot be told apart reliably by position or text."""
    def name(s):
        return f"{s.kind} {s.form}" if s.form in ("until", "seq", "off", "on") else s.kind

    def cmp(ob, nb, where):
        for a, b in zip(ob, nb):
            if (a.kind, a.form) != (b.kind, b.form):
                return b.line, f"line {b.line} is '{name(b)}' where the running version has '{name(a)}' (line {a.line})"
            if (a.orelse is None) != (b.orelse is None):
                return b.line, f"the 'else' of line {b.line} was added or removed"
            r = cmp(a.body, b.body, f"the block at line {b.line}") or cmp(a.orelse or [], b.orelse or [],
                                                                          f"the 'else' of line {b.line}")
            if r:
                return r
        if len(ob) != len(nb):
            line = nb[min(len(ob), len(nb)) - 1].line if nb else 1
            return line, (f"{where} has {len(nb)} statements where the running version has {len(ob)}: a statement was "
                          "inserted or deleted")
        return None
    r = cmp(old.body, new.body, "the protocol")
    if r is None:
        return None
    return r[0], (f"{r[1]}; a mid-run edit may change values only (same statements, same order, same blocks) - stop "
                  "and start the protocol again for a structural change")


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
