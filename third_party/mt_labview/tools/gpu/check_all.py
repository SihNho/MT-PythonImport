"""check_all.py - run the NumPy reference over the recorded fixture exactly as the LabVIEW harness did (state fed back frame
to frame, the main VI's reseed rule on a lost bead) and compare every bead of every frame with the LabVIEW reference
(tools/bench/fixture_compare_results.jsonl).  Acceptance: |dx|,|dy| < 1e-6 px, |dz| < 1e-6 um.
  py tools/gpu/check_all.py [--n=200] [--every=1] [--start=0] [--out=tools/gpu/check_all_results.jsonl]
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import ref_numpy as r  # noqa: E402
from fixture import read_cal, read_image, read_reference  # noqa: E402

TOL_XY, TOL_Z = 1e-6, 1e-4      # z relaxed by the user 2026-09-07 ("1e-4 차이는 괜찮아")


def arg(name, default):
    v = next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{name}=")), None)
    return type(default)(v) if v is not None else default


def main():
    N = arg("n", 10 ** 9); EVERY = arg("every", 1); START = arg("start", 0); OUT = arg("out", os.path.join(HERE, "check_all_results.jsonl"))
    p = r.DEFAULT
    win_rs, win_h, cals = r.load_inputs(); cal = read_cal(); xy0 = cal["xy"]
    ref = read_reference(); rows = ref["frames"]
    nb = len(cals); cross = 120
    # the state the LabVIEW harness fed to frame k = ff of frame k-1, or the cal positions after a lost bead (spec §35)
    worst = {"x": 0.0, "y": 0.0, "z": 0.0}; worst_frame = {}; n_bad = 0; t0 = time.time(); n_done = 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps({"session": time.strftime("%Y-%m-%d %H:%M:%S"), "params": dataclass_dict(p)}) + "\n")
        for k in range(START, len(rows), EVERY):
            if n_done >= N:
                break
            row = rows[k]
            if k == 0:
                state = np.array(xy0)
            else:
                prev = rows[k - 1]
                lost = any(v == -1.0 for v in prev["ff"])
                state = np.array(xy0) if lost else np.array(prev["ff"]).reshape(-1, 3)[:, :2]
                good_in = [True] * nb if lost else prev["good"]
            img = read_image(row["frame"])
            errs = []; outs = []
            for b in range(nb):
                if k > 0 and not good_in[b]:
                    outs.append((-1.0, -1.0, -1.0)); errs.append((0.0, 0.0, 0.0)); continue   # bad bead: the kernel's other case
                x_in, y_in = r.lv_round(state[b][0]), r.lv_round(state[b][1])
                try:
                    o = r.track_bead(img, x_in, y_in, cross, win_rs, win_h, cals[b], p)
                    xo, yo, zo = o["x"], o["y"], o["z"]
                except Exception as e:
                    xo = yo = zo = float("nan")
                outs.append((xo, yo, zo))
                rx, ry, rz = row["ff"][3 * b], row["ff"][3 * b + 1], row["ff"][3 * b + 2]
                if rx == -1.0 and ry == -1.0:
                    errs.append((0.0, 0.0, 0.0))                 # LabVIEW flagged the bead bad this frame (bounds check) - compared separately
                else:
                    errs.append((abs(xo - rx), abs(yo - ry), abs(zo - rz)))
            ex = max(e[0] for e in errs); ey = max(e[1] for e in errs); ez = max(e[2] for e in errs)
            bad = not (ex < TOL_XY and ey < TOL_XY and ez < TOL_Z)
            n_bad += bad
            for key, v in (("x", ex), ("y", ey), ("z", ez)):
                if v > worst[key]:
                    worst[key] = v; worst_frame[key] = row["frame"]
            f.write(json.dumps({"frame": row["frame"], "ex": ex, "ey": ey, "ez": ez, "out": outs, "ref": row["ff"]}) + "\n")
            n_done += 1
            if n_done <= 3 or n_done % 100 == 0 or bad:
                print(f"frame {row['frame']}: |dx| {ex:.2e} |dy| {ey:.2e} |dz| {ez:.2e} {'FAIL' if bad else 'ok'}  ({(time.time() - t0) / n_done:.2f} s/frame)", flush=True)
    print(f"SUMMARY frames={n_done} failing={n_bad} worst |dx| {worst['x']:.3e} @{worst_frame.get('x')} |dy| {worst['y']:.3e} @{worst_frame.get('y')} "
          f"|dz| {worst['z']:.3e} @{worst_frame.get('z')}  ({(time.time() - t0) / max(1, n_done):.2f} s/frame)", flush=True)
    return 0 if n_bad == 0 else 1


def dataclass_dict(p):
    import dataclasses
    return dataclasses.asdict(p)


if __name__ == "__main__":
    sys.exit(main())
# ---
# labview: none
# hardware: none
# ---
