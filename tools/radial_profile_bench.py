# labview: none
# hardware: none
"""Radial-profile bench (2026-10-24, owner asked for it): does a different RADIAL PROFILE stage reduce the XY->Z
crosstalk of the current tracker? Offline only: images rendered from the fixture's own calibration profiles, and a
replay of the recorded fixture. No device is opened.

Candidate radial stages (same signature as track.radial_current, swapped in via dataclasses.replace(T.CURRENT, ...)):
  current   : the program's two-bin linear split of each pixel's radius (track.radial_profile).
  polar1    : QI-style polar resampling, bilinear interpolation, radial step 1 px, angular step <= 0.5 px of arc.
  polar3    : same, radial step 1/3 px, reduced to the 60 integer bins with the same triangular (two-bin) weights.
  area4     : pixel-area weighting: each pixel is split into 4 x 4 sub-samples, each sub-sample's radius is split
              linearly between two bins like the current method.
The XY and Z stages stay the current ones.

The look-up table (LUT) was built with the current radial stage, so every variant gets its own LUT: the calibration
images are rendered at the calibration's own 60 slices (same rendering and source-profile pre-compensation as
tools/xy_passes_bench.py, sub-pixel offset (0.3, 0.6)), each variant's profile of each image is mirrored into a stack
and prepared with calib.prep_bead using the bead's own (LOW, HIGH, forget). 'current' is run twice: with the
program's own LUT (must reproduce the 2026-10-22 numbers) and with the rendered LUT (the fair control).

  synthetic : S2 crosstalk (20 x 20 sub-pixel grid at slices 15, 30, 45), S3 z interpolation (slice 3..56 in 0.05
              steps at the LUT offset (0.3, 0.6) and at (0.8, 0.1)), S4 noise (sigma 1.66, 200 images at 3 offsets),
              time per call.
  replay    : bead 1 (reference bead) of the recorded fixture, all frames, with each variant and its rendered LUT.

Usage: .venv/Scripts/python tools/radial_profile_bench.py synthetic|s2float|s2noise|replay [--out=DIR]
"""
import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import FIXTURE, load_harness_inputs, read_image
from xy_passes_bench import NOISE_SIGMA, render, source_profile, to_8bit

from mtpy import calib
from mtpy import track as T
from mtpy.lvfiles import read_cal

CROSS = 120
HALF = CROSS // 2
LUT_OFF = (0.3, 0.6)          # sub-pixel offset of the rendered calibration images (= the pre-compensation offset)
BASE = 160.0


# ------------------------------------------------------------------------------------------ radial variants ---
def _polar_tables(dr, arc=0.5, half=HALF):
    """Sample offsets (dx, dy) on rings r = 0, dr, 2 dr, ... < half - 1 + 1e-9, each ring with n = max(8, ceil(2 pi r /
    arc)) angles, and the (half, n_samples) weight matrix that reduces them to integer bins with triangular weights
    w = max(0, 1 - |r - k|) (for dr = 1 this is the identity per ring), normalised per bin."""
    rs = np.arange(0.0, half - 1 + 1e-9, dr)
    dx, dy, rr, inv_n = [], [], [], []
    for r in rs:
        n = 1 if r == 0 else max(8, int(np.ceil(2 * np.pi * r / arc)))
        th = 2 * np.pi * (np.arange(n) + 0.5) / n
        dx.append(r * np.cos(th)); dy.append(r * np.sin(th)); rr.append(np.full(n, r))
        inv_n.append(np.full(n, 1.0 / n))          # each ring is one sample of I(r), whatever its number of angles
    dx, dy, rr, inv_n = (np.concatenate(a) for a in (dx, dy, rr, inv_n))
    k = np.arange(half)[:, None]
    W = np.clip(1 - np.abs(rr[None, :] - k), 0, None) * inv_n[None, :]
    W /= W.sum(axis=1, keepdims=True)
    return dx, dy, W


def make_polar(dr):
    dx, dy, W = _polar_tables(dr)

    def radial_polar(sub, xc, yc, half, p):
        x = xc + dx
        y = yc + dy
        x0 = np.floor(x).astype(int); y0 = np.floor(y).astype(int)
        fx = x - x0; fy = y - y0
        s = sub.astype(np.float64)
        v = ((1 - fy) * ((1 - fx) * s[y0, x0] + fx * s[y0, x0 + 1])
             + fy * ((1 - fx) * s[y0 + 1, x0] + fx * s[y0 + 1, x0 + 1]))
        return W @ v
    return radial_polar


