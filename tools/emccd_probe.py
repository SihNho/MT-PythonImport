r"""emccd_probe.py - first contact with the Andor iXon Ultra through `api.emccd` on the rig (owner 2026-10-30).

  RIG, inside V6 tools/rig_session.py --no-motor-session (holds the rig lock; kills on refusal):
  py tools/rig_session.py --purpose "LabVIEW2Scr: iXon probe" --no-motor-session --max-min 20 -- \
      G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -u G:\Codes\LabVIEW2Scr\tools\emccd_probe.py --out <dir>

Connects the `real` backend (JAI + iXon, motors simulated), prints the iXon's identity, limits and settings as read,
applies a preset (exposure, rate, gain mode, gain, temperature) with read-back, snaps one frame (saved as .npy),
then disconnects (cooler off, warm-up wait, ShutDown) and prints the result as `SUMMARY {...}`. Nothing moves.
EM gain stays 0 by default (the light level is unknown; manual "Safety envelope").
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", default="real", help="sim = a dry run on the simulators")
    ap.add_argument("--exposure-ms", type=float, default=30.0)
    ap.add_argument("--rate", type=float, default=20.0)
    ap.add_argument("--gain-mode", type=int, default=0, help="0 = 8 bit DAC (gain 0 = none); 3 = real EM gain (>= 1)")
    ap.add_argument("--gain", type=int, default=0)
    ap.add_argument("--temperature", type=int, default=0, help="set point C (0: cooler on, no long warm-up at close)")
    a = ap.parse_args(argv)
    import numpy as np

    from mtpy import api
    from mtpy.api import estop, events
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = time.strftime("emccd_%Y%m%d_%H%M%S")
    r = {"name": name, "steps": []}

    def step(what, fn):
        t0 = time.perf_counter()
        try:
            got = fn()
            r["steps"].append({"step": what, "ok": True, "s": round(time.perf_counter() - t0, 2), "result": got})
            print(f"OK   {what} ({time.perf_counter() - t0:.1f} s): {got}", flush=True)
            return got
        except Exception as e:  # noqa: BLE001 - recorded, the probe goes on to the cleanup
            r["steps"].append({"step": what, "ok": False, "s": round(time.perf_counter() - t0, 2),
                               "error": f"{type(e).__name__}: {e}"})
            print(f"FAIL {what} ({time.perf_counter() - t0:.1f} s): {type(e).__name__}: {e}", flush=True)
            return None

    try:
        with events.as_caller("gui"):
            estop.clear()
            def connect():
                st = api.devices.connect({"backend": a.backend})
                if st["emccd"]["state"] != "connected":
                    raise RuntimeError(f"emccd not connected: {st['emccd']['last_error']}")
                return st["emccd"]
            if step("connect", connect):
                step("info", lambda: api.devices.info("emccd"))
                step("preset", lambda: api.emccd.apply_preset({
                    "name": "probe", "em_gain_mode": a.gain_mode, "em_gain": a.gain, "exposure_ms": a.exposure_ms,
                    "rate_Hz": a.rate, "temperature_C": a.temperature}))
                step("settings", api.emccd.settings)

                def snap():
                    img = api.emccd.snap()
                    np.save(out / f"{name}.npy", img)
                    return {"shape": img.shape, "min": int(img.min()), "max": int(img.max()),
                            "mean": float(img.mean()), "file": str(out / f"{name}.npy")}
                step("snap (shutter opened by the start)", snap)
                step("shutter closed", lambda: api.emccd.set_shutter(2))
                step("snap shutter closed", snap)
                step("shutter open", lambda: api.emccd.set_shutter(1))
                step("snap shutter open", snap)
                step("exposure x0.5", lambda: api.emccd.set_exposure(a.exposure_ms * 0.5))
                step("snap x0.5", snap)
                step("settings after", api.emccd.settings)
    finally:
        with events.as_caller("gui"):
            step("disconnect (cooler off, warm-up wait, ShutDown)", api.devices.disconnect)
        (out / f"{name}.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
        print("SUMMARY " + json.dumps({s["step"]: s["ok"] for s in r["steps"]}), flush=True)
    return 0 if all(s["ok"] for s in r["steps"]) else 1


if __name__ == "__main__":
    sys.exit(main())
