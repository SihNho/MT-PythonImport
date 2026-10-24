"""WP5: the script parser (positions in errors), the protocol checker (API and rig safety profile before anything
runs) and the protocol engine on the simulated rig (event sequence, pause / resume, stop, emergency stop, refusal,
mid-run edits, HDF5 events). No hardware; the G: fixture is not needed."""
import re
import threading
import time
from pathlib import Path

import pytest
from test_acq import _connect
from test_devices import SYNTHETIC_TABLE, _config

from mtpy import api
from mtpy.api import estop, events
from mtpy.api.errors import NotReady, ScriptError
from mtpy.data import HDF5Writer, read_run
from mtpy.protocol import parse

REPO = Path(__file__).resolve().parents[1]
HEAD = 'grammar 0.1\nprotocol "t"\n'


def _rig(tmp_path, monkeypatch, test_limits, profile_version=None):
    _config(tmp_path, monkeypatch, test_limits, profile_version)
    monkeypatch.setattr(api.protocol, "_engine", None)
    with events.as_caller("gui"):
        estop.clear()
        api.devices.connect({"backend": "sim"})
    if test_limits:
        api.magnet.use_force_table(SYNTHETIC_TABLE)
    yield
    if api.protocol.running():
        api.protocol.stop()
        api.protocol.wait(10)
    if api.acq.running():
        api.acq.stop()
    api.devices.disconnect()
    with events.as_caller("gui"):
        estop.clear()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Simulated rig on the TEST profile with the synthetic force table (0.1 pN at 0 mm .. 10 pN at 20 mm)."""
    yield from _rig(tmp_path, monkeypatch, True)


@pytest.fixture
def shipped_rig(tmp_path, monkeypatch):
    """Simulated rig on the shipped profile (v2, decision 0016: magnet speed max 15 mm/s, force max still unset)."""
    yield from _rig(tmp_path, monkeypatch, False)


@pytest.fixture
def v1_rig(tmp_path, monkeypatch):
    """Simulated rig on profile v1 from the history (no magnet speed maximum)."""
    yield from _rig(tmp_path, monkeypatch, False, profile_version=1)


@pytest.fixture
def cam(tmp_path, monkeypatch):
    monkeypatch.setattr(api.protocol, "_engine", None)
    gen = _connect(tmp_path, monkeypatch)
    yield next(gen)
    if api.protocol.running():                      # before the rig is disconnected
        api.protocol.stop()
        api.protocol.wait(10)
    next(gen, None)


def _errors(text, file="p.mtprot"):
    with pytest.raises(ScriptError) as e:
        parse(text, file)
    return [str(d) for d in e.value.diagnostics]


def _steps(since, kind="protocol_step"):
    return [(e.extra["line"], e.extra["phase"], e.extra["loop"]) for e in events.events()[since:] if e.kind == kind]


def _marks(since):
    return [e.extra["text"] for e in events.events()[since:] if e.kind == "mark"]


def _until(cond, timeout_s=5.0):
    t_end = time.monotonic() + timeout_s
    while not cond():
        assert time.monotonic() < t_end, "condition not reached"
        time.sleep(0.01)


# --- parser ------------------------------------------------------------------------------------------------------------
def test_parse_errors_have_line_and_column():
    text = HEAD + ("hold f=7pN t=3\n"            # 3: unit suffix on the value
                   "jump t=3\n"                    # 4: unknown statement
                   "loop n=2\n"
                   "  hold f=1 t=1 f=2\n"          # 6: key twice
                   "end\n"
                   "end\n"                         # 8: end without a block
                   "ramp from=0 to=5 t=0.01\n"     # 9: below the grammar range
                   'mark "open\n'                  # 10: string not closed
                   "hold f=1\n"                    # 11: missing t=
                   "hold f=1 t=2 speed=3\n"        # 12: unknown key
                   "loop n=1.5\n")                 # 13: not a whole number; and never closed
    errs = _errors(text)
    assert errs == [
        ("p.mtprot:3:8: 'f' is written with a unit ('7pN'); units are fixed per key and never written in the value: "
         "write f=7 (pN)"),
        ("p.mtprot:4:1: unknown statement 'jump' (protocol statements: zero ramp hold move rotate focus record light "
         "mark wait loop if else on stop end repeat rule kind; 'end protocol' last)"),
        "p.mtprot:6:16: 'f' is given twice",
        "p.mtprot:8:1: 'end' without an open block",
        "p.mtprot:9:20: 't' is 0.01 (s); the grammar allows 0.1-36000 (s)",
        'p.mtprot:10:6: the quoted string is not closed (missing ")',
        "p.mtprot:11:9: 'hold' needs t=",
        "p.mtprot:12:14: 'hold' has no key 'speed' (keys: f=, t=)",
        "p.mtprot:13:1: 'loop' is not closed: add 'end'",
        "p.mtprot:13:8: 'n' must be a whole number, not 1.5",
    ]


def test_parse_header_errors():
    assert _errors('protocol "x"\nhold f=1 t=1\n')[0].startswith("p.mtprot:1:1: the first line must be 'grammar 0.1'")
    assert _errors('grammar 0.2\nprotocol "x"\nhold f=1 t=1\n')[0].startswith("p.mtprot:1:9: grammar version")
    assert "p.mtprot:2:1: a sequence belongs in a .mtseq file, not 'p.mtprot'" in _errors('grammar 0.1\nsequence "s"\n')
    assert _errors(HEAD + "rule dext >= 0.8\nhold f=1 t=1\n")[0] == \
        "p.mtprot:3:1: 'rule' is allowed only in a protocol of kind screening"
    assert _errors(HEAD + "repeat 2\nhold f=1 t=1\n")[0] == \
        "p.mtprot:4:1: 'repeat n' must be the last statement of the file"
    assert "p.mtprot:3:14: expected a number, a name or a function call" in _errors(HEAD + "if force_pN >\nend\n")


def test_grammar_md_examples_parse():
    text = (REPO / "docs" / "format" / "grammar.md").read_text(encoding="utf-8")
    blocks = [b for b in re.findall(r"```\n(grammar 0\.1.*?)```", text, re.DOTALL) if len(b.splitlines()) > 3]
    kinds = {}
    for b in blocks:
        s = parse(b, "example")
        kinds[s.kind] = s
    assert set(kinds) == {"protocol", "sequence", "recipe"}
    seq = kinds["sequence"]
    assert seq.meta == {"lights": ["532", "637"], "ratio": 3}
    assert [b.kind for b in seq.body] == ["header", "body", "footer"] and seq.body[1].args["repeat"].value == 100
    clamp = parse(blocks[2], "clamp.mtprot")
    assert [s.kind for s in clamp.body] == ["zero", "record", "loop", "record"] and clamp.body[2].args["n"].value == 10


def test_repeat_wraps_the_list_and_comments_are_ignored():
    s = parse(HEAD + "hold f=1 t=1   # a comment with = and \"quotes\"\nmark \"a # not a comment\"\nrepeat 3\n")
    assert [x.kind for x in s.body] == ["loop"] and s.body[0].args["n"].value == 3
    assert s.body[0].body[1].pos[0].value == "a # not a comment"


def test_sequence_and_recipe_checks():
    errs = _errors('grammar 0.1\nsequence "s"\nlights 532 637\nratio n=0\nbody\n  frame 532=on\nend\n', "s.mtseq")
    assert "s.mtseq:4:9: 'n' is 0; the grammar allows 1-65536" in errs
    assert "s.mtseq:6:15: 'frame' needs 637=" in errs
    errs = _errors('grammar 0.1\nrecipe "r"\nsignals dd\nobservable E = fret(dd, xx)\nselect wobble(E)\n', "r.mtrec")
    assert errs == ["r.mtrec:4:25: unknown name 'xx': not a signal, an observable or a live quantity defined above",
                    ("r.mtrec:5:8: unknown function 'wobble' (library: fret, present, fell, rose, mean, sd, rel, "
                     "at_start, fraction)")]


def test_load_never_executes(rig):
    n = len(events.events())
    p0 = api.magnet.position()
    s = api.protocol.load(HEAD + "hold f=5 t=1\nmove mm=3\n", file="x.mtprot")
    assert s.kind == "protocol" and len(s.body) == 2
    api.protocol.check(s)
    assert events.events()[n:] == [] and abs(api.magnet.position() - p0) < 0.01
    assert api.protocol.status() == {"state": "idle"}


# --- checker -----------------------------------------------------------------------------------------------------------
def test_check_refuses_statements_the_api_cannot_run(rig):
    s = parse(HEAD + 'light seq="green"\nif force_pN > 3\n  mark "x"\nend\nwait until t_s > 3 timeout=5\n'
                     "hold f=1 t=1\n", "c.mtprot")
    rep = api.protocol.check(s)
    errs = [str(d) for d in rep["errors"]]
    assert not rep["ok"] and len(errs) == 3
    assert errs[0].startswith(f"c.mtprot:3:1: 'light seq' needs api.light.load_sequence, which api {api.VERSION} does not "
                              "have yet")
    assert errs[1].startswith("c.mtprot:4:1: 'if' needs api.events.rule")
    assert errs[2].startswith("c.mtprot:7:1: 'wait until' needs api.events.rule")


def test_check_out_of_profile_value_names_step_and_range(rig):
    rep = api.protocol.check(parse(HEAD + "hold f=1 t=1\nloop n=2\n  ramp from=1 to=25 t=5\nend\nmove mm=40\n",
                                   "fe.mtprot"))
    errs = [str(d) for d in rep["errors"]]
    assert "fe.mtprot:5:18: 'to' is 25 pN; magnet_force_pN 25 pN is outside the allowed range [0, 20] pN of the " \
           "rig safety profile v2" in errs                       # the TEST profile is built on the shipped v2
    assert any(e.startswith("fe.mtprot:7:9: 'mm' is 40 mm; magnet_position_mm 40 mm is outside the allowed range "
                            "[0, 39] mm") for e in errs)
    assert any(e.startswith("fe.mtprot:5:18: 'to' is 25 pN; the force table") for e in errs)   # rig state layer


def test_shipped_profile_v2_runs_magnet_moves_but_not_forces(shipped_rig):
    """Decision 0016: with v2 a position move passes the check and runs; a force step still fails the check because
    magnet_force_pN has no maximum yet (and no force table is loaded)."""
    rep = api.protocol.check(parse(HEAD + "hold f=1 t=1\n", "v2.mtprot"), devices=False)
    errs = [str(d) for d in rep["errors"]]
    assert not any("magnet_speed_mm_s" in e for e in errs) and any("magnet_force_pN has no limit set" in e
                                                                    for e in errs)
    api.protocol.run(parse(HEAD + "move mm=2\nzero t=0.1\n"))
    assert api.protocol.wait(10)["state"] == "completed"
    assert api.magnet.position() == pytest.approx(0.0, abs=0.01)


def test_magnet_move_refused_by_profile_v1_before_anything_runs(v1_rig):
    s = parse(HEAD + "hold f=1 t=1\n", "v1.mtprot")
    rep = api.protocol.check(s, devices=False)
    errs = [str(d) for d in rep["errors"]]
    assert any(e.startswith("v1.mtprot:3:1: 'hold' moves the magnet, and api.magnet.move_to checks the magnet speed")
               and "magnet_speed_mm_s has no limit set" in e for e in errs)
    n, p0 = len(events.events()), api.magnet.position()
    with pytest.raises(ScriptError, match="magnet_speed_mm_s"):
        api.protocol.run(s)
    assert [e.kind for e in events.events()[n:]] == ["refused"]
    assert api.protocol.status()["state"] in ("idle", "completed", "stopped", "refused", "failed", "aborted")
    assert not api.protocol.running() and abs(api.magnet.position() - p0) < 0.01


# --- engine ------------------------------------------------------------------------------------------------------------
def test_full_run_event_sequence(rig):
    text = HEAD + ("kind experiment\n"
                   "hold f=1 t=0.1\n"           # 4
                   "loop n=2\n"
                   "  ramp from=1 to=2 t=0.2\n"  # 6
                   '  mark "pass"\n'             # 7
                   "end\n"
                   "move mm=5\n"                 # 9
                   "wait t=0.05\n")              # 10
    s = parse(text, "seq.mtprot")
    n = len(events.events())
    api.protocol.run(s, ramp_step_s=0.1)
    st = api.protocol.wait(30)
    assert st["state"] == "completed" and st["reason"] is None and st["steps_done"] == 7, st
    assert _steps(n) == [(4, "start", -1), (4, "end", -1), (6, "start", 1), (6, "end", 1), (7, "start", 1),
                         (7, "end", 1), (6, "start", 2), (6, "end", 2), (7, "start", 2), (7, "end", 2),
                         (9, "start", -1), (9, "end", -1), (10, "start", -1), (10, "end", -1)]
    run = [e for e in events.events()[n:] if e.kind == "protocol"]
    assert [e.extra["action"] for e in run] == ["start", "end"] and run[0].extra["sha256"] == s.sha256
    caller = s.caller
    assert caller.startswith("script:t@") and all(e.caller == caller for e in events.events()[n:]
                                                   if e.kind in ("protocol_step", "act", "force_request", "mark"))
    ramp_end = [e for e in events.events()[n:] if e.kind == "protocol_step" and e.extra["line"] == 6][1]
    assert ramp_end.extra["increments"] == 2
    acts = [e for e in events.events()[n:] if e.kind == "act" and e.request["quantity"] == "magnet_position_mm"]
    assert len(acts) == 1 + 2 * 3 + 1                          # hold, 2 x ramp (start + 2 increments), move
    assert abs(api.magnet.position() - 5.0) <= 0.01 and _marks(n) == ["pass", "pass"]


def test_rotate_and_focus_go_through_the_api(rig):
    z0 = api.focus.position()
    n = len(events.events())
    api.protocol.run(parse(HEAD + "rotate from=-1 to=1 f=1 t=0.4\nfocus um=5\n"))
    st = api.protocol.wait(30)
    assert st["state"] == "completed", st
    origin = api.devices.info("rotor")["origin"]
    assert api.rotor.position() - origin == pytest.approx(1.0, abs=0.003)
    assert api.focus.position() == pytest.approx(z0 + 5.0, abs=0.2)
    q = [e.request["quantity"] for e in events.events()[n:] if e.kind == "act"]
    assert q == ["magnet_position_mm", "rotor_turns", "rotor_turns", "focus_z_um"]


def test_pause_and_resume(rig):
    n = len(events.events())
    api.protocol.run(parse(HEAD + 'wait t=0.4\nmark "after"\n'))
    t0 = time.monotonic()
    time.sleep(0.1)
    api.protocol.pause()
    _until(lambda: api.protocol.status()["state"] == "paused")
    time.sleep(0.6)
    assert api.protocol.status()["state"] == "paused" and _marks(n) == []
    api.protocol.resume()
    st = api.protocol.wait(5)
    assert st["state"] == "completed" and _marks(n) == ["after"]
    assert time.monotonic() - t0 >= 0.95                         # 0.4 s of protocol time + 0.6 s paused
    acts = [e.extra["action"] for e in events.events()[n:] if e.kind == "protocol"]
    assert acts == ["start", "pause", "resume", "end"]


def test_stop_ends_run_and_nothing_else_starts(rig):
    n = len(events.events())
    api.protocol.run(parse(HEAD + 'hold f=1 t=30\nmark "never"\n'))
    _until(lambda: (api.protocol.status()["current"] or {}).get("line") == 3)
    time.sleep(0.2)
    api.protocol.stop()
    st = api.protocol.wait(5)
    assert st["state"] == "stopped" and "operator" in st["reason"]
    assert _steps(n)[-1] == (3, "stopped", -1) and _marks(n) == []
    with pytest.raises(NotReady):
        api.protocol.resume()


def test_estop_mid_step_aborts_and_motors_stay_stopped(rig):
    n = len(events.events())
    api.protocol.run(parse(HEAD + 'hold f=10 t=1\nmark "never"\n'))     # 0 -> 20 mm at 10 mm/s: 2 s of motion
    _until(lambda: 1.0 < api.magnet.position() < 15.0)
    estop.engage("test: mid-step")
    st = api.protocol.wait(5)
    assert st["state"] == "aborted" and "emergency stop" in st["reason"]
    assert _steps(n)[-1] == (3, "aborted", -1) and _marks(n) == []
    p1 = api.magnet.position()
    time.sleep(0.3)
    assert abs(api.magnet.position() - p1) < 0.005 and p1 < 19.0          # stopped in place, not at the target
    with pytest.raises(NotReady, match="cannot resume"):
        api.protocol.resume()
    with events.as_caller("gui"):
        estop.clear()
    time.sleep(0.4)
    assert abs(api.magnet.position() - p1) < 0.005                         # nothing resumes after the release
    assert api.protocol.status()["state"] == "aborted"
    assert not any(e.kind == "act" for e in events.events()[n:])


def test_run_refused_while_estop_engaged(rig):
    estop.engage("test")
    with pytest.raises(NotReady, match="emergency stop"):
        api.protocol.run(parse(HEAD + "wait t=0.1\n"))


def test_api_refusal_mid_run_stops_the_run(rig):
    n = len(events.events())
    api.protocol.run(parse(HEAD + 'hold f=1 t=0.5\nhold f=8 t=0.1\nmark "never"\n'))
    _until(lambda: (api.protocol.status()["current"] or {}).get("line") == 3)
    narrow = {**SYNTHETIC_TABLE, "name": "narrow table", "force_pN": [0.1, 1.0, 5.0]}
    api.magnet.use_force_table(narrow)                 # the operator loads another table during the run
    st = api.protocol.wait(10)
    assert st["state"] == "refused", st
    assert "line 4 'hold f=8 t=0.1' was refused by the API" in st["reason"] and "outside the table" in st["reason"]
    refused = [e for e in events.events()[n:] if e.kind == "protocol_step" and e.extra["phase"] == "refused"]
    assert len(refused) == 1 and refused[0].extra["line"] == 4 and refused[0].extra["error"] == "SafetyRefused"
    assert _marks(n) == [] and (5, "start", -1) not in _steps(n)


def test_mid_run_edit_applies_at_next_step_boundary(rig):
    """Loop value edits (n, a force, a text) still apply at the next boundary (regression for review l2s-wp5-r1)."""
    n = len(events.events())
    api.protocol.run(parse(HEAD + 'loop n=3\n  hold f=1 t=0.3\n  mark "a"\nend\n'))
    time.sleep(0.1)                                    # inside the first hold
    with pytest.raises(ScriptError, match="25 pN"):
        api.protocol.edit(HEAD + 'loop n=3\n  hold f=25 t=0.3\n  mark "a"\nend\n')
    api.protocol.edit(HEAD + 'loop n=2\n  hold f=2 t=0.3\n  mark "b"\nend\n')
    api.protocol.apply_edits()
    st = api.protocol.wait(10)
    assert st["state"] == "completed" and st["protocol_version"] == 1
    assert _marks(n) == ["b", "b"]                     # the not-started mark takes it at once; 2 passes in all
    ed = [e for e in events.events()[n:] if e.kind == "protocol_edit"]
    assert [e.extra["action"] for e in ed] == ["refused", "applied"] and 'mark "b"' in ed[1].extra["new_text"]


def _edit_refused(draft, match):
    n = len(events.events())
    with pytest.raises(ScriptError, match=match):
        api.protocol.edit(draft)
    ev = [e for e in events.events()[n:] if e.kind == "protocol_edit"]
    assert [e.extra["action"] for e in ev] == ["refused"], ev


def test_mid_run_structural_edits_are_refused_with_an_event(rig):
    """Review l2s-wp5-r1 fix 4: only in-place value edits; deleting / inserting an earlier statement of the same kind
    (identical repeated text), removing or adding the enclosing loop and adding a step after the running position are
    each refused with a `protocol_edit` event - never applied, never silently ignored - and the run goes on."""
    n = len(events.events())
    three = 'wait t=0.4\nwait t=0.4\nwait t=0.4\nmark "end"\n'
    api.protocol.run(parse(HEAD + three))
    _until(lambda: (api.protocol.status()["current"] or {}).get("line") == 4)       # the second wait runs
    _edit_refused(HEAD + 'wait t=0.4\nwait t=0.4\nmark "end"\n', "where the running version has 'wait'")  # deleted
    _edit_refused(HEAD + "wait t=0.4\n" + three, "where the running version has 'mark'")                 # inserted
    _edit_refused(HEAD + three + 'mark "added after"\n', "inserted or deleted")                         # added after
    _edit_refused(HEAD + 'loop n=1\n  wait t=0.4\n  wait t=0.4\n  wait t=0.4\n  mark "end"\nend\n', "'loop'")
    st = api.protocol.wait(10)
    assert st["state"] == "completed" and st["protocol_version"] == 0 and st["edits"] == []
    assert [x for x in _steps(n) if x[1] == "end"] == [(3, "end", -1), (4, "end", -1), (5, "end", -1),
                                                       (6, "end", -1)]
    assert _marks(n) == ["end"]


def test_engine_refuses_a_structural_draft_at_the_boundary(rig):
    """A draft that reaches the engine without api.protocol.edit is still refused (with an event) at the boundary."""
    n = len(events.events())
    api.protocol.run(parse(HEAD + 'wait t=0.3\nmark "a"\n'))
    api.protocol._engine.offer_edit(parse(HEAD + 'wait t=0.3\nmark "a"\nmark "b"\n'))
    st = api.protocol.wait(10)
    assert st["state"] == "completed" and st["edits"][0]["result"] == "refused" and _marks(n) == ["a"]
    ev = [e for e in events.events()[n:] if e.kind == "protocol_edit"]
    assert ev[0].extra["action"] == "refused" and "structural change refused" in ev[0].extra["reason"]


def test_mid_run_edit_focus_uses_the_run_start_reference(rig):
    """Review l2s-wp5-r1 fix 3: an edit's focus check uses the focus position read when the run started (the
    engine's reference), not the position now. The first step moved the focus +45 um; a later step edited to +48 um
    from the start is inside the +-50 um window (from the position now it would be +93 and refused)."""
    z0 = api.focus.position()
    api.protocol.run(parse(HEAD + "focus um=45\nwait t=0.6\nfocus um=40\n"))
    _until(lambda: (api.protocol.status()["current"] or {}).get("line") == 4)
    api.protocol.edit(HEAD + "focus um=45\nwait t=0.6\nfocus um=48\n")
    api.protocol.apply_edits()
    st = api.protocol.wait(10)
    assert st["state"] == "completed" and st["protocol_version"] == 1
    assert api.focus.position() == pytest.approx(z0 + 48.0, abs=0.2)


def test_focus_step_without_run_reference_is_refused(rig):
    """Review l2s-wp5-r1 fix 3: a run that started without a focus step has no focus reference; a focus step offered
    by an edit is refused - by the checker (run_focus_z0=None) and, through api.protocol.edit, with an event."""
    from mtpy.protocol.check import check
    rep = check(parse(HEAD + "wait t=0.5\nfocus um=5\n", "f.mtprot"), devices=True, run_focus_z0=None)
    assert [str(d) for d in rep["errors"]] == [
        ("f.mtprot:4:1: a focus step cannot be added by a mid-run edit: the running protocol has no focus reference "
         "(it had no focus step when it started); stop and start it again")]
    api.protocol.run(parse(HEAD + "wait t=0.5\nwait t=0.3\n"))
    assert api.protocol._engine.focus_z0 is None
    _edit_refused(HEAD + "wait t=0.5\nfocus um=5\n", "where the running version has 'wait'")
    assert api.protocol.wait(10)["state"] == "completed"


# --- review l2s-wp5-r1 fixes 1 and 2: e-stop barriers, one run at a time ------------------------------------------------
def _count_sends(monkeypatch, name):
    dev = api.devices.service(name).device
    sent, real = [], dev.move_to
    monkeypatch.setattr(dev, "move_to", lambda *a, **k: (sent.append(a), real(*a, **k))[1])
    return sent


def _engage_and_release(reason):
    estop.engage(reason)
    with events.as_caller("gui"):
        estop.clear()


def test_estop_engaged_and_released_during_step_start_event_sends_nothing(rig, monkeypatch):
    """Fix 1: an emergency stop engaged and released while the step-start event is delivered (a subscriber) voids
    every later request of the run: zero magnet sends, run aborted."""
    sent = _count_sends(monkeypatch, "magnet")
    fired = []

    def on_event(ev):
        if ev.kind == "protocol_step" and ev.extra.get("phase") == "start" and not fired:
            fired.append(ev)
            _engage_and_release("test: during the step-start event")
    unsubscribe = events.subscribe(on_event)
    try:
        api.protocol.run(parse(HEAD + "hold f=1 t=0.2\n"))
        st = api.protocol.wait(10)
    finally:
        unsubscribe()
    assert fired and not estop.active()
    assert st["state"] == "aborted" and sent == []


def test_estop_engaged_and_released_during_rotor_pre_read_sends_nothing(rig, monkeypatch):
    """Fix 1: an emergency stop engaged and released while the rotor is read before a rotate: zero rotor sends, run
    aborted (the magnet force step before it ran)."""
    sent = _count_sends(monkeypatch, "rotor")
    dev = api.devices.service("rotor").device
    armed, fired, real = [], [], dev.position

    def position():
        if armed and not fired:
            fired.append(1)
            _engage_and_release("test: during the rotor pre-read")
        return real()
    monkeypatch.setattr(dev, "position", position)

    def arm(ev):
        if ev.kind == "act" and isinstance(ev.request, dict) and ev.request.get("quantity") == "magnet_position_mm":
            armed.append(1)
    unsubscribe = events.subscribe(arm)
    try:
        api.protocol.run(parse(HEAD + "rotate from=-1 to=1 f=1 t=0.4\n"))
        st = api.protocol.wait(10)
    finally:
        unsubscribe()
    assert armed and fired and not estop.active()
    assert st["state"] == "aborted" and sent == []


class _SpyLock:
    """Stands in for api.protocol._run_lock around `inner` (anything with acquire(blocking, timeout) / release: the
    real lock, or in the negative control a lock without mutual exclusion). Review l2s-wp5-r3: `waiting` is set only
    AFTER a non-blocking acquire was REFUSED - proof that another thread holds the lock, not mere arrival; the wait
    that follows is bounded (acquire(timeout=5)) and a failure raises here, so the block never runs without the lock
    and __exit__ never releases a lock it does not hold."""

    def __init__(self, inner):
        self.inner = inner
        self.waiting = {"run-A": threading.Event(), "run-B": threading.Event()}
        self.holding = {"run-A": threading.Event(), "run-B": threading.Event()}

    def __enter__(self):
        me = threading.current_thread().name
        if not self.inner.acquire(blocking=False):
            self.waiting[me].set()
            if not self.inner.acquire(timeout=5):
                raise RuntimeError(f"{me}: run lock not acquired within 5 s")
        self.holding[me].set()
        return self

    def __exit__(self, *exc):
        self.holding[threading.current_thread().name].clear()
        self.inner.release()
        return False


class _NoExclusion:
    """The negative control's inner lock: acquire always succeeds at once (mutual exclusion removed)."""

    def acquire(self, blocking=True, timeout=-1):
        return True

    def release(self):
        pass


