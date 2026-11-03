"""The reduced bench matrix of 2026-11-01 21:00 (owner: "run the configuration you recommended; the rest is filled in
later when the bench is done properly"). Blocks run one after another, each its own process of rig_accuracy.py or
gui_rig_isolate.py with the environment below, logs in bench_out/matrix/<block>.log, data in
G:\\l2s_rig_data\\2026-11-01_m_<block>. A failed block is reported and the next one starts; the runner stops when the
rig lock stays held after a block (a cleanup that did not finish) or when bench_out/matrix/STOP exists.

Blocks: script 50 / 100 beads at 90, 150, 248 (full frame) and 555 Hz (half ROI, beads 2-4); the focus block at
90 Hz, 20 beads, numba: step 20 / 50 / 100 nm x speed 1 / 0.1 and the +-1 um pattern at speed 0.1; the GUI client
at the four rates with 5-100 beads, all methods and executors (a fresh LUT per block). The runs of 20:06-20:59
(script, 5-20 beads, no stage steps) stay as they are.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"G:\Codes\rig")
import riglock

ROOT = Path(r"G:\Codes\LabVIEW2Scr")
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOGS = ROOT / "bench_out" / "matrix"
DATA = r"G:\l2s_rig_data\2026-11-01_m_"
# 11-03 channel (owner: reference 5, 6, 7 + magnetic 1 of candidates_numbered.png): the half ROI holds 5, 6 and 1
ROI = {"ROI": "296,300,640,512", "PICK_IDS": "1,2,4"}      # 19:09 magnet check: none of the four responds, all reference
CASES = ",".join(f"{n}:{ex}:{zm}" for n in (5, 10, 20, 50, 100) for zm in ("current", "spline", "phase_spline")
                 for ex in ("numba", "gpu"))
GUI = {"CLIENT": "1", "STEPS": "1", "MAKE_CAL": "1", "CONDITIONS": "normal", "CASES": CASES}
BLOCKS = [
    ("s90", "rig_accuracy.py", {"FPS": "90", "COUNTS": "50,100"}),
    ("s150", "rig_accuracy.py", {"FPS": "150", "COUNTS": "50,100"}),
    ("s248", "rig_accuracy.py", {"FPS": "max", "COUNTS": "50,100"}),
    ("s555", "rig_accuracy.py", {"FPS": "max", "COUNTS": "50,100", **ROI}),
    *[(f"p{nm}_v{v}".replace(".", ""), "rig_accuracy.py",
       {"FPS": "90", "COUNTS": "20", "EXEC": "numba", "HOLD_S": "3", "STEP_NM": str(nm), "SPEED_FACTOR": str(v)})
      for nm in (20, 50, 100) for v in (1, 0.1)],
    ("ppm1_v01", "rig_accuracy.py", {"FPS": "90", "COUNTS": "20", "EXEC": "numba", "SPEED_FACTOR": "0.1"}),
    # owner 2026-11-01 22:12: one more focus speed, 1 um/s or the closest the controller takes
    *[(f"p{nm}_v1um", "rig_accuracy.py",
       {"FPS": "90", "COUNTS": "20", "EXEC": "numba", "HOLD_S": "3", "STEP_NM": str(nm), "SPEED_MM_S": "0.001"})
      for nm in (20, 50, 100)],
    ("ppm1_v1um", "rig_accuracy.py", {"FPS": "90", "COUNTS": "20", "EXEC": "numba", "SPEED_MM_S": "0.001"}),
    ("g90", "gui_rig_isolate.py", {"FPS": "90", **GUI}),
    ("g150", "gui_rig_isolate.py", {"FPS": "150", **GUI}),
    ("g248", "gui_rig_isolate.py", {"FPS": "max", **GUI}),
    ("g555", "gui_rig_isolate.py", {"FPS": "max", **GUI, **ROI}),
]


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:]                       # block names to run; none = all
    summary = []
    for name, tool, env in BLOCKS:
        if only and name not in only:
            continue
        if (LOGS / "STOP").exists():
            say("STOP file found; not starting", name)
            break
        out = DATA + name
        if Path(out).exists():
            say(f"{name}: {out} exists, skipped (remove it to rerun)")
            continue
        log = LOGS / f"{name}.log"
        say(f"{name}: {tool} {env} -> {out}")
        t0 = time.monotonic()
        with open(log, "w", encoding="utf-8") as f:
            rc = subprocess.run([str(PY), str(ROOT / "tools" / tool)], env={**os.environ, **env, "OUT": out},
                                stdout=f, stderr=subprocess.STDOUT, cwd=str(ROOT), check=False).returncode
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        failed = [ln for ln in lines if "FAILED" in ln or "Traceback" in ln]
        say(f"{name}: exit {rc} in {(time.monotonic() - t0) / 60:.1f} min; {len(failed)} failure lines"
            + (f"; first: {failed[0][:160]}" if failed else ""))
        summary.append({"block": name, "exit": rc, "minutes": (time.monotonic() - t0) / 60, "failures": failed[:3]})
        (LOGS / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        st = riglock.status()
        if st.get("holder") is not None:
            say(f"rig lock still held after {name}: {st['holder']}; stopping (RULES.md: never take over a stale lock here)")
            break
    say("matrix done:", json.dumps(summary, default=str)[:800])


if __name__ == "__main__":
    main()
