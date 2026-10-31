"""Walking skeleton, end to end on the simulators (plan phase 5, WP6). Hardware: NONE (backend "sim" only).

    .venv\\Scripts\\python.exe tools\\walking_skeleton.py --out D:\\tmp\\skeleton            # normal run
    .venv\\Scripts\\python.exe tools\\walking_skeleton.py --out D:\\tmp\\skeleton --estop    # e-stop mid-protocol

One run, through the public API only (`mtpy.api`), as a script would do it:
1. A copy of the shipped `config/` in `<out>/config` becomes the active profile folder (the shipped files are never
   written; their sha256 is compared before and after). The run uses that copy unchanged: the shipped profile (v5:
   magnet position [0, 39] mm and speed 15 mm/s rig-checked, no separate force limit - decision 0017).
2. Decision 0018 on the shipped profile: the default force calibration is the live LabVIEW equation (M270 v3, with a
   TEST-ONLY touch position); with a TEST-ONLY table that reaches past 39 mm, a protocol whose force needs a position
   beyond the limit is COERCED (checked plan rewritten, `coerced` event) and runs to the 39 mm limit; with the run's
   table the protocol passes the check. (Until v5 the skeleton made a TEST-ONLY profile with a force maximum in the
   copy; v5 needs none. Until 0018 the out-of-reach force was refused.)
3. Simulated devices (the camera replays the recorded G: fixture frames when they exist, else synthetic rings); a
   camera preset (90 Hz) applied and read back; beads 1-5 of the fixture's `cal002` selected, bead 1 = reference;
   a TEST-ONLY synthetic position-to-force table.
4. Acquisition and recording to `<out>/<name>.h5`; the protocol file `<out>/<name>.mtprot` runs (magnet moves,
   ramps, a mark, `zero`, `end protocol`); `end protocol` leaves recording on (decision 0016 item 3, owner change),
   so the skeleton switches recording off itself; acquisition stops; devices disconnect.
5. The file is read back and exported (`.tra`, `.cal`) and checked: frames, segment, rate (U15), events incl. the
   protocol steps, magnet position per frame, `.tra` frame column from the first recorded frame, `.cal` bytes.
   `--estop`: the emergency stop is engaged during a magnet move; the run must end `aborted`, the magnet stay
   stopped (also after the release), acquisition and recording go on, and the file be consistent.

Prints one `RESULT {...}` line (ok, checks failed, paths). Exit code 0 when every check passed.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mtpy import api
from mtpy.api import estop, events, safety
from mtpy.data import export_cal, export_tra, legacy_matrix, read_run
from mtpy.lvfiles import read_tra
from mtpy.protocol import parse

FIXTURE = Path(os.environ.get("MTPY_DATA", r"G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch"))
FIXTURE = FIXTURE / "test"
# TEST ONLY - a clearly synthetic position-to-force table (no physics; decision 0010 needs a recorded one)
TABLE = {"name": "TEST ONLY synthetic table (walking skeleton)", "version": "test", "position_mm": [0.0, 10.0, 20.0],
         "force_pN": [0.1, 1.0, 10.0]}
# TEST ONLY - a synthetic table reaching past the 39 mm magnet position limit (23.04 pN at 39 mm; decision 0017)
WIDE_TABLE = {"name": "TEST ONLY wide synthetic table (walking skeleton)", "version": "test",
              "position_mm": [0.0, 20.0, 45.0], "force_pN": [0.1, 1.0, 30.0]}
OUT_OF_REACH = 'grammar 0.1\nprotocol "out-of-reach"\nhold f=31 t=0.1\n'      # beyond WIDE_TABLE itself at any position limit
TOUCH_MM = 40.0     # TEST ONLY - a touch position for the force equation (the rig's value is set per session)
PRESET = {"name": "skeleton 90 Hz", "roi": (0, 0, 1280, 1024), "rate_Hz": 90.0, "exposure_ms": 2.0, "gain_dB": 0.0}
BEADS = [1, 2, 3, 4, 5]
ROLES = {1: "reference", 2: "tethered", 3: "tethered", 4: "tethered", 5: "tethered"}
PROTOCOL = """grammar 0.1
protocol "skeleton"
# walking skeleton (WP6): simulators only, shipped profile, TEST-ONLY force table
hold f=1 t=0.3
move mm=3 t=0.2
mark "midway"
loop n=2
  ramp from=1 to=2 t=0.4
