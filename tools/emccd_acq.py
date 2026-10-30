r"""emccd_acq.py - a timed acquisition on the Andor iXon Ultra through `api.emccd`.

Owner 2026-10-30 (relayed by the main session): "EM gain 0으로 acquisition 해볼 것. 50 fps, 1 min."

  RIG, inside V6 tools/rig_session.py --no-motor-session (holds the rig lock; kills on refusal):
  py tools/rig_session.py --purpose "LabVIEW2Scr: iXon 50 fps 1 min" --no-motor-session --max-min 20 -- \
      G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -u G:\Codes\LabVIEW2Scr\tools\emccd_acq.py --out <dir>

Connects the `real` backend, applies the preset (frame transfer on, gain mode, gain, rate; the exposure equals the
period), STOPS if the read-back rate is not the requested one (the reachable maximum is reported, never a lower
rate substituted), then reads the SDK ring for --seconds: frames received, SDK frame numbers (a jump = loss), the
rate measured on the PC clock, mean counts per frame, the sensor temperature and cooler state every 10 s. Writes
`<out>/<name>.json` (and the first frame as .npy), prints `SUMMARY {...}`, disconnects (cooler off, ShutDown).
Nothing moves; the motors stay simulated.
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
    ap.add_argument("--fps", type=float, default=50.0)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--gain-mode", type=int, default=0)
    ap.add_argument("--gain", type=int, default=0)
    ap.add_argument("--frame-transfer", type=int, default=1)
    a = ap.parse_args(argv)
    import numpy as np

    from mtpy import api
    from mtpy.api import estop, events
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = time.strftime("emccd_acq_%Y%m%d_%H%M%S")
    r = {"name": name, "request": vars(a), "error": None}
    try:
        with events.as_caller("gui"):
            estop.clear()
            st = api.devices.connect({"backend": a.backend})
            if st["emccd"]["state"] != "connected":
                raise RuntimeError(f"emccd not connected: {st['emccd']['last_error']}")
            r["identity"] = api.devices.info("emccd")["identity"]
            r["preset_readback"] = api.emccd.apply_preset({
                "name": "acq", "frame_transfer": a.frame_transfer, "em_gain_mode": a.gain_mode, "em_gain": a.gain,
                "rate_Hz": a.fps})
            r["limits"] = api.devices.info("emccd")["limits"]
            got = r["preset_readback"]["rate_Hz"]
            if abs(got - a.fps) > 0.01 * a.fps:
                raise RuntimeError(f"{a.fps:g} fps not reached: read back {got:.3f} Hz; limits {r['limits']['rate_Hz']}")
            print(f"preset read back {r['preset_readback']}", flush=True)
            api.emccd.start()
            t0 = time.perf_counter()
            n, last, lost, jumps, means, temps, t_first = 0, 0, 0, [], [], [], None
            t_temp = t0
            while time.perf_counter() - t0 < a.seconds:
                got = api.emccd.read_new()
                if got is not None:
                    first, new_last, frames = got
                    if t_first is None:
                        t_first = time.perf_counter()
                        np.save(out / f"{name}_frame1.npy", frames[0])
                    if first != last + 1:
                        lost += first - last - 1
                        jumps.append((last, first))
                    n += new_last - first + 1
                    last = new_last
                    means.append(float(frames.mean()))
                if time.perf_counter() - t_temp >= 10.0:
                    s = api.emccd.settings()
                    temps.append({"t_s": round(time.perf_counter() - t0, 1), "sensor_C": s["sensor_temperature_C"],
                                  "cooler": s["cooler"], "rate_Hz": s["rate_Hz"], "exposure_ms": s["exposure_ms"]})
                    print(f"{temps[-1]}  frames {n} lost {lost}", flush=True)
                    t_temp = time.perf_counter()
                time.sleep(0.1)
            t_end = time.perf_counter()
            r["total_acquired"] = api.emccd.total_acquired()
            api.emccd.stop()
            r["result"] = {"frames_received": n, "last_frame_number": last, "frames_lost": lost, "jumps": jumps[:20],
                           "rate_measured_Hz": (n - 1) / (t_end - t_first) if n > 1 else None,
                           "seconds": t_end - t0, "mean_counts": float(np.mean(means)) if means else None,
                           "mean_counts_min_max": (min(means), max(means)) if means else None, "temps": temps,
                           "settings_after": api.emccd.settings()}
    except Exception as e:  # noqa: BLE001 - recorded; cleanup below
        r["error"] = f"{type(e).__name__}: {e}"
        print(f"ERROR {r['error']}", flush=True)
    finally:
        with events.as_caller("gui"):
            try:
                api.devices.disconnect()
                r["cleanup"] = "disconnected (cooler off, ShutDown)"
            except Exception as e:  # noqa: BLE001
                r["cleanup"] = f"FAILED {type(e).__name__}: {e}"
        (out / f"{name}.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
        print("SUMMARY " + json.dumps({k: r.get(k) for k in ("error", "preset_readback", "total_acquired", "result",
                                                            "cleanup")}, default=str), flush=True)
    return 0 if r["error"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
