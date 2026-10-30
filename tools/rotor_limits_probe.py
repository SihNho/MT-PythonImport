r"""rotor_limits_probe.py - READ-ONLY look at the Autonics PMC-2HS soft-limit parameters
(owner 2026-10-30: "로터도 하드웨어 리밋 따라가자"). RIG, inside V6 tools/rig_session.py --no-motor-session;
sends only queries, never a setting or a move:

  py tools/rig_session.py --purpose "rotor soft-limit probe (read-only)" --no-motor-session --max-min 5 -- \
      G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -u G:\Codes\LabVIEW2Scr\tools\rotor_limits_probe.py

Reads (manual DRW170814AB pp. 76-78, parameter table p. 78): POS, ERD X (bits 9 / 8 = soft limit - / + error),
IXR X7A soft limit + and IXR X7B soft limit - (4-byte, pulses), IHR XE4 operation mode 2 (digit 6 "Soft Limit",
0 = ENABLE, 1 = DISABLE - the manual marks the logic as reversed), IHR XE6 speed multiplier, VER. Prints one line per
query and a RESULT line with the decoded values.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _signed32(h):
    v = int(h, 16)
    return v - (1 << 32) if v >= (1 << 31) else v


def main():
    from mtpy.devices import autonics, gate
    from mtpy.devices.gate import Line
    gate.permitted("the rotor probe")
    L = Line.open(autonics.PORT, autonics.BAUD, b"\r", b"\r", 1.5)
    out = {}
    try:
        L.ask("POS")                                  # the first read after opening times out (V6 note)
        time.sleep(0.2)
        for q in ("POS", "ERD X", "IXR X7A", "IXR X7B", "IHR XE4", "IHR XE6", "VER"):
            r = L.ask(q)
            out[q] = r
            print(f"{q:8s} -> {r!r}", flush=True)
            time.sleep(0.15)
    finally:
        L.close()
    dec = {}
    try:
        dec["position_pulses"] = _signed32(out["POS"].split()[1].split(",")[0])
        dec["soft_limit_plus_pulses"] = _signed32(out["IXR X7A"].split(",")[1])
        dec["soft_limit_minus_pulses"] = _signed32(out["IXR X7B"].split(",")[1])
        mode2 = int(out["IHR XE4"].split(",")[1], 16)
        dec["operation_mode2_hex"] = f"{mode2:04X}"
        dec["note"] = "REG72 digit 6 = soft limit (0 enable, 1 disable, reversed); how the digits map onto this word is unconfirmed"
        dec["speed_multiplier"] = int(out["IHR XE6"].split(",")[1], 16)
        e = out["ERD X"].split()[1] if out["ERD X"].startswith("ERD") else ""
        dec["error_hex"] = e.removeprefix("X")        # the controller answers 'ERD X4000'
    except (IndexError, ValueError, KeyError) as e:
        dec["decode_error"] = f"{type(e).__name__}: {e}"
    print("RESULT " + json.dumps({"raw": out, "decoded": dec}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