def overlapping_runs(monkeypatch, inner):
    """Run A enters its check while holding the run lock and is held there by a signal; run B is started and must
    signal `waiting` (its non-blocking acquire refused); then A is released. Signals only, every wait bounded; A is
    released and both threads joined on every path, also when an assertion fails. Returns what happened."""
    import mtpy.protocol.check as chk
    real = chk.check
    a_in_check, release_a = threading.Event(), threading.Event()

    def held_check(*a, **k):
        if threading.current_thread().name == "run-A":
            a_in_check.set()
            assert release_a.wait(5), "run A was never released"
        return real(*a, **k)
    monkeypatch.setattr(chk, "check", held_check)
    spy = _SpyLock(inner)
    monkeypatch.setattr(api.protocol, "_run_lock", spy)
    n = len(events.events())
    results = {}

    def go(name):
        try:
            api.protocol.run(parse(f'grammar 0.1\nprotocol "{name}"\nwait t=1\n'))
            results[name] = "started"
        except NotReady as e:
            results[name] = f"refused: {e}"
    a = threading.Thread(target=go, args=("A",), name="run-A", daemon=True)
    b = threading.Thread(target=go, args=("B",), name="run-B", daemon=True)
    try:
        a.start()
        assert a_in_check.wait(5) and spy.holding["run-A"].is_set(), "A is not inside its check holding the lock"
        b.start()
        assert spy.waiting["run-B"].wait(5), "no waiting signal: B's non-blocking acquire was not refused"
        assert not spy.holding["run-B"].is_set()
    finally:
        release_a.set()
        a.join(5)
        b.join(5)
    assert not a.is_alive() and not b.is_alive()
    new = events.events()[n:]
    return {"results": results, "running_name": api.protocol.status()["name"],
            "started": [e.extra["name"] for e in new if e.kind == "protocol" and e.extra["action"] == "start"],
            "refused": [e.request["protocol"] for e in new if e.kind == "refused"]}