end
zero t=0.2
end protocol
"""
PROTOCOL_ESTOP = """grammar 0.1
protocol "skeleton-estop"
# walking skeleton (WP6), e-stop variant: the stop is engaged during the second hold's magnet move
hold f=1 t=0.3
hold f=8 t=5
mark "never"
end protocol
"""
STEP_LINES = [4, 5, 6, 8, 8, 10, 11]          # statements of PROTOCOL that run (the ramp twice), `end protocol` last


def _sha(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*.json"))}


class Report:
    def __init__(self):
        self.checks, self.facts = [], {}

    def check(self, name, ok, detail=""):
        self.checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})
        return bool(ok)

    @property
    def ok(self):
        return all(c["ok"] for c in self.checks)

    @property
    def failed(self):
        return [c for c in self.checks if not c["ok"]]


def _shipped_profile_passes(r, script):
    """The shipped profile (unchanged copy, v5) has no force limit; with the run's table the protocol passes the
    full check (rig state included)."""
    shipped = json.loads((REPO / "config" / "safety_profile.json").read_text(encoding="utf-8"))["version"]
    p = safety.profile()
    rep = api.protocol.check(script, devices=True)
    r.check("shipped profile (no force limit, 0017) in the temporary copy; the protocol passes the check",
            p["version"] == shipped and "magnet_force_pN" not in p["limits"] and rep["ok"]
            and Path(safety.CONFIG).resolve() != (REPO / "config").resolve(),
            f"v{p['version']} in {safety.CONFIG}: {[str(d) for d in rep['errors']]}")


def _equation_is_the_default(r):
    """Decision 0018 item 1: right after connecting, the calibration in use is the live LabVIEW equation; it needs
    the touch position (TEST-ONLY value here) and then gives the equation's force at a position."""
    cal = api.magnet.force_calibration()
    api.magnet.set_touch_position(TOUCH_MM)
    got = api.magnet.force_at(38.0)
    want = 48.8162 * np.exp(-2 / 1.13483) + 22.8394 * np.exp(-2 / 3.68428) - 0.45845
    r.check("default force calibration is the live equation M270 v3 case 1 (0018)",
            cal["name"].startswith("M270 v3") and cal["kind"] == "equation" and not cal["ready"]
            and abs(got - want) < 1e-12, f"{cal['name']}: F(38 mm, touch {TOUCH_MM}) = {got!r}")


def _out_of_reach_coerced(r):
    """Decision 0018 with the shipped profile: a force the TEST-ONLY wide table reaches only beyond the 39 mm magnet
    position limit is coerced to the force at 39 mm (checked plan rewritten, `coerced` event, no refusal) and runs
    to the limit; the run's table is loaded again afterwards."""
    n = len(events.events())
    api.magnet.use_force_table(WIDE_TABLE)
    try:
        rep = api.protocol.check(parse(OUT_OF_REACH, "out_of_reach.mtprot"), devices=True)
        api.protocol.run(parse(OUT_OF_REACH, "out_of_reach.mtprot"))
        st = api.protocol.wait(30)
    except api.MtpyError as e:
        rep, st = {"ok": False, "coerced": [], "text": ""}, {"state": f"{type(e).__name__}: {e}"}
    finally:
        api.magnet.use_force_table(TABLE)
    p = api.magnet.position()
    co = [e for e in events.events()[n:] if e.kind == "coerced"]
    api.magnet.move_to(0.0).wait(10)                   # the main protocol starts from the top, as before 0018
    hi = safety.profile()["limits"]["magnet_position_mm"]["max"]           # 39 mm until profile v8, 40.9 from v9
    f_hi = api.magnet.force_at(hi, WIDE_TABLE)
    co_ok = len(rep["coerced"]) == 1 and abs(rep["coerced"][0]["applied"] - f_hi) < 1e-3         and f"hold f={rep['coerced'][0]['text']} t=0.1" in rep["text"]
    r.check(f"force beyond the magnet position limit coerced, not refused; runs to the {hi:g} mm limit (0018)",
            rep["ok"] and co_ok
            and st["state"] == "completed" and abs(p - hi) < 0.01 and len(co) == 1, f"{st['state']}, {p:.3f} mm, "
            f"{[(c['requested'], c['applied']) for c in rep['coerced']]}")


