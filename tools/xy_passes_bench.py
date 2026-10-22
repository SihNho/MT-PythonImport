"""Bench A + B (2026-10-22, owner: "A와 B부터"): how much do the current XY method's extra passes buy, and what are its
pixel bias, XY-Z crosstalk and Z interpolation error? Offline only: recorded fixture + images rendered from the
fixture's own calibration profiles. No device is opened.

The current XY step fits a parabola 3 times per axis (P1, then two phase-shifted passes; decision 0003). Variants:
  passes=1 : result = P1                (no discretization removal)
  passes=2 : result = P1 + out1
  passes=3 : result = P1 + out1 + out2  (the current method; must equal track.find_avg_profile_center)

  replay    : track all recorded frames with each variant (each feeds its own output forward, like the program);
              per bead: frame-to-frame noise, Allan deviation, difference to passes=3, sub-pixel histogram.
  synthetic : beads rendered from cal002's raw radial profiles at known sub-pixel / sub-slice positions.
              S1 XY bias map, S2 XY->Z crosstalk, S3 Z interpolation error (profiles between slices are a LINEAR
              blend of the two neighbouring slices - a model, stated in the results), S4 noise (sigma 1.66 grey levels,
              measured on the reference bead's patch over 36 frames), all with 8-bit rounding.

Usage: .venv/Scripts/python tools/xy_passes_bench.py replay|synthetic [--out DIR]
"""
import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from conftest import FIXTURE, load_harness_inputs, read_image

from mtpy import track as T
from mtpy.lvfiles import read_cal

CROSS = 120
PASSES = (1, 2, 3)
NOISE_SIGMA = 1.66          # grey levels, reference-bead patch, frames 4..43 (measured 2026-10-22)


# ------------------------------------------------------------------------------------------- XY variant stage ---
def center_passes(profile, window_h, start, half, n_pts, frame2_shifted, passes):
    """track.find_avg_profile_center with the number of parabola passes as a parameter (3 = identical)."""
    cross = 2 * half
    F = np.fft.fft(profile) * window_h
    F2 = F * F
    k = 2 * np.pi / cross
    i = np.arange(cross)
    a = np.where(i > half, i - cross, i).astype(np.float64)

    def corr(S):
        return np.roll(np.abs(np.fft.ifft(S)), half)

    def shift(S, d):
        return np.abs(S) * np.exp(1j * (np.angle(S) + k * d * a))

    P1 = T.fit_parabola(corr(F2), n_pts)
    res = P1
    if passes >= 2:
        r1 = T.lv_round(P1)
        G1 = shift(F2, P1 - r1)
        out1 = T.fit_parabola(corr(G1), n_pts) - r1
        res += out1
        if passes >= 3:
            G2 = shift(G1 if frame2_shifted else F2, out1)
            res += T.fit_parabola(corr(G2), n_pts) - r1
    sh = (res - half) / 2
    return start + sh, sh


def xy_stage(passes):
    def xy(sub, h, x_in, y_in, cross, win_rs, win_h, p):
        half = T.lv_i32_div(cross, 2)
        n_end = T.lv_i32_div(cross, p.k_end)
        ax, ay = T.average_xy_in_cross(sub, h, h, cross, p.arm, p.sgl_avg)
        px = T.prep_avg_profile(ax, cross, n_end, win_rs, p.end_quirk)
        py = T.prep_avg_profile(ay, cross, n_end, win_rs, p.end_quirk)
        x, sx = center_passes(px, win_h, x_in, half, p.n_pts, p.frame2_shifted, passes)
        y, sy = center_passes(py, win_h, y_in, half, p.n_pts, p.frame2_shifted, passes)
        return x, y, sx, sy
    return xy


STAGES = {n: dataclasses.replace(T.CURRENT, xy=xy_stage(n)) for n in PASSES}


# ----------------------------------------------------------------------------------------------------- metrics ---
def f2f_noise(v):
    """Frame-to-frame noise: std of successive differences / sqrt 2."""
    return float(np.std(np.diff(v)) / np.sqrt(2))