def test_only_one_run_starts_and_the_running_one_is_never_overwritten(rig, monkeypatch):
    """Fix 2 (re-reviews l2s-wp5-r2 / r3: signals, no sleep): A holds the run lock inside its check, B's
    non-blocking acquire is refused (waiting signal), A is released: exactly one run starts (A), B is refused with
    NotReady and a `refused` event, and the running engine is still A. Assumes A's engine (wait t=1) is still
    running when B gets the lock (WP6 carry)."""
    got = overlapping_runs(monkeypatch, threading.Lock())
    assert got["started"] == ["A"], got
    assert got["results"]["A"] == "started" and got["results"]["B"].startswith("refused: a protocol is already "
                                                                                "running"), got
    assert got["refused"] == ["B"] and got["running_name"] == "A", got
    api.protocol.stop()
    assert api.protocol.wait(5)["state"] == "stopped"


def test_engine_calls_only_the_public_api():
    """The engine and the checker never import the device layer or reach a device service."""
    for name in ("engine.py", "check.py", "grammar.py"):
        src = (REPO / "src" / "mtpy" / "protocol" / name).read_text(encoding="utf-8")
        assert "mtpy.devices" not in src and "service(" not in src and "_services" not in src, name


# --- end to end with the HDF5 file ---------------------------------------------------------------------------------------
def test_end_to_end_recording_has_protocol_events(cam, tmp_path):
    api.magnet.use_force_table(SYNTHETIC_TABLE)
    api.acq.start(record=True, name="prot", folder=tmp_path)
    s = parse(HEAD + 'hold f=1 t=0.2\nmark "in protocol"\nrecord off\n', "e2e.mtprot")
    api.protocol.run(s)
    assert api.protocol.wait(30)["state"] == "completed"
    st = api.acq.stop()
    assert st["stop"] == "complete" and st["sink_failures"] == 0, st["sink_error"]
    run = read_run(tmp_path / "prot.h5")
    ev = run["events"]
    steps = ev["protocol_step"]
    phases = list(zip([d["line"] for d in steps["data"]], [d["phase"] for d in steps["data"]]))
    assert phases == [(3, "start"), (3, "end"), (4, "start"), (4, "end"), (5, "start")]   # recording off at line 5
    assert set(steps["caller"].tolist()) == {s.caller}
    assert [d["action"] for d in ev["protocol"]["data"]] == ["start"]
    assert ev["protocol"]["data"][0]["sha256"] == s.sha256 and ev["protocol"]["data"][0]["text"] == s.text
    assert "in protocol" in [d["text"] for d in ev["mark"]["data"]]
    assert run["attrs"]["closed_cleanly"] == 1