def make_area(ss=4):
    o = (np.arange(ss) + 0.5) / ss - 0.5                 # sub-sample offsets within a pixel centred on its index

    def radial_area(sub, xc, yc, half, p):
        n = 2 * half + 2
        x0 = int(np.floor(xc)) - half - 1
        y0 = int(np.floor(yc)) - half - 1
        win = sub[y0:y0 + n, x0:x0 + n].astype(np.float64)
        X = (np.arange(n)[None, :, None, None] + x0 + o[None, None, None, :]) - xc
        Y = (np.arange(n)[:, None, None, None] + y0 + o[None, None, :, None]) - yc
        r = np.sqrt(X * X + Y * Y).ravel()
        pv = np.broadcast_to(win[:, :, None, None], (n, n, ss, ss)).ravel()
        rf = np.floor(r).astype(int)
        fr = r - rf
        ok0 = rf < half
        ok1 = rf + 1 < half
        s = (np.bincount(rf[ok0], (1 - fr[ok0]) * pv[ok0], half)
             + np.bincount(rf[ok1] + 1, fr[ok1] * pv[ok1], half))
        w = np.bincount(rf[ok0], 1 - fr[ok0], half) + np.bincount(rf[ok1] + 1, fr[ok1], half)
        return s / w
    return radial_area


RADIALS = {"current": T.radial_current, "polar1": make_polar(1.0), "polar3": make_polar(1 / 3), "area4": make_area(4)}


# ------------------------------------------------------------------------------------------------------ LUTs ---
def compensated_sources(profs, beads):
    """Source profiles (all slices) whose rendering re-binned by the CURRENT radial stage reproduces the calibration."""
    src = np.zeros_like(profs)
    resid = []
    for b in beads:
        for s in range(profs.shape[1]):
            src[b, s], r = source_profile(profs[b, s], *LUT_OFF)
            resid.append(r)
    return src, float(max(resid))


def rendered_lut(src_b, radial, cal_i32, z_step):
    """LUT of one bead for a radial stage: render each slice at LUT_OFF, profile with `radial`, mirror, prep_bead."""
    rows = []
    for s in range(len(src_b)):
        cx, cy = BASE + LUT_OFF[0], BASE + LUT_OFF[1]
        img = render(src_b[s], cx + 0.5, cy + 0.5)
        h = T.lv_round(CROSS * T.DEFAULT.k_half)
        sub = T.sub_image(img, T.lv_round(cx), T.lv_round(cy), h)
        prof = radial(sub, h + cx - T.lv_round(cx), h + cy - T.lv_round(cy), HALF, T.DEFAULT)
        rows.append(np.concatenate([prof[1:][::-1], prof]))
    lo, hi, fg = (int(v) for v in cal_i32)
    return calib.prep_bead(np.array(rows), lo, hi, fg, z_step, CROSS)


def build_variants(profs_src, cal, cals_orig, beads):
    """{name: (stages, [cal per bead])}; 'current_origLUT' uses the program's own LUT."""
    out = {"current_origLUT": (T.CURRENT, cals_orig)}
    for name, rad in RADIALS.items():
        luts = [rendered_lut(profs_src[b], rad, cal["bead_i32"][b], cal["z_step"]) if b in beads else None
                for b in range(len(cals_orig))]
        out[name] = (dataclasses.replace(T.CURRENT, radial=rad), luts)
    return out


def track_one(img, cx, cy, win_rs, win_h, cal, stages):
    x, y, z, _, good = T.track_bead(img, T.lv_round(cx), T.lv_round(cy), CROSS, win_rs, win_h, cal, stages=stages)
    return x, y, z / float(cal["z_step"]), good


