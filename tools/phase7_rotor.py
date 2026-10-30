r"""phase7_rotor.py - verify the rotor window on the rig and record it in the safety profile (owner 2026-10-30:
"반영하도록 하고"). RIG, inside V6 tools/rig_session.py --no-motor-session:

  py tools/rig_session.py --purpose "LabVIEW2Scr phase 7 rotor" --no-motor-session --max-min 15 -- \
      G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -u G:\Codes\LabVIEW2Scr\tools\phase7_rotor.py --out <dir>

Through the gate alone (driver-direct): to +5 turns (the window's edge), back, -5 turns, back, each read back in
pulses; +5.002 turns (one pulse past the edge) refused. Then the profile's `rotor_turns` is marked verified (v7,
re-commissioning report = these readbacks) and the same +-1 turn is driven through `api.rotor.rotate`. Disconnect.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from phase7_motors import R, _settle, expect_refusal, step


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", default="real-motors")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = time.strftime("phase7_rotor_%Y%m%d_%H%M%S")
    from mtpy import api
    from mtpy.api import estop, events, safety
    from mtpy.api.errors import DeviceError
    svc = api.devices.service

    def direct(turns):
        svc("rotor").call(svc("rotor").require().move_to, turns, what="direct move")
        _settle(api.rotor)
        return api.rotor.position()

    fails = []
    try:
        with events.as_caller("gui"):
            estop.clear()
            st = step("connect", lambda: api.devices.connect({"backend": a.backend}))
            if (st.get("result") or {}).get("rotor", {}).get("state") != "connected":
                raise RuntimeError("rotor not connected")
            r0 = step("rotor start (turns)", api.rotor.position)["result"]
            w = step("rotor window", lambda: api.devices.info("rotor")["limits"])["result"]
            for d in (5.0, 0.0, -5.0, 0.0):
                step(f"driver-direct to start {d:+g} turns", lambda d=d: direct(r0 + d))
            expect_refusal("driver-direct +5.002 turns (one pulse past the edge)", lambda: direct(r0 + 5.002), (DeviceError, ValueError))
            e = safety.profile()["limits"]["rotor_turns"]
            if not e["verified"]:
                def profile_v7():
                    from mtpy.admin import safety_admin as admin
                    with events.as_caller("rig-admin"):
                        s = admin.open_admin_session("rotor window verified on the rig (owner 2026-10-30)")
                        lim = safety._thaw(safety.profile()["limits"])
                        lim["rotor_turns"].update(verified=True, source=(
                            f"+-5 turns from the session start, driven to both edges and read back on the rig "
                            f"{time.strftime('%Y-%m-%d')} (window {w}); one pulse past the edge refused "
                            "(tools/phase7_rotor.py; owner 2026-10-30)"))
                        pend = admin.propose_change(s, lim, by="rig-admin (phase 7 rotor run)", reason="rotor window verified on the rig")
                        p = admin.activate(s, pend, admin.RecommissioningReport(by="rig-admin (phase 7 rotor run)",
                                                                                   checked={"rotor_turns": True}))
                        return {"version": p["version"], "rotor_turns": p["limits"]["rotor_turns"]}
                step("profile: rotor_turns verified", profile_v7)
            step("api.rotor.rotate(+1)", lambda: api.rotor.rotate(1.0).wait(30))
            step("api.rotor.rotate(-1)", lambda: api.rotor.rotate(-1.0).wait(30))
            expect_refusal("api.rotor.rotate(+6) (profile)", lambda: api.rotor.rotate(6.0), Exception)
            step("rotor end (turns)", api.rotor.position)
    except Exception as e:  # noqa: BLE001
        R["error"] = f"{type(e).__name__}: {e}"
        print("ERROR " + R["error"], flush=True)
    finally:
        with events.as_caller("gui"):
            step("disconnect", api.devices.disconnect)
        (out / f"{name}.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
        fails = [s["step"] for s in R["steps"] if not s["ok"]]
        print(f"RESULT {json.dumps({'steps': len(R['steps']), 'failed': fails})}", flush=True)
    return 1 if R.get("error") or fails else 0


if __name__ == "__main__":
    sys.exit(main())
