"""The offline numeric comparison of decision 0030: the same recorded frames (the replay fixture of the tests: the
2026-09-06 run, the LabVIEW reference positions as the start of every frame) through the reference - current_v1 on
numba FP64, the LabVIEW numbers - and every other method / executor / precision; per variant the LUT index jump
rate (frames whose slice index differs from the reference's), the z and xy difference distributions and the time
per frame. No rig, no device: the first gate before a variant goes to the bench.

  py tools/offline_compare.py [--stride N] [--gpu] [--json OUT]     (stride 20: ~every 20th reference frame)

Variants: every z method of track.Z_METHODS on numba fp64 and, with --gpu, on cuda fp64 and cuda fp32.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from conftest import FIXTURE, load_harness_inputs, load_reference, need, read_image

from mtpy.fast import FastKernel
from mtpy.track import Z_METHODS, lv_round

CROSS = 120


def frames(rows, stride):
    """(image, xin, yin, good) per compared frame: the LabVIEW reference's previous positions start every frame."""
    out = []
    for k in range(1, len(rows), stride):
        prev, row = rows[k - 1], rows[k]
        if any(v == -1.0 for v in prev["ff"]):
            continue
        st = np.array(prev["ff"]).reshape(-1, 3)
        out.append((read_image(row["frame"]).astype(np.uint8), [lv_round(v) for v in st[:, 0]],
                    [lv_round(v) for v in st[:, 1]], list(prev["good"])))
    return out


def run(kernel, data):
    xyz, idx, ms = [], [], []
    for img, xin, yin, good in data:
        t0 = time.perf_counter()
        a = kernel.track(img, xin, yin, good)
        ms.append((time.perf_counter() - t0) * 1e3)
        xyz.append(a[0])
        idx.append(a[1])
    return np.array(xyz), np.array(idx), np.array(ms[1:])          # the first call compiles / warms up


def compare(ref, out, zstep_um):
    """Against the reference: index jumps (bead-frames whose slice differs), |dz| and |dxy| distributions."""
    rx, ri = ref
    ox, oi = out
    live = (rx[:, :, 2] != -1.0) & (ox[:, :, 2] != -1.0)
    jumps = (ri != oi) & live
    dz = np.abs(ox[:, :, 2] - rx[:, :, 2])[live] * 1000.0
    dxy = np.hypot(ox[:, :, 0] - rx[:, :, 0], ox[:, :, 1] - rx[:, :, 1])[live]
    lost_diff = int(((rx[:, :, 2] == -1.0) != (ox[:, :, 2] == -1.0)).sum())
    return {"bead_frames": int(live.sum()), "index_jumps": int(jumps.sum()),
            "index_jump_pct": float(100.0 * jumps.sum() / max(1, live.sum())),
            "dz_nm_median": float(np.median(dz)) if dz.size else None,
            "dz_nm_p99": float(np.percentile(dz, 99)) if dz.size else None,
            "dz_nm_max": float(dz.max()) if dz.size else None,
            "dz_nm_at_jumps_median": float(np.median(np.abs(ox[:, :, 2] - rx[:, :, 2])[jumps] * 1000.0)) if jumps.any() else None,
            "dxy_px_max": float(dxy.max()) if dxy.size else None, "lost_flag_differences": lost_diff}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=20)
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    need(FIXTURE / "cal002")
    win_rs, win_h, cals = load_harness_inputs()
    data = frames(load_reference(), a.stride)
    zstep = float(cals[0]["z_step"])
    print(f"{len(data)} frames, {len(cals)} beads, stride {a.stride}; z step {zstep * 1000:.0f} nm")
    variants = [(zm, "numba", "fp64", lambda zm=zm: FastKernel(CROSS, win_rs, win_h, cals, z_method=zm)) for zm in Z_METHODS]
    if a.gpu:
        from mtpy.gpu import GpuKernel, GpuKernel32
        variants += [(zm, "cuda", "fp64", lambda zm=zm: GpuKernel(CROSS, win_rs, win_h, cals, z_method=zm)) for zm in Z_METHODS]
        variants += [(zm, "cuda", "fp32", lambda zm=zm: GpuKernel32(CROSS, win_rs, win_h, cals, z_method=zm)) for zm in Z_METHODS]
    ref_xyz, ref_idx, _ = run(FastKernel(CROSS, win_rs, win_h, cals, z_method="current_v1"), data)
    rows = []
    print(f"{'z method':16s} {'exec':6s} {'prec':5s} {'ms p50':>7s} {'p99':>6s} {'max':>6s} | jumps %  dz nm median / p99 / max  at jumps  dxy px max  lost diff")
    for zm, ex, prec, make in variants:
        xyz, idx, ms = run(make(), data)
        c = compare((ref_xyz, ref_idx), (xyz, idx), zstep)
        row = {"z_method": zm, "executor": ex, "precision": prec, "ms_p50": float(np.median(ms)),
               "ms_p99": float(np.percentile(ms, 99)), "ms_max": float(ms.max()), **c}
        rows.append(row)
        f = lambda v: "-" if v is None else f"{v:.2f}"
        print(f"{zm:16s} {ex:6s} {prec:5s} {row['ms_p50']:7.2f} {row['ms_p99']:6.2f} {row['ms_max']:6.2f} | "
              f"{c['index_jump_pct']:6.2f}  {f(c['dz_nm_median'])} / {f(c['dz_nm_p99'])} / {f(c['dz_nm_max'])}  "
              f"{f(c['dz_nm_at_jumps_median'])}  {f(c['dxy_px_max'])}  {c['lost_flag_differences']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"frames": len(data), "beads": len(cals), "stride": a.stride,
                                            "reference": "current_v1 numba fp64", "rows": rows}, indent=1), encoding="utf-8")
        print("->", a.json)


if __name__ == "__main__":
    main()