# --------------------------------------------------------------------------------------------------- synthetic ---
def synthetic(out):
    win_rs, win_h, cals = load_harness_inputs()
    cal = read_cal(FIXTURE / "cal002")
    profs = cal["stack"][:, :, HALF - 1:]                 # n x S x 60
    S = profs.shape[1]
    beads = (0, 1)
    t0 = time.time()
    src, resid = compensated_sources(profs, beads)
    print(f"sources {time.time() - t0:.0f} s, max residual {resid:.4f} grey", flush=True)
    V = build_variants(src, cal, cals, beads)
    names = list(V)
    lut_dev = {n: [float(np.abs(V[n][1][b]["real"] - cals[b]["real"]).max()) for b in beads] for n in names}
    print(f"LUTs {time.time() - t0:.0f} s; max |real - program LUT|: {lut_dev}", flush=True)
    res = {"noise_sigma": NOISE_SIGMA, "lut_offset": LUT_OFF, "compensation_resid_max_grey": resid,
           "lut_max_abs_diff_vs_program": lut_dev, "variants": names}

    # S2: crosstalk at three slices, 20 x 20 grid, no noise
    offs = np.arange(0.0, 1.0, 0.05)
    s2 = {}
    for b in beads:
        for sl in (15, 30, 45):
            E = {n: np.zeros((len(offs), len(offs))) for n in names}
            for iy, dy in enumerate(offs):
                for ix, dx in enumerate(offs):
                    cx, cy = BASE + dx, BASE + dy
                    img = to_8bit(render(src[b, sl], cx + 0.5, cy + 0.5))
                    for n in names:
                        E[n][iy, ix] = track_one(img, cx, cy, win_rs, win_h, V[n][1][b], V[n][0])[2] - sl
            for n in names:
                e = E[n] * 100
                s2.setdefault(n, {})[f"bead{b + 1}_s{sl}"] = {"p2p_nm": float(np.ptp(e)), "sd_nm": float(e.std()),
                                                               "mean_nm": float(e.mean())}
            print(f"S2 bead {b + 1} slice {sl}  {time.time() - t0:.0f} s: " +
                  ", ".join(f"{n} {s2[n][f'bead{b + 1}_s{sl}']['p2p_nm']:.2f}" for n in names), flush=True)
    res["S2"] = s2

    # S3: interpolation over heights at the LUT offset and at another offset (linear blend between slices)
    s3 = {}
    for off, step in ((LUT_OFF, 0.05), ((0.8, 0.1), 0.1)):
        zs = np.arange(3.0, S - 4.0 + 1e-9, step)
        for b in beads:
            err = {n: [] for n in names}
            for zt in zs:
                s0 = int(np.floor(zt)); w = zt - s0
                prof = (1 - w) * src[b, s0] + w * src[b, min(s0 + 1, S - 1)]
                cx, cy = BASE + off[0], BASE + off[1]
                img = to_8bit(render(prof, cx + 0.5, cy + 0.5))
                for n in names:
                    err[n].append(track_one(img, cx, cy, win_rs, win_h, V[n][1][b], V[n][0])[2] - zt)
            for n in names:
                e = np.array(err[n]) * 100
                s3.setdefault(n, {})[f"bead{b + 1}_off{off[0]}_{off[1]}"] = {
                    "rms_nm": float(np.sqrt((e ** 2).mean())), "rms_about_mean_nm": float(e.std()),
                    "mean_nm": float(e.mean()), "max_abs_nm": float(np.abs(e).max())}
            print(f"S3 bead {b + 1} off {off}  {time.time() - t0:.0f} s: " +
                  ", ".join(f"{n} {s3[n][f'bead{b + 1}_off{off[0]}_{off[1]}']['rms_nm']:.2f}" for n in names), flush=True)
    res["S3"] = s3

    # S4: noise at slice 30, 200 realisations per offset; the same noisy images for every variant
    rng = np.random.default_rng(20261024)
    s4 = {}
    for b in beads:
        for d in (0.0, 0.25, 0.5):
            cx, cy = BASE + d, BASE + d
            clean = render(src[b, 30], cx + 0.5, cy + 0.5)
            zz = {n: [] for n in names}
            for _ in range(200):
                img = to_8bit(clean, rng, NOISE_SIGMA)
                for n in names:
                    zz[n].append(track_one(img, cx, cy, win_rs, win_h, V[n][1][b], V[n][0])[2])
            for n in names:
                z = np.array(zz[n])
                s4.setdefault(n, {})[f"bead{b + 1}_d{d}"] = {"z_sd_nm": float(z.std() * 100),
                                                             "z_bias_nm": float((z.mean() - 30) * 100)}
        print(f"S4 bead {b + 1}  {time.time() - t0:.0f} s: " +
              ", ".join(f"{n} {np.mean([v['z_sd_nm'] for k, v in s4[n].items() if k.startswith(f'bead{b + 1}')]):.2f}"
                        for n in names), flush=True)
    res["S4"] = s4

    # time per call (radial stage alone and the whole bead), numpy
    img = to_8bit(render(src[0, 30], BASE + 0.3 + 0.5, BASE + 0.6 + 0.5))
    h = T.lv_round(CROSS * T.DEFAULT.k_half)
    sub = T.sub_image(img, 160, 161, h)
    tm = {}
    for n in names:
        rad = V[n][0].radial
        reps = 200
        t1 = time.perf_counter()
        for _ in range(reps):
            rad(sub, h + 0.3, h + 0.6 - 1, HALF, T.DEFAULT)
        t_rad = (time.perf_counter() - t1) / reps
        t1 = time.perf_counter()
        for _ in range(reps):
            track_one(img, BASE + 0.3, BASE + 0.6, win_rs, win_h, V[n][1][0], V[n][0])
        tm[n] = {"radial_ms": t_rad * 1e3, "bead_ms": (time.perf_counter() - t1) / reps * 1e3}
    res["time"] = tm
    (out / "synthetic_summary.json").write_text(json.dumps(res, indent=1))
    for n in names:
        print(f"{n}: S2 p2p " + " ".join(f"{k} {v['p2p_nm']:.2f}" for k, v in s2[n].items())
              + " | S3 rms " + " ".join(f"{v['rms_nm']:.2f}" for v in s3[n].values())
              + " | S4 sd " + " ".join(f"{v['z_sd_nm']:.2f}" for v in s4[n].values())
              + f" | {tm[n]['radial_ms']:.2f} / {tm[n]['bead_ms']:.2f} ms")
    return {"S2_p2p_s30_nm": {n: [s2[n]["bead1_s30"]["p2p_nm"], s2[n]["bead2_s30"]["p2p_nm"]] for n in names}}