# --- decision 0016 item 3: `end protocol` -------------------------------------------------------------------------------
def test_end_protocol_parse_rules():
    s = parse(HEAD + "hold f=1 t=1\nrepeat 2\nend protocol\n")
    assert [x.kind for x in s.body] == ["loop", "end_protocol"] and s.body[1].line == 5
    assert "p.mtprot:4:3: 'end protocol' belongs at the top level, as the last statement (close the open blocks " \
           "with 'end' first)" in _errors(HEAD + "loop n=2\n  end protocol\nend\n")
    assert "p.mtprot:4:1: nothing may follow 'end protocol' (line 3); it is the last statement" in \
        _errors(HEAD + "end protocol\nhold f=1 t=1\n")
    s = parse('grammar 0.1\nprotocol "s"\nkind screening\nhold f=1 t=1\nend protocol\nrule angle_deg <= 20\n')
    assert s.body[-1].kind == "end_protocol" and len(s.rules) == 1          # rules may follow (not actions)


def test_end_protocol_switches_recording_off_and_closes_the_interval(cam, tmp_path):
    """With `end protocol`: recording off through the API, acquisition keeps running, the HDF5 recording interval is
    closed at the off event, and the end is an event."""
    api.magnet.use_force_table(SYNTHETIC_TABLE)
    api.acq.start(record=True, name="ended", folder=tmp_path)
    api.acq.wait_frames(5, 5)
    n = len(events.events())
    api.protocol.run(parse(HEAD + 'hold f=1 t=0.2\nend protocol\n', "end.mtprot"))
    st = api.protocol.wait(30)
    assert st["state"] == "completed" and "recording switched off" in st["reason"]
    acq = api.acq.status()
    assert acq["running"] and not acq["recording"]
    received = acq["frames_received"]
    api.acq.wait_frames(10, 5)                                              # acquisition goes on
    assert api.acq.status()["frames_received"] > received
    ends = [e for e in events.events()[n:] if e.kind == "protocol" and e.extra["action"] == "end_statement"]
    assert len(ends) == 1 and ends[0].extra["recording_switched_off"] is True and ends[0].extra["line"] == 4
    assert _steps(n)[-1] == (4, "completed", -1)
    off = [e for e in events.events()[n:] if e.kind == "recording" and e.extra["action"] == "off"]
    assert len(off) == 1 and off[0].caller == parse(HEAD + 'hold f=1 t=0.2\nend protocol\n', "end.mtprot").caller
    api.acq.stop()
    run = read_run(tmp_path / "ended.h5")
    rec = run["recordings"]
    assert rec["name"].tolist() == ["ended"] and int(rec["off_buffer"][0]) == off[0].extra["buffer_number"]
    assert int(run["mt"]["buffer_number"].max()) == off[0].extra["buffer_number"]   # nothing after the off recorded
    assert run["attrs"]["frames_not_written"] == 0 and run["attrs"]["frames_outside_recordings"] == 0
    assert [d["action"] for d in run["events"]["protocol"]["data"]] == ["start", "end_statement"]


