r"""phase7_sequence.py - the owner's motor sequence of 2026-10-30 through the API (every move checked by the profile and
the motion gate). RIG, inside V6 tools/rig_session.py --no-motor-session:

  py tools/rig_session.py --purpose "LabVIEW2Scr motor sequence" --no-motor-session --max-min 20 -- \
      G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -u G:\Codes\LabVIEW2Scr\tools\phase7_sequence.py --out <dir>

Owner: "PI motor 0 --> 30 --> 0 (motor speed 15 mm/s, no wait) / rotor -10 turns --> +10 turns --> 0 /
Piezo stage: +2 um --> -2 um --> 0 / X,Y: +0.5 mm --> -0.5 mm --> 0, each". "No wait" = no dwell at the target: the
next move is sent as soon as the previous one has arrived. Every target outside the profile is requested anyway and
the refusal recorded (the rotor window is +-5 turns, so +-10 is expected to be refused). Writes
`<out>/sequence_<time>.json` and prints STEP / RESULT lines.
"""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

R = {"steps": []}


def step(name, fn):
    t0 = time.perf_counter()
    rec = {"step": name}
    try:
        rec["result"] = fn()
        rec["ok"] = True
    except Exception as e:  # noqa: BLE001 - every outcome is recorded; the run goes on to the cleanup
        rec["ok"], rec["error"] = False, f"{type(e).__name__}: {e}"
    rec["s"] = round(time.perf_counter() - t0, 3)
    R["steps"].append(rec)
    print(f"STEP {name}: {'ok' if rec['ok'] else 'FAIL'} {rec.get('result', rec.get('error'))} ({rec['s']} s)", flush=True)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", default="real-motors")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = time.strftime("sequence_%Y%m%d_%H%M%S")
    from mtpy import api
    from mtpy.api import estop, events
    fails = []
    try:
        with events.as_caller("gui"):
            estop.clear()
            st = step("connect", lambda: api.devices.connect({"backend": a.backend}))
            bad = [n for n, s in (st.get("result") or {}).items() if s["state"] != "connected"]
            if bad:
                raise RuntimeError(f"not connected: {bad}")
            # --- PI magnet 0 -> 30 -> 0 at 15 mm/s, no dwell
            step("magnet at 0 mm", lambda: api.magnet.move_to(0.0, 15.0).wait(30))
            for p in (30.0, 0.0):
                step(f"magnet {p:g} mm @ 15 mm/s", lambda p=p: api.magnet.move_to(p, 15.0).wait(30))
            # --- rotor -10 -> +10 -> 0 (relative to now); outside the +-5 window the API refuses
            r0 = step("rotor position (turns)", api.rotor.position)["result"]
            for t in (-10.0, 10.0, 0.0):
                step(f"rotor to {t:+g} turns from start",
                     lambda t=t: api.rotor.rotate(t - (api.rotor.position() - r0)).wait(60))
            # --- focus +2 -> -2 -> 0 um relative to now
            z0 = step("focus position (um)", api.focus.position)["result"]
            for dz in (2.0, -2.0, 0.0):
                step(f"focus {dz:+g} um", lambda dz=dz: api.focus.move_to(z0 + dz).wait(10))
            # --- stage x then y: +0.5 -> -0.5 -> 0 mm relative to now
            x0, y0 = step("stage position (mm)", api.stage.position)["result"]
            for axis in ("x", "y"):
                for d in (0.5, -0.5, 0.0):
                    tgt = (x0 + d, y0) if axis == "x" else (x0, y0 + d)
                    step(f"stage {axis} {d:+g} mm", lambda tgt=tgt: api.stage.move_to(*tgt).wait(30))
    except Exception:  # noqa: BLE001
        R["error"] = traceback.format_exc()
        print("ERROR " + R["error"], flush=True)
    finally:
        with events.as_caller("gui"):
            step("disconnect (magnet home, limits released)", api.devices.disconnect)
        (out / f"{name}.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
        fails = [s["step"] for s in R["steps"] if not s["ok"]]
        print(f"RESULT {json.dumps({'steps': len(R['steps']), 'failed': fails, 'file': str(out / (name + '.json'))})}", flush=True)
    return 1 if R.get("error") or fails else 0


if __name__ == "__main__":
    sys.exit(main())