def s2float(out):
    """S2 at slice 30 WITHOUT 8-bit rounding: how much of the crosstalk is the radial stage and how much is rounding."""
    win_rs, win_h, cals = load_harness_inputs()
    cal = read_cal(FIXTURE / "cal002")
    profs = cal["stack"][:, :, HALF - 1:]
    beads = (0, 1)
    src, _ = compensated_sources(profs, beads)
    V = build_variants(src, cal, cals, beads)
    offs = np.arange(0.0, 1.0, 0.05)
    res = {}
    for b in beads:
        E = {n: np.zeros((len(offs), len(offs))) for n in V}
        for iy, dy in enumerate(offs):
            for ix, dx in enumerate(offs):
                cx, cy = BASE + dx, BASE + dy
                img = render(src[b, 30], cx + 0.5, cy + 0.5)          # float image, no rounding
                for n in V:
                    E[n][iy, ix] = track_one(img, cx, cy, win_rs, win_h, V[n][1][b], V[n][0])[2] - 30
        for n in V:
            res.setdefault(n, {})[f"bead{b + 1}_s30"] = {"p2p_nm": float(np.ptp(E[n]) * 100),
                                                          "sd_nm": float(E[n].std() * 100)}
        print(f"S2 no rounding bead {b + 1}: " + ", ".join(f"{n} {res[n][f'bead{b + 1}_s30']['p2p_nm']:.2f}" for n in V),
              flush=True)
    (out / "s2float_summary.json").write_text(json.dumps(res, indent=1))
    return {n: [v["p2p_nm"] for v in r.values()] for n, r in res.items()}