def allan_dev(v, taus):
    """Overlapping Allan deviation of a position trace at averaging times tau (frames)."""
    out = []
    c = np.concatenate([[0.0], np.cumsum(v)])
    for m in taus:
        if 2 * m >= len(v):
            break
        avg = (c[m:] - c[:-m]) / m                       # running means of length m
        d = avg[m:] - avg[:-m]
        out.append(float(np.sqrt(0.5 * np.mean(d * d))))
    return out


def frac_flatness(v, bins=20):
    """Sub-pixel histogram of a moving bead (pixel locking shows as a non-flat histogram): max/min bin ratio and the
    chi-square per degree of freedom against a flat histogram."""
    h, _ = np.histogram(np.mod(v, 1.0), bins=bins, range=(0, 1))
    e = h.mean()
    return {"max_over_min": float(h.max() / max(h.min(), 1)), "chi2_dof": float(((h - e) ** 2 / e).sum() / (bins - 1)),
            "hist": h.tolist()}


# ------------------------------------------------------------------------------------------------------ replay ---
def replay(out):
    win_rs, win_h, cals = load_harness_inputs()
    cal = read_cal(FIXTURE / "cal002")
    frames = sorted(int(p.stem[3:]) for p in FIXTURE.glob("img*.tif"))
    trackers = {n: T.Tracker(cal["xy"], CROSS, win_rs, win_h, cals, stages=STAGES[n]) for n in PASSES}
    res = {n: np.zeros((len(frames), len(cals), 3)) for n in PASSES}
    t0 = time.time()
    for k, f in enumerate(frames):
        img = read_image(f)
        for n in PASSES:
            res[n][k] = trackers[n].step(img)
        if k % 1000 == 0:
            print(f"frame {k}/{len(frames)}  {time.time() - t0:.0f} s", flush=True)
    np.savez_compressed(out / "replay_xyz.npz", frames=np.array(frames), **{f"p{n}": res[n] for n in PASSES})
    taus = [2 ** j for j in range(14)]
    summary = {"frames": len(frames), "taus_frames": taus, "fps": 90, "beads": {}}
    for b in range(len(cals)):
        ok = np.all([(res[n][:, b, 0] != -1.0) for n in PASSES], axis=0)
        bd = {"good_frames": int(ok.sum())}
        for n in PASSES:
            x, y, z = (res[n][ok, b, j] for j in range(3))
            bd[f"p{n}"] = {
                "f2f_px": [f2f_noise(x), f2f_noise(y)], "f2f_z_nm": f2f_noise(z) * 1e3,
                "adev_x_px": allan_dev(x, taus), "adev_y_px": allan_dev(y, taus),
                "adev_z_nm": [v * 1e3 for v in allan_dev(z, taus)],
                "frac_x": frac_flatness(x), "frac_y": frac_flatness(y),
                "lost_flags": int((res[n][:, b, 0] == -1.0).sum())}
            if n != 3:
                d = res[n][ok, b] - res[3][ok, b]
                bd[f"p{n}"]["vs_p3"] = {"mean_px": d[:, :2].mean(0).tolist(), "rms_px": np.sqrt((d[:, :2] ** 2).mean(0)).tolist(),
                                        "max_px": np.abs(d[:, :2]).max(0).tolist(),
                                        "rms_z_nm": float(np.sqrt((d[:, 2] ** 2).mean()) * 1e3)}
        summary["beads"][b + 1] = bd
    (out / "replay_summary.json").write_text(json.dumps(summary, indent=1))
    for b, bd in summary["beads"].items():
        print(f"bead {b}: " + " | ".join(
            f"p{n} f2f x {bd[f'p{n}']['f2f_px'][0]:.5f} y {bd[f'p{n}']['f2f_px'][1]:.5f} px z {bd[f'p{n}']['f2f_z_nm']:.2f} nm"
            for n in PASSES))
    return summary


# --------------------------------------------------------------------------------------------------- synthetic ---
def render(prof, cx, cy, size=320, ss=3):
    """Bead image from a radial profile I(r) (index = radius in px) centred at (cx, cy) in pixel coordinates where pixel
    (i, j) covers [j, j+1) x [i, i+1); each pixel is the mean of ss x ss samples (pixel integration). Beyond the
    profile's last radius the value is the profile's last value (background)."""
    o = (np.arange(ss) + 0.5) / ss
    g = np.arange(size)
    X = (g[None, :, None, None] + o[None, None, None, :]) - cx
    Y = (g[:, None, None, None] + o[None, None, :, None]) - cy
    r = np.sqrt(X * X + Y * Y)
    return np.interp(r, np.arange(len(prof)), prof).mean(axis=(2, 3))


