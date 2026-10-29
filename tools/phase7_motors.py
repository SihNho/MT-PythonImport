r"""phase7_motors.py - phase 7 first rig run: the real motors through the API and the project's motion gate
(decision 0025). RIG, inside V6 tools/rig_session.py --no-motor-session (lock only; this gate sets and releases the
controller limits itself):

  py tools/rig_session.py --purpose "LabVIEW2Scr phase 7" --no-motor-session --max-min 20 -- \
      G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -u G:\Codes\LabVIEW2Scr\tools\phase7_motors.py --out <dir>

Connects `real-motors` (PI session: limits 0..39, FNL reference, verify; ASI SL/SU = position +- 2 mm; Z window and
rotor window read), then per device: a few moves inside the envelope read back through the API, a request outside
it refused by the API (profile) and, called on the driver directly, by the gate (before anything is sent). Focus:
decision 0025 - the controller's SL/SU Z become the profile's `focus_z_um` (v6) after a driver move inside them
is read back. Disconnect = magnet home 0 mm, limits released; then an independent read-only check of both
controllers' limits on freshly opened ports. Writes `<out>/phase7_<time>.json` and prints RESULT lines.
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


def expect_refusal(name, fn, exc):
    def body():
        try:
            fn()
        except exc as e:
            return f"refused as expected: {e}"
        raise AssertionError("NOT refused")
    return step(name, body)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", default="real-motors")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = time.strftime("phase7_%Y%m%d_%H%M%S")
    from mtpy import api
    from mtpy.api import estop, events, safety
    from mtpy.api.errors import DeviceError, SafetyRefused
    GATE = (DeviceError, ValueError)      # the service wraps the driver's ValueError in DeviceError
    from mtpy.devices import asi, pi

    def svc(n):
        return api.devices.service(n)

    def direct(n, *args):
        """A driver call through its service thread, bypassing the API's profile check: tests the gate alone."""
        return svc(n).call(svc(n).require().move_to, *args, what="direct move")

    try:
        with events.as_caller("gui"):
            estop.clear()
            st = step("connect", lambda: api.devices.connect({"backend": a.backend}))
            bad = [n for n, s in (st.get("result") or {}).items() if s["state"] != "connected"]
            if bad:
                raise RuntimeError(f"not connected: {bad}")
            for n in ("magnet", "stage", "focus", "rotor"):
                step(f"{n} info", lambda n=n: api.devices.info(n))
            # --- magnet
            step("magnet 5 mm", lambda: api.magnet.move_to(5.0).wait(30))
            step("magnet 39 mm", lambda: api.magnet.move_to(39.0).wait(30))
            step("magnet 40 mm request (API coerces to 39, decision 0018)",
                 lambda: {"m": api.magnet.move_to(40.0).wait(30), "applied": api.magnet.move_to(40.0).applied_mm})
            expect_refusal("magnet driver-direct 40 mm (gate)", lambda: direct("magnet", 40.0), GATE)
            expect_refusal("magnet driver-direct -1 mm (gate)", lambda: direct("magnet", -1.0), GATE)
            step("magnet 0 mm", lambda: api.magnet.move_to(0.0).wait(30))
            # --- stage
            p0 = step("stage position", api.stage.position)["result"]
            if p0:
                step("stage +0.5 mm x", lambda: api.stage.move_to(p0[0] + 0.5, p0[1]).wait(30))
                step("stage -0.5 mm y", lambda: api.stage.move_to(p0[0], p0[1] - 0.5).wait(30))
                step("stage back", lambda: api.stage.move_to(p0[0], p0[1]).wait(30))
                expect_refusal("stage +3 mm x (API profile)", lambda: api.stage.move_to(p0[0] + 3.0, p0[1]), SafetyRefused)
                expect_refusal("stage driver-direct +3 mm x (gate)", lambda: direct("stage", (p0[0] + 3.0, p0[1])), GATE)
            # --- focus (decision 0025)
            zl = step("focus controller limits", lambda: api.devices.info("focus")["limits"])["result"]
            z0 = step("focus position (um)", api.focus.position)["result"]
            fz_set = safety.profile()["limits"]["focus_z_um"]["min"] is not None
            if not fz_set:
                expect_refusal("focus +1 um (API, profile unset)", lambda: api.focus.move_to(z0 + 1.0), SafetyRefused)
            if zl and zl.get("SL_SU_Z_mm") and z0 is not None:
                lo_um, hi_um = (v * 1000.0 for v in zl["SL_SU_Z_mm"])
                step("focus driver-direct +1 um (gate)", lambda: (direct("focus", z0 + 1.0), time.sleep(0.5), api.focus.position())[-1])
                step("focus driver-direct back", lambda: (direct("focus", z0), time.sleep(0.5), api.focus.position())[-1])
                expect_refusal("focus driver-direct beyond SU Z (gate)", lambda: direct("focus", hi_um + 1.0), GATE)

                def profile_v6():
                    from mtpy.admin import safety_admin as admin
                    with events.as_caller("rig-admin"):
                        s = admin.open_admin_session("decision 0025: focus_z_um = the ASI controller's SL/SU Z")
                        lim = safety._thaw(safety.profile()["limits"])
                        lim["focus_z_um"] = {"min": lo_um, "max": hi_um, "unit": "um", "relative_to": None, "verified": True,
                                             "source": f"ASI Tiger SL Z? / SU Z? read on the rig {time.strftime('%Y-%m-%d')} "
                                                       "(decision 0025, owner: 'Focus Z lock은 하드웨어 리밋 따라갈것'); "
                                                       "+1 um driver move read back inside them (tools/phase7_motors.py)"}
                        pend = admin.propose_change(s, lim, by="rig-admin (phase 7 run)", reason="decision 0025")
                        p = admin.activate(s, pend, admin.RecommissioningReport(by="rig-admin (phase 7 run)",
                                                                                   checked={"focus_z_um": True}))
                        return {"version": p["version"], "focus_z_um": p["limits"]["focus_z_um"]}
                if not fz_set:
                    step("profile v6: focus_z_um from the controller", profile_v6)
                step("focus +1 um through the API (profile v6)", lambda: api.focus.move_to(z0 + 1.0).wait(10))
                step("focus back through the API", lambda: api.focus.move_to(z0).wait(10))
            # --- rotor
            r0 = step("rotor position (turns)", api.rotor.position)["result"]
            expect_refusal("rotor +0.5 turn (API, profile unverified)", lambda: api.rotor.rotate(0.5), SafetyRefused)
            if r0 is not None:
                step("rotor driver-direct +0.5 turn (gate)", lambda: (direct("rotor", r0 + 0.5), _settle(api.rotor), api.rotor.position())[-1])
                step("rotor driver-direct back", lambda: (direct("rotor", r0), _settle(api.rotor), api.rotor.position())[-1])
                expect_refusal("rotor driver-direct +6 turns (gate)", lambda: direct("rotor", r0 + 6.0), GATE)
    except Exception:  # noqa: BLE001
        R["error"] = traceback.format_exc()
        print("ERROR " + R["error"], flush=True)
    finally:
        with events.as_caller("gui"):
            step("disconnect (magnet home, limits released)", api.devices.disconnect)
        if a.backend != "sim":           # real ports, read-only, still under the wrapper's lock
            step("independent limit readback after release", lambda: _readback(pi, asi))
        (out / f"{name}.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
        fails = [s["step"] for s in R["steps"] if not s["ok"]]
        print(f"RESULT {json.dumps({'steps': len(R['steps']), 'failed': fails, 'file': str(out / (name + '.json'))})}", flush=True)
    return 1 if R.get("error") or fails else 0


def _settle(rotor, timeout_s=30):
    t_end = time.time() + timeout_s
    last = rotor.position()
    while time.time() < t_end:
        time.sleep(0.3)
        p = rotor.position()
        if p == last:
            return
        last = p


def _readback(pi, asi):
    """Read-only, on fresh port opens: what the controllers hold after the session."""
    from mtpy.devices.gate import Line
    out = {}
    L = Line.open(pi.PORT, pi.BAUD, b"\n", b"\n", 0.6)
    try:
        out["pi"] = {q: L.ask(q) for q in ("TMN?", "TMX?", "POS?", "ERR?")}
    finally:
        L.close()
    L = Line.open(asi.PORT, asi.BAUD, b"\r", b"\r\n", 0.8)
    try:
        out["asi"] = {q: L.ask(q) for q in ("SL X? Y?", "SU X? Y?", "SL Z?", "SU Z?", "W X", "W Y", "W Z")}
    finally:
        L.close()
    return out


if __name__ == "__main__":
    sys.exit(main())