def test_without_end_protocol_recording_keeps_going(cam, tmp_path):
    """No `end protocol`: the run completes and recording simply continues; a user stop does not switch it off
    either (0007, 0016)."""
    api.magnet.use_force_table(SYNTHETIC_TABLE)
    api.acq.start(record=True, name="open", folder=tmp_path)
    api.protocol.run(parse(HEAD + 'hold f=1 t=0.2\n'))
    assert api.protocol.wait(30)["state"] == "completed"
    assert api.acq.status()["recording"]
    api.protocol.run(parse(HEAD + 'wait t=30\nend protocol\n'))
    _until(lambda: (api.protocol.status()["current"] or {}).get("line") == 3)
    api.protocol.stop()
    assert api.protocol.wait(5)["state"] == "stopped" and api.acq.status()["recording"]
    api.acq.stop()

# --- WP5 carry: the HDF5 writer's max_pending overflow is visible in api.acq.status() --------------------------------------
class _NoRecordingOn:
    """A sink in front of HDF5Writer that never passes the recording events, so no recording-on is accepted and every
    recorded frame waits (bounded by max_pending)."""

    def __init__(self, writer):
        self.w = writer

    @property
    def unwritten_frames(self):
        return self.w.unwritten_frames

    def write_frame(self, result):
        self.w.write_frame(result)

    def write_event(self, ev):
        if ev.kind != "recording":
            self.w.write_event(ev)

    def close(self):
        self.w.close()


def test_max_pending_overflow_visible_in_status(cam, tmp_path):
    sink = _NoRecordingOn(HDF5Writer(tmp_path / "over.h5", max_pending=5))
    api.acq.start(record=True, name="over", sink=sink)
    api.acq.wait_frames(30, 5)
    _until(lambda: (api.acq.status()["frames_not_written"] or 0) >= 10)
    st = api.acq.status()
    assert st["running"] and st["recording"]
    assert st["sink_failures"] >= st["frames_not_written"] >= 10
    assert "5 recorded frames wait for an accepted recording-on interval" in st["sink_error"]
    received = st["frames_received"]
    api.acq.wait_frames(10, 5)                                   # the pipeline carries on per frame
    assert api.acq.status()["frames_received"] > received
    st = api.acq.stop()
    assert st["frames_not_written"] >= 10 and st["sink_error"].startswith("close: RecordingRefused")
    assert not (tmp_path / "over.h5").exists()                   # no accepted recording-on -> no file


def test_status_frames_not_written_none_for_a_plain_sink(cam):
    api.acq.start(record=True, name="mem")
    api.acq.wait_frames(5, 5)
    assert api.acq.status()["frames_not_written"] is None
    api.acq.stop()