def source_profile(prof, fx, fy, iters=10, ss=3):
    """Rendering then re-binning blurs a profile (a 57 nm z offset at slice 30 if ignored). Find the source profile whose
    rendered image, re-binned by the tracker's own radial_profile around the true centre (sub-pixel offset fx, fy),
    reproduces `prof` (fixed-point iteration). Returns (source, rms residual in grey levels)."""
    half = len(prof)
    c = 160.0
    src = prof.copy()
    for _ in range(iters):
        img = render(src, c + fx + 0.5, c + fy + 0.5, ss=ss)
        sub = T.sub_image(img, int(c), int(c), 72)
        m = T.radial_profile(sub, 72 + fx, 72 + fy, half)
        d = np.where(np.isfinite(m), prof - m, 0.0)
        src = src + d
    return src, float(np.sqrt(np.mean(d * d)))


def to_8bit(img, rng=None, sigma=0.0):
    if rng is not None and sigma > 0:
        img = img + rng.normal(0.0, sigma, img.shape)
    return np.clip(np.rint(img), 0, 255)


def track_one(img, cx, cy, win_rs, win_h, cal, n):
    """Track from the integer start the program would have (the true centre rounded)."""
    x, y, z, _, good = T.track_bead(img, T.lv_round(cx), T.lv_round(cy), CROSS, win_rs, win_h, cal, stages=STAGES[n])
    return x, y, z / float(cal["z_step"]), good


