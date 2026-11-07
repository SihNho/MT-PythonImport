"""Tables of the 2026-11-07 bench (tools/rig_bench_1107.py) from the blocks' report.json (script) and isolate.json
(GUI client): one markdown table per block, the 11-01 columns (frames, gaps, drops, tracking ms, the accuracy in nm
raw / reference-corrected for the focus, stage and magnet holds, the per-hold noise, lost bead-frames, follow ms,
overshoot) plus the hold's moves per run (from the run file's "hold" marks).

  py tools/rig_bench_1107_report.py [DATA_PREFIX]      -> markdown on stdout (default G:\\l2s_rig_data\\2026-11-07_)
"""
import glob
import json
import os
import sys

import h5py

PREFIX = sys.argv[1] if len(sys.argv) > 1 else r"G:\l2s_rig_data\2026-11-07_"


def f0(v):
    return "-" if v is None else f"{v:.0f}"


def acc_cols(a):
    if not a:
        return ["-"] * 10
    pairs = [f"{f0(a[k][0])} / {f0(a[k][1])}" for k in ("focus_raw_nm", "focus_ref_nm", "stage_raw_nm", "stage_ref_nm",
                                                       "magnet_raw_nm", "magnet_ref_nm")]
    return [*pairs, f0(a.get("noise_nm")), str(a.get("lost", "-")), f"{f0(a['follow_ms'][0])} / {f0(a['follow_ms'][1])}",
            f0((a.get("overshoot_nm") or [None])[0])]


def hold_moves(h5):
    """'stage dx dy um; focus dz um' from the run's hold marks, or '-'."""
    try:
        with h5py.File(h5, "r") as f:
            if "events/mark" not in f:
                return "-"
            texts = [json.loads(d).get("text", "") for d in f["events/mark"]["data"][:]]
    except OSError:
        return "?"
    moves = [t.split(" (")[0].replace("hold ", "") for t in texts if t.startswith("hold")]
    return "; ".join(moves) if moves else "none"


HEAD = ("| run | fps | beads | z method | exec | frames | gaps | drops | track ms p50/p99/max | focus raw/ref nm | "
        "stage raw/ref | magnet raw/ref | noise nm | lost | follow ms | overshoot nm | hold moves |")
SEP = "|" + "---|" * 17


def script_rows(folder, rep):
    for r in rep.get("runs", []):
        if "error" in r:
            yield f"| {r['name']} | {r.get('fps', '')} | {r.get('beads', '')} | {r.get('z_method', '')} | | FAILED: {r['error'][:60]} |"
            continue
        ex = r["name"].split("_")[-1].replace("r", "") if r["name"].endswith("_r") else r["name"].split("_")[-1]
        cols = [r["name"], f"{r['fps']:.0f}", str(r["beads"]), r["z_method"], ex, str(r["frames_tracked"]),
                str(r["camera_gaps"]), str(r["pipeline_drops"]),
                f"{r['track_ms_p50']:.2f} / {r['track_ms_p99']:.2f} / {r['track_ms_max']:.2f}", *acc_cols(r.get("accuracy")),
                hold_moves(os.path.join(folder, r["name"] + ".h5"))]
        yield "| " + " | ".join(cols) + " |"


def gui_rows(folder, rep):
    for r in rep.get("runs", []):
        name = f"iso_{r['fps']:.0f}_{r['beads']}_{r['z_method']}_{'gpu' if r['gpu'] else 'numba'}_{r['condition']}"
        cols = [name, f"{r['fps']:.0f}", str(r["beads"]), r["z_method"], "gpu" if r["gpu"] else "numba", str(r["frames"]),
                str(r["gaps"]), str(r["drops"]), f"{r['track_p50']:.2f} / {r['track_p99']:.2f} / {r['track_max']:.2f}",
                *acc_cols(r.get("accuracy")), hold_moves(os.path.join(folder, "runs", name + ".h5"))]
        yield "| " + " | ".join(cols) + " |"


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import rig_bench_1107  # sets rig_bench_matrix.BLOCKS; folders set aside (_failed_bead5 ...) are skipped
    blocks = {name for name, _, _ in rig_bench_1107.R.BLOCKS}
    for folder in sorted(glob.glob(PREFIX + "*")):
        block = folder[len(PREFIX):]
        if block not in blocks:
            continue
        for fn, rows in (("report.json", script_rows), ("isolate.json", gui_rows)):
            p = os.path.join(folder, fn)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                rep = json.load(f)
            print(f"\n### {block} ({rep.get('date', '')}; {len(rep.get('runs', []))} runs"
                  + (f"; error: {rep['error'][:80]}" if rep.get("error") else "") + ")\n")
            print(HEAD)
            print(SEP)
            for line in rows(folder, rep):
                print(line)


if __name__ == "__main__":
    main()