def _engage_mid_move(r, target_lo=11.0, target_hi=16.0, timeout_s=20.0):
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        p = api.magnet.position()
        if target_lo < p < target_hi:
            estop.engage("walking skeleton: e-stop mid-protocol")
            return p
        time.sleep(0.01)
    r.check("magnet reached the e-stop window", False, f"never between {target_lo} and {target_hi} mm")
    return None


def check_destination(out):
    """Review l2s-wp6-r1: refuse BEFORE anything is written when the destination config folder `<out>/config` is the
    repository's `config/`, lies inside it or contains it, or already exists (it is never deleted or replaced)."""
    cfg, repo_cfg = (Path(out) / "config").resolve(), (REPO / "config").resolve()
    if cfg == repo_cfg or cfg.is_relative_to(repo_cfg) or repo_cfg.is_relative_to(cfg):
        raise ValueError(f"refused: the skeleton's config copy {cfg} would overlap the repository's {repo_cfg}; "
                         "choose an output folder outside the repository's config/")
    if cfg.exists():
        raise ValueError(f"refused: {cfg} already exists; the skeleton never deletes or replaces a config folder - "
                         "use a new output folder")
    return cfg


def run(out, fixture=FIXTURE, estop_variant=False, name=None):
    """Run the skeleton into the folder `out` (created; must not hold the run file or a `config` folder). Returns
    the Report. ValueError, with nothing written, when the destination is refused (check_destination)."""
    out = Path(out)
    cfg = check_destination(out)
    out.mkdir(parents=True, exist_ok=True)
    name = name or ("skeleton_estop" if estop_variant else "skeleton")
    r = Report()
    fixture = Path(fixture) if fixture else None
    cal = fixture / "cal002" if fixture else None
    if cal is None or not cal.is_file():
        r.check("fixture .cal available (beads incl. the reference bead)", False, f"no {cal}")
        return r
    shipped = _sha(REPO / "config")
    saved = (safety.CONFIG, safety._active, api.beads._selected)
    shutil.copytree(REPO / "config", cfg)              # cfg does not exist (check_destination): never overwritten
    prot = out / f"{name}.mtprot"
    prot.write_text(PROTOCOL_ESTOP if estop_variant else PROTOCOL, encoding="utf-8")
    h5 = out / f"{name}.h5"
    t_estop = None
    try:
        safety.CONFIG = cfg
        safety.load_active()
        with events.as_caller("gui"):
            estop.clear()
            api.devices.connect({"backend": "sim", "fixture": str(fixture)})
            _equation_is_the_default(r)
            api.magnet.use_force_table(TABLE)
            script = api.protocol.load(prot)
            _out_of_reach_coerced(r)
            _shipped_profile_passes(r, script)
            got = api.camera.apply_preset(PRESET)
            r.check("camera preset applied and read back (U15)", abs(got["rate_Hz"] - 90.0) < 0.01, got)
            api.beads.select(BEADS, cal_path=cal)
            n0 = len(events.events())
            api.acq.start(record=True, name=name, folder=out, roles=ROLES)
            api.acq.wait_frames(30, 10)
            api.protocol.run(script)
            if estop_variant:
                p_engaged = _engage_mid_move(r)
                st = api.protocol.wait(30)
                t_estop = next(e.t for e in events.events()[n0:] if e.kind == "estop")
                p1 = api.magnet.position()
                f1 = api.acq.status()["frames_received"]
                api.acq.wait_frames(45, 10)                  # half a second more of frames, e-stop still engaged
                acq_mid = api.acq.status()
                estop.clear()
                time.sleep(0.3)
                p2 = api.magnet.position()
                r.facts.update(p_engaged=p_engaged, p_after=p1, p_after_release=p2)
                r.check("e-stop: the run is aborted", st["state"] == "aborted", st["reason"])
                r.check("e-stop: the magnet stopped in place and stays there after the release",
                        p_engaged is not None and abs(p2 - p1) < 0.005 and p1 < 17.0, f"{p1:.4f} -> {p2:.4f} mm")
                r.check("e-stop: acquisition and recording go on",
                        acq_mid["running"] and acq_mid["recording"] and acq_mid["frames_received"] > f1,
                        f"{f1} -> {acq_mid['frames_received']} frames")
            else:
                st = api.protocol.wait(60)
                r.check("protocol completed by 'end protocol'", st["state"] == "completed"
                        and "recording left as it is" in (st["reason"] or ""), st["reason"])
                acq_mid = api.acq.status()
                r.check("after 'end protocol': recording still on, acquisition still running (0016 item 3)",
                        acq_mid["running"] and acq_mid["recording"])
                api.acq.wait_frames(20, 10)
                api.acq.set_recording(False)          # the skeleton (the user) switches recording off itself
            acq = api.acq.stop()
            r.check("acquisition stopped completely, no storage error",
                    acq["stop"] == "complete" and acq["sink_failures"] == 0
                    and acq["camera_stop"] == {"stop_call": "ok", "camera_acquiring": False},
                    {k: acq[k] for k in ("stop", "sink_failures", "sink_error", "camera_stop")})
    finally:
        with events.as_caller("gui"):
            if api.protocol.running():
                api.protocol.stop()
                api.protocol.wait(10)
            if api.acq.running():
                api.acq.stop()
            api.devices.disconnect()
            estop.clear()
        safety.CONFIG, safety._active, api.beads._selected = saved
    r.check("shipped config/ unchanged (sha256 of every profile file)", _sha(REPO / "config") == shipped)
    _verify_file(r, h5, out, cal, estop_variant, t_estop)
    return r