def synthetic(out):
    win_rs, win_h, cals = load_harness_inputs()
    stack = read_cal(FIXTURE / "cal002")["stack"]          # n x S x 119, mirrored raw radial profiles
    half = CROSS // 2
    profs = stack[:, :, half - 1:]                          # n x S x 60, r = 0..59
    # Pixel centre convention: pixel (i, j) is centred at (j + 0.5, i + 0.5) in render(); the tracker's coordinates
    # are pixel indices, so a bead rendered at c_render sits at c_render - 0.5 in tracker coordinates.
    base = 160.0
    rng = np.random.default_rng(20261022)
    S = profs.shape[1]
    res = {"noise_sigma": NOISE_SIGMA, "beads_used": [1, 2], "slice_S1": 30,
           "rendering": "source profiles pre-compensated at sub-pixel offset (0.3, 0.6) so that re-binning reproduces "
                        "the calibration profile; 3x3 samples per pixel; 8-bit rounding"}
    t0 = time.time()
    src = np.zeros_like(profs)
    resid = []
    for b in (0, 1):
        for s in range(2, S - 2):
            src[b, s], r = source_profile(profs[b, s], 0.3, 0.6)
            resid.append(r)
    res["compensation_resid_max_grey"] = float(max(resid))
    print(f"source profiles done  {time.time() - t0:.0f} s, max residual {max(resid):.4f} grey", flush=True)
    profs = src

    # S1 + S2: offsets dx, dy in [0, 1) px, slice 30, no noise (8-bit rounding only)
    offs = np.arange(0.0, 1.0, 0.05)
    s1 = {}
    for b in (0, 1):
        E = {n: np.zeros((3, len(offs), len(offs))) for n in PASSES}
        for iy, dy in enumerate(offs):
            for ix, dx in enumerate(offs):
                cx, cy = base + dx, base + dy
                img = to_8bit(render(profs[b, 30], cx + 0.5, cy + 0.5))
                for n in PASSES:
                    x, y, zi, _ = track_one(img, cx, cy, win_rs, win_h, cals[b], n)
                    E[n][:, iy, ix] = x - cx, y - cy, zi - 30
        for n in PASSES:
            ex, ey, ez = E[n]
            s1[f"bead{b + 1}_p{n}"] = {
                "x_err_px": {"mean": float(ex.mean()), "p2p": float(np.ptp(ex)), "rms_about_mean": float(ex.std())},
                "y_err_px": {"mean": float(ey.mean()), "p2p": float(np.ptp(ey)), "rms_about_mean": float(ey.std())},
                "x_err_vs_dx": ex.mean(axis=0).tolist(),
                "z_err_slices": {"mean": float(ez.mean()), "p2p": float(np.ptp(ez)), "rms_about_mean": float(ez.std())}}
        print(f"S1/S2 bead {b + 1} done  {time.time() - t0:.0f} s", flush=True)
    res["S1_S2"] = s1
    res["offsets"] = offs.tolist()

    # S3: z from slice 3 to S-4 in 0.05-slice steps (5 nm), fixed offset (0.3, 0.6), linear blend between slices
    zs = np.arange(3.0, S - 4.0 + 1e-9, 0.05)
    s3 = {}
    for b in (0, 1):
        errs = {n: [] for n in (1, 3)}
        for zt in zs:
            s0 = int(np.floor(zt)); w = zt - s0
            prof = (1 - w) * profs[b, s0] + w * profs[b, min(s0 + 1, S - 1)]
            cx, cy = base + 0.3, base + 0.6
            img = to_8bit(render(prof, cx + 0.5, cy + 0.5))
            for n in (1, 3):
                errs[n].append(track_one(img, cx, cy, win_rs, win_h, cals[b], n)[2] - zt)
        for n in (1, 3):
            err = np.array(errs[n])
            frac = np.mod(zs, 1.0)
            per = [float(err[np.isclose(frac, f, atol=1e-6)].mean()) for f in np.arange(0, 1, 0.05)]
            s3[f"bead{b + 1}_p{n}"] = {"rms_slices": float(np.sqrt((err ** 2).mean())), "p2p_slices": float(np.ptp(err)),
                                       "mean_by_subslice": per, "err_slices": err.tolist()}
        print(f"S3 bead {b + 1} done  {time.time() - t0:.0f} s", flush=True)
    res["S3"] = s3
    res["S3_z"] = zs.tolist()

    # S4: noise, 200 realisations at three offsets, slice 30
    s4 = {}
    for b in (0, 1):
        for n in PASSES:
            rows = []
            for d in (0.0, 0.25, 0.5):
                cx, cy = base + d, base + d
                clean = render(profs[b, 30], cx + 0.5, cy + 0.5)
                r = np.array([track_one(to_8bit(clean, rng, NOISE_SIGMA), cx, cy, win_rs, win_h, cals[b], n)[:3]
                              for _ in range(200)])
                rows.append({"offset": d, "x_bias_px": float(r[:, 0].mean() - cx), "x_sd_px": float(r[:, 0].std()),
                             "y_sd_px": float(r[:, 1].std()), "z_bias_slices": float(r[:, 2].mean() - 30),
                             "z_sd_nm": float(r[:, 2].std() * 100)})
            s4[f"bead{b + 1}_p{n}"] = rows
        print(f"S4 bead {b + 1} done  {time.time() - t0:.0f} s", flush=True)
    res["S4"] = s4
    (out / "synthetic_summary.json").write_text(json.dumps(res, indent=1))
    for k, v in s1.items():
        print(f"S1 {k}: x err p2p {v['x_err_px']['p2p']:.4f} px, mean {v['x_err_px']['mean']:+.4f}; "
              f"z err p2p {v['z_err_slices']['p2p'] * 100:.2f} nm")
    for k, v in s3.items():
        print(f"S3 {k}: z err rms {v['rms_slices'] * 100:.2f} nm, p2p {v['p2p_slices'] * 100:.2f} nm")
    for k, v in s4.items():
        print(f"S4 {k}: " + "; ".join(f"d={r['offset']}: x sd {r['x_sd_px']:.4f} px, z sd {r['z_sd_nm']:.2f} nm" for r in v))
    return res


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "synthetic"
    out = Path(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), "bench_out/xy_passes"))
    out.mkdir(parents=True, exist_ok=True)
    {"replay": replay, "synthetic": synthetic}[mode](out)
    print("RESULT " + json.dumps({"ok": True, "mode": mode, "out": str(out)}))