def s2noise(out, reps=100):
    """S2 at slice 30 WITH noise (sigma 1.66) and 8-bit rounding: mean z over `reps` noisy images at each point of a
    5 x 5 sub-pixel grid. Real images carry noise, which dithers the rounding; this is the systematic crosstalk a
    real bead would see. sd_corr removes the noise of the means (var(means) - mean(var)/reps)."""
    win_rs, win_h, cals = load_harness_inputs()
    cal = read_cal(FIXTURE / "cal002")
    profs = cal["stack"][:, :, HALF - 1:]
    beads = (0, 1)
    src, _ = compensated_sources(profs, beads)
    V = build_variants(src, cal, cals, beads)
    offs = np.arange(0.0, 1.0, 0.2)
    rng = np.random.default_rng(20261025)
    res = {}
    for b in beads:
        M = {n: np.zeros((len(offs), len(offs))) for n in V}
        Q = {n: np.zeros((len(offs), len(offs))) for n in V}
        for iy, dy in enumerate(offs):
            for ix, dx in enumerate(offs):
                cx, cy = BASE + dx, BASE + dy
                clean = render(src[b, 30], cx + 0.5, cy + 0.5)
                zz = {n: [] for n in V}
                for _ in range(reps):
                    img = to_8bit(clean, rng, NOISE_SIGMA)
                    for n in V:
                        zz[n].append(track_one(img, cx, cy, win_rs, win_h, V[n][1][b], V[n][0])[2])
                for n in V:
                    z = np.array(zz[n]) * 100
                    M[n][iy, ix] = z.mean()
                    Q[n][iy, ix] = z.var()
        for n in V:
            v = M[n].var() - Q[n].mean() / reps
            res.setdefault(n, {})[f"bead{b + 1}_s30"] = {
                "p2p_of_means_nm": float(np.ptp(M[n])), "sd_of_means_nm": float(M[n].std()),
                "sd_corr_nm": float(np.sqrt(max(v, 0.0))), "se_of_one_mean_nm": float(np.sqrt(Q[n].mean() / reps))}
        print(f"S2 with noise bead {b + 1}: " + ", ".join(
            f"{n} p2p {res[n][f'bead{b + 1}_s30']['p2p_of_means_nm']:.2f} sd_corr {res[n][f'bead{b + 1}_s30']['sd_corr_nm']:.2f}"
            for n in V), flush=True)
    (out / "s2noise_summary.json").write_text(json.dumps(res, indent=1))
    return {n: [v["sd_corr_nm"] for v in r.values()] for n, r in res.items()}


# ------------------------------------------------------------------------------------------------------ replay ---
def replay(out):
    """Bead 1 (reference bead) of the recorded fixture with every variant; LUTs rendered from cal002's bead-1 profiles."""
    win_rs, win_h, cals = load_harness_inputs()
    cal = read_cal(FIXTURE / "cal002")
    profs = cal["stack"][:, :, HALF - 1:]
    src, resid = compensated_sources(profs, (0,))
    V = build_variants(src, cal, cals, (0,))
    frames = sorted(int(p.stem[3:]) for p in FIXTURE.glob("img*.tif"))
    names = list(V)
    trk = {n: T.Tracker(cal["xy"][:1], CROSS, win_rs, win_h, V[n][1][:1], stages=V[n][0]) for n in names}
    R = {n: np.zeros((len(frames), 3)) for n in names}
    t0 = time.time()
    for k, f in enumerate(frames):
        img = read_image(f)
        for n in names:
            R[n][k] = trk[n].step(img)[0]
        if k % 2000 == 0:
            print(f"frame {k}/{len(frames)}  {time.time() - t0:.0f} s", flush=True)
    summ = {"frames": len(frames)}
    ref = R["current_origLUT"][:, 2]
    for n in names:
        z = R[n][:, 2]
        ok = (z != -1.0) & (ref != -1.0)
        d = (z[ok] - ref[ok]) * 1e3
        summ[n] = {"good": int(ok.sum()), "f2f_z_nm": float(np.std(np.diff(z[ok])) / np.sqrt(2) * 1e3),
                   "z_sd_nm": float(z[ok].std() * 1e3), "mean_z_um": float(z[ok].mean()),
                   "vs_origLUT_mean_nm": float(d.mean()), "vs_origLUT_rms_about_mean_nm": float(d.std())}
        print(f"{n}: {summ[n]}", flush=True)
    (out / "replay_summary.json").write_text(json.dumps(summ, indent=1))
    return {n: summ[n]["f2f_z_nm"] for n in names}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "synthetic"
    out = Path(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), "bench_out/radial_profile"))
    out.mkdir(parents=True, exist_ok=True)
    r = {"synthetic": synthetic, "s2float": s2float, "s2noise": s2noise, "replay": replay}[mode](out)
    print("RESULT " + json.dumps({"ok": True, "mode": mode, "out": str(out), "summary": r}))