def _verify_file(r, h5, out, cal, estop_variant, t_estop):
    run = read_run(h5)
    a, mt, seg, ev = run["attrs"], run["mt"], run["segments"], run["events"]
    n = len(mt["buffer_number"])
    r.facts.update(frames=n, h5=str(h5))
    r.check("file closed cleanly, every recorded frame written, none outside the recording",
            a["closed_cleanly"] == 1 and a["frames_written"] == n and a["frames_not_written"] == 0
            and a["frames_outside_recordings"] == 0 and a["sink_failures"] == 0,
            {k: a.get(k) for k in ("closed_cleanly", "frames_written", "frames_not_written",
                                   "frames_outside_recordings", "sink_failures")})
    buf = mt["buffer_number"].astype(np.int64)
    rec = run["recordings"]
    r.check("frames: one segment, buffer numbers increasing, rows = recorded frames",
            n > 50 and seg["number"].tolist() == [1] and (np.diff(buf) > 0).all()
            and int(seg["frames_recorded"][0]) == n and int(rec["on_buffer"][0]) < buf[0]
            and (estop_variant or int(rec["off_buffer"][0]) == buf[-1]),
            f"{n} rows, buffers {buf[0]}..{buf[-1]}, on {rec['on_buffer'][0]}, off {rec['off_buffer'][0]}")
    rate = run["metadata"]["run"]["frame_rate_hz"]
    r.check("rate (U15): preset / read back / measured all present and agreeing",
            np.isfinite(rate).all() and abs(rate[0] - 90.0) < 1e-9 and abs(rate[1] - 90.0) < 0.01
            and abs(rate[2] - rate[1]) < 1e-3 * rate[1] and abs(seg["rate_Hz"][0] - rate[1]) < 1e-9,
            rate.tolist())
    steps = [(d["line"], d["phase"]) for d in ev["protocol_step"]["data"]]
    acts = [d["action"] for d in ev["protocol"]["data"]]
    mag = mt["magnet_mm"]
    r.check("magnet position on every frame (poller), following the moves",
            np.isfinite(mag).all() and np.isfinite(mt["rotor_deg"]).all() and (np.diff(mt["magnet_t"]) >= 0).all()
            and len(np.unique(np.round(mag, 3))) > 10 and "motor_reading" in ev,
            f"{len(np.unique(np.round(mag, 3)))} distinct values, {mag.min():.3f}..{mag.max():.3f} mm")
    if estop_variant:
        t0 = a["t0_unix"]
        after = (mt["t_host"] + t0) > t_estop + 0.05
        r.check("e-stop in the file: event, aborted step, recording went on after it",
                "estop" in ev and steps[-1] == (5, "aborted") and acts == ["start", "end"] and after.sum() >= 20,
                f"steps {steps}, {int(after.sum())} rows after the stop")
        r.check("e-stop in the file: the magnet column is constant after the stop",
                np.ptp(mag[after]) < 0.01 and mag[after].max() < 17.0, f"{mag[after].min():.4f}..{mag[after].max():.4f}")
        # review l2s-wp6-r1: the poller kept reading the magnet after the stop (>= 2 new readings with distinct
        # completion times, magnet only) and those readings are what /mt shows after them
        t_reads = sorted({d["t_read"] for d in ev["motor_reading"]["data"]
                          if d["device"] == "magnet" and not d.get("repeated") and d["t_read"] > t_estop})
        shown = sorted({t for t in (mt["magnet_t"][after] + t0) if t > t_estop})
        r.check("e-stop: >= 2 new magnet readings after the stop, shown in /mt",
                len(t_reads) >= 2 and len(shown) >= 2
                and all(np.min(np.abs(np.asarray(t_reads) - t)) < 1e-5 for t in shown),
                f"{len(t_reads)} readings after the stop, {len(shown)} of them in /mt")
        acts_after = [e for e in ev.get("act", {}).get("t_host", []) if e + t0 > t_estop]
        r.check("e-stop in the file: no move read-back after the stop", not acts_after)
        r.check("e-stop: 'mark never' not reached", "mark" not in ev or "never" not in
                [d["text"] for d in ev["mark"]["data"]])
    else:
        ends = [ln for ln, ph in steps if ph == "end"]
        r.check("events: every protocol step start / end with its line, then 'end protocol'",
                ends == STEP_LINES[:-1] and steps[-2:] == [(STEP_LINES[-1], "start"), (STEP_LINES[-1], "completed")]
                and acts == ["start", "warning", "end_statement", "end"], f"ends {ends}, protocol {acts}")
        r.check("events: mark, recording on / off, magnet moves", "midway" in [d["text"] for d in ev["mark"]["data"]]
                and [d["action"] for d in ev["recording"]["data"]] == ["on", "off"]
                and len(ev["act"]["event_id"]) >= 5)
        r.check("magnet: 10 mm at the 1 pN hold, back at 0 mm at the end",
                abs(mag.max() - 11.111) < 0.05 and abs(mag[-1]) < 0.01, f"max {mag.max():.3f}, last {mag[-1]:.3f}")
    paths = export_tra(h5)
    _, rows = read_tra(paths[0])
    first = buf.min()
    ok = (mt["dropped"] == 0) & (mt["track_error"] == 0)
    m = legacy_matrix(h5)[1]
    r.check(".tra: frame column from the first recorded frame, magnet column = /mt",
            len(paths) == 1 and rows[0, 0] == 0.0 and np.array_equal(rows[:, 0], (buf[ok] - first).astype(float))
            and np.array_equal(rows[:, 1], mag[ok]) and np.array_equal(rows, m)
            and np.array_equal(rows[:, 3], mt["x_px"][ok, 0]),
            f"{paths[0].name}: {rows.shape}, first frame column {rows[0, 0]}")
    c = export_cal(h5, out / (h5.stem + ".cal"))
    r.check(".cal export byte-identical to the selected .cal", c.read_bytes() == cal.read_bytes())
    beads = run["beads"]
    r.check("beads: bead 1 is the reference (user role), tracked positions present",
            beads["role"].tolist() == ["reference"] + ["tethered"] * 4
            and set(beads["role_source"].tolist()) == {"user"} and np.isfinite(mt["x_px"][ok]).all(),
            beads["role"].tolist())
    r.facts.update(tra=[str(p) for p in paths], cal=str(c))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output folder (run file, protocol, exports, config copy)")
    ap.add_argument("--fixture", default=str(FIXTURE), help="folder with img*.tif and cal002 (default: the G: fixture)")
    ap.add_argument("--estop", action="store_true", help="engage the emergency stop during a magnet move")
    a = ap.parse_args(argv)
    r = run(a.out, a.fixture, a.estop)
    for c in r.checks:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + (f"  [{c['detail']}]" if not c["ok"] else ""))
    print("RESULT " + json.dumps({"ok": r.ok, "checks": len(r.checks), "failed": [c["check"] for c in r.failed],
                                  **r.facts}, default=str))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
