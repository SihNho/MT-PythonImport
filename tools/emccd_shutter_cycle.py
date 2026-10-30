r"""emccd_shutter_cycle.py - cycle the iXon's internal shutter so the owner can hear it (owner 2026-10-30:
"셔터 열리는 소리가 안들림. 20회 열었다 닫았다 반복할것.").

  RIG, inside V6 tools/rig_session.py --no-motor-session (holds the rig lock):
  py tools/rig_session.py --purpose "iXon shutter cycles" --no-motor-session --max-min 8 -- \
      G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -u G:\Codes\LabVIEW2Scr\tools\emccd_shutter_cycle.py

Opens the iXon alone (no JAI, no acquisition), then SetShutter(typ, 1 open, 50, 50) / (typ, 2 closed, 50, 50) --cycles
times about --pause s apart, one line per call with the SDK return code (20002 = DRV_SUCCESS); first with TTL type
--ttl (1 = high to open, the lab's smCamera value), then --alt cycles with the other TTL type and --alt cycles with
SetShutterEx (internal + external mode), so a wrong TTL polarity or an external-shutter wiring would show as a
difference. Closes the camera (shutter closed, ShutDown) at the end.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=20)
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--ttl", type=int, default=1)
    ap.add_argument("--alt", type=int, default=3)
    a = ap.parse_args(argv)
    from mtpy.devices.ixon import DRV_SUCCESS, AndorError, IxonCamera

    def call(sdk, *args):
        try:
            rc = sdk(*args)
        except AndorError as e:
            rc = str(e)
        print(f"{time.strftime('%H:%M:%S')} {args} -> {rc}", flush=True)
        return rc == DRV_SUCCESS

    dev = IxonCamera()
    t0 = time.perf_counter()
    dev.open()
    print(f"open {time.perf_counter() - t0:.1f} s: {dev.identity()}", flush=True)
    ok = 0
    try:
        sdk = dev.sdk
        print(f"CYCLING START: {a.cycles} x (open, closed), TTL type {a.ttl}, {a.pause} s apart", flush=True)
        for i in range(a.cycles):
            if not call(sdk, "SetShutter", a.ttl, 1, 50, 50):
                print(f"STOPPED at cycle {i + 1} (open): not DRV_SUCCESS", flush=True)
                break
            ok += 1
            time.sleep(a.pause)
            if not call(sdk, "SetShutter", a.ttl, 2, 50, 50):
                print(f"STOPPED at cycle {i + 1} (closed): not DRV_SUCCESS", flush=True)
                break
            ok += 1
            time.sleep(a.pause)
        other = 1 - a.ttl
        print(f"ALT: {a.alt} cycles with TTL type {other}", flush=True)
        for i in range(a.alt):
            call(sdk, "SetShutter", other, 1, 50, 50)
            time.sleep(a.pause)
            call(sdk, "SetShutter", other, 2, 50, 50)
            time.sleep(a.pause)
        print(f"ALT: {a.alt} cycles with SetShutterEx (internal and external mode together)", flush=True)
        for i in range(a.alt):
            call(sdk, "SetShutterEx", a.ttl, 1, 50, 50, 1)
            time.sleep(a.pause)
            call(sdk, "SetShutterEx", a.ttl, 2, 50, 50, 2)
            time.sleep(a.pause)
    finally:
        dev.close()
        print(f"DONE: {ok} of {2 * a.cycles} main SetShutter calls returned DRV_SUCCESS; camera closed (ShutDown)",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
