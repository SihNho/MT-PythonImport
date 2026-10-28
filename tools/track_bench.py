r"""track_bench.py - tracking alternatives against the current method on the recorded reference-bead data
(decision 0023 item 4; phase 10b, offline, no device).

  py tools/track_bench.py [--quick]      -> docs/results/2026-10-28-track-bench.json and a printed table

Data: the 2026-10-26 z-scan (8 fixed beads, 100 nm steps over +-5 um, 30 frames per slice at 150 Hz, 160 px crops) and
the first 60 s of the 30 min drift run (same beads at rest). Each method builds its own LUT from the FIRST half of
every slice's frames and is tested on the SECOND half (out of sample).

Measures (nm; 203 nm / px measured):
- xy / z noise: per-slice scatter of the DIFFERENCE of two beads / sqrt 2 (common motion removed), median over pairs
  and slices;
- z error: rms of the slice-mean z against the commanded z over +-4 um, offset removed (interpolation + LUT bias);
- z slope: tracked vs commanded;
- time: per bead and frame of the stage, numpy only (the current method's numba time is the production figure).

Methods (each stage swappable, decision 0003):
- XY: `current` (mirrored cross profiles, 3 passes); `qi` (quadrant interpolation, van Loenhout 2012: polar
  resampling at 1/3 px, quadrant profiles, mirror correlation, 2 passes).
- radial profile: `current` (two-bin split), `polar3`, `area4` (tools/radial_profile_bench.py).
- Z: `current` (band-pass + 5-slice phase fit); `spline` (continuous LUT by cubic interpolation of the prepped
  profiles, SSD minimised by golden section; Kovari 2019 in spirit); `phasor` (single-frequency phase of the
  mirrored profile mapped to z by a polynomial; Brouwer 2020 in spirit, z part only).
"""
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import radial_profile_bench as RB
import refbead_analyze as A

from mtpy import calib, track

NM_PX = 203.0
CROSS, HALF = 120, 60
H = track.lv_round(CROSS * 0.6)
WIN_RS, WIN_H = calib.windows(CROSS)
LOW, HIGH, FORGET = 0, 40, 10                                   # decision 0022 (50x)
ZSCAN = r"G:\l2s_rig_data\2026-10-26_refbead\zscan"
DRIFT = r"G:\l2s_rig_data\2026-10-26_refbead\drift"
BEADS = [0, 1, 2, 4, 6, 7, 8, 9]


# ---------------------------------------------------------------- XY stages
def xy_current(sub, cx, cy):
    x, y, _, _ = track.xy_croquette(sub, H, cx, cy, CROSS, WIN_RS, WIN_H, track.DEFAULT)
    return x, y


_QI_DR = 1 / 3
_QI_R = np.arange(_QI_DR, HALF - 1, _QI_DR)                    # radii of the quadrant profiles (r = 0 excluded)
_QI_N = 24                                                      # angles per quadrant per ring
_QI_TH = {q: (q * np.pi / 2 - np.pi / 4) + np.pi / 2 * (np.arange(_QI_N) + 0.5) / _QI_N for q in range(4)}
# quadrants: 0 = +x (right), 1 = +y (down in image rows), 2 = -x (left), 3 = -y (up)
_QI_OFF = {q: (np.outer(_QI_R, np.cos(th)), np.outer(_QI_R, np.sin(th))) for q, th in _QI_TH.items()}
_QI_WIN, _QI_WH = calib.windows(2 * len(_QI_R))


def _bilinear(sub, x, y):
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    return ((1 - fy) * ((1 - fx) * sub[y0, x0] + fx * sub[y0, x0 + 1])
            + fy * ((1 - fx) * sub[y0 + 1, x0] + fx * sub[y0 + 1, x0 + 1]))


def _qi_profiles(sub, xc, yc):
    s = sub.astype(np.float64)
    return [_bilinear(s, xc + dx, yc + dy).mean(1) for dx, dy in _QI_OFF.values()]


def _mirror_shift(profile):
    """Shift of the profile's centre of symmetry (profile samples), by the current method's FFT mirror correlation
    with one phase-shifted refit (two passes)."""
    n = len(profile)
    half = n // 2
    p = (profile - profile.mean()) * _QI_WIN
    F = np.fft.fft(p) * _QI_WH
    F2 = F * F
    k = 2 * np.pi / n
    i = np.arange(n)
    a = np.where(i > half, i - n, i).astype(np.float64)
    P1 = track.fit_parabola(np.roll(np.abs(np.fft.ifft(F2)), half), 5)
    r1 = track.lv_round(P1)
    G1 = np.abs(F2) * np.exp(1j * (np.angle(F2) + k * (P1 - r1) * a))
    out1 = track.fit_parabola(np.roll(np.abs(np.fft.ifft(G1)), half), 5) - r1
    return (P1 + out1 - half) / 2


def xy_qi(sub, cx, cy, passes=2):
    x, y = float(cx), float(cy)
    for _ in range(passes):
        q = _qi_profiles(sub, x, y)
        px = np.concatenate([q[2][::-1], q[0]])                 # -x profile reversed ++ +x profile
        py = np.concatenate([q[3][::-1], q[1]])
        x += _mirror_shift(px) * _QI_DR
        y += _mirror_shift(py) * _QI_DR
    return x, y


XY = {"current": xy_current, "qi": xy_qi}
RADIAL = {"current": RB.RADIALS["current"], "polar3": RB.RADIALS["polar3"], "area4": RB.RADIALS["area4"]}


# ---------------------------------------------------------------- Z stages (take the mirrored, prepped profile)
def z_current(rad, cal):
    zi, _ = track.z_phase(rad, HALF, cal, track.DEFAULT)
    return zi


def z_spline(rad, cal):
    """Continuous LUT: Catmull-Rom cubic interpolation of the prepped real profiles along z, SSD minimised by golden
    section within +-1 slice of the best slice."""
    prep, _ = track.prep_i_of_r(rad, HALF, int(cal["forget_radius"]), cal["cosband"])
    R = cal["real"]
    S = len(R)
    idx = track.fit_prep_to_cal(prep, R)

    def at(z):
        i = int(np.floor(z))
        t = z - i
        p0, p1, p2, p3 = (R[min(max(i + k, 0), S - 1)] for k in (-1, 0, 1, 2))
        return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                      + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)

    def ssd(z):
        return float(((at(z) - prep) ** 2).sum())

    lo, hi = max(idx - 1.0, 0.0), min(idx + 1.0, S - 1.0)
    g = (np.sqrt(5) - 1) / 2
    c, d = hi - g * (hi - lo), lo + g * (hi - lo)
    fc, fd = ssd(c), ssd(d)
    for _ in range(30):
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - g * (hi - lo)
            fc = ssd(c)
        else:
            lo, c, fc = c, d, fd
            d = lo + g * (hi - lo)
            fd = ssd(d)
    return (lo + hi) / 2


class Phasor:
    """Single-frequency phasor z. The MIRRORED profile is symmetric, so its FFT is real and carries no phase; the
    one-sided profile (r >= forget) does: the phase of its FFT at the band's strongest bin moves with z as the rings
    move outward. Unwrapped along the LUT and mapped to the slice index by interpolation. Per bead."""

    def __init__(self, stack_onesided, low, high, forget):
        self.f0 = forget
        P = stack_onesided[:, forget:] - stack_onesided[:, forget:].mean(1, keepdims=True)
        F = np.fft.rfft(P, axis=1)
        n = F.shape[1]
        lo, hi = max(1, low * n // HALF), min(n - 1, max(2, high * n // HALF))
        self.k = lo + int(np.argmax(np.abs(F[:, lo:hi + 1]).mean(0)))
        ph = np.unwrap(np.angle(F[:, self.k]))
        self.ph = ph
        self.idx = np.arange(len(ph), dtype=float)
        self.mono = bool(np.all(np.diff(ph) > 0) or np.all(np.diff(ph) < 0))

    def z(self, rad):
        p = rad[self.f0:] - rad[self.f0:].mean()
        a = np.angle(np.fft.rfft(p)[self.k])
        cands = a + 2 * np.pi * np.arange(-8, 9)
        lo, hi = self.ph.min(), self.ph.max()
        c = cands[(cands >= lo - 0.5) & (cands <= hi + 0.5)]
        if not len(c):
            return np.nan
        # nearest LUT phase sample decides the branch, then linear interpolation of the index along the LUT
        j = [int(np.argmin(np.abs(self.ph - v))) for v in c]
        best = int(np.argmin([abs(self.ph[jj] - v) for jj, v in zip(j, c)]))
        v, jj = c[best], j[best]
        k0 = max(0, min(jj - 1, len(self.ph) - 2))
        seg = self.ph[k0:k0 + 3]
        order = np.argsort(seg)
        return float(np.interp(v, seg[order], self.idx[k0:k0 + 3][order]))


# ---------------------------------------------------------------- data
def zscan_slices(d=ZSCAN, seg="zscan"):
    crops, idx, _ = A.load(d, seg)
    mk = A.marks(d)
    ks = sorted(int(n.split("_z")[-1][:-6]) for n in mk if n.startswith(seg + "_z") and n.endswith("_start"))
    out = []
    for k in ks:
        fr = np.flatnonzero((idx[:, 0] > mk[f"{seg}_z{k}_start"]) & (idx[:, 0] <= mk[f"{seg}_z{k}_end"]))
        out.append((k * 0.1, fr))
    return crops, out


def run_stage(crops, frames, xy_fn, rad_fn):
    """(xy (n, b, 2) crop px, profiles (n, b, 60), t_xy, t_rad per bead-frame in ms)."""
    hc = crops.shape[2] // 2
    xy = np.full((len(frames), len(BEADS), 2), np.nan)
    prof = np.full((len(frames), len(BEADS), HALF), np.nan)
    t_xy = t_rad = 0.0
    for i, f in enumerate(frames):
        for j, b in enumerate(BEADS):
            sub = crops[f, b, hc - H:hc + H, hc - H:hc + H]
            try:
                t0 = time.perf_counter()
                x, y = xy_fn(sub, H, H)
                t1 = time.perf_counter()
                r = rad_fn(sub, x, y, HALF, track.DEFAULT)
                t_rad += time.perf_counter() - t1
                t_xy += t1 - t0
                xy[i, j] = x, y
                prof[i, j] = r
            except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                pass
    n = len(frames) * len(BEADS)
    return xy, prof, 1e3 * t_xy / n, 1e3 * t_rad / n


def diff_noise(v):
    """Median over bead pairs of std(a - b) / sqrt 2 along axis 0; v: (frames, beads[, k])."""
    nb = v.shape[1]
    d = [np.nanstd(v[:, i] - v[:, j], axis=0) / np.sqrt(2) for i in range(nb) for j in range(i + 1, nb)]
    return np.nanmedian(d, axis=0)


def eval_z(second, zs, step, fn):
    """Run one z estimator fn(profile, bead column) -> slice index on the test halves; noise / error / slope / time."""
    t0 = time.perf_counter()
    zz, cmd = [], []
    for zc, p in second:
        z = np.full((len(p), len(BEADS)), np.nan)
        for f in range(len(p)):
            for j in range(len(BEADS)):
                if np.isnan(p[f, j]).any():
                    continue
                try:
                    z[f, j] = zs[0] + fn(p[f, j], j) * step
                except (TypeError, ValueError, IndexError, np.linalg.LinAlgError):
                    pass
        zz.append(z)
        cmd.append(zc)
    t_z = 1e3 * (time.perf_counter() - t0) / sum(len(p) for _, p in second) / len(BEADS)
    cmd = np.array(cmd)
    noise = np.nanmedian([diff_noise(z) for z in zz]) * 1000
    means = np.array([np.nanmean(z, 0) for z in zz])              # (S, beads)
    m = np.abs(cmd) <= 4.0
    err = means[m] - cmd[m, None]
    err = err - np.nanmedian(err, 0)
    rms = float(np.sqrt(np.nanmean(err ** 2)) * 1000)
    slope = float(np.nanmedian([np.polyfit(cmd[m], means[m, j], 1)[0] for j in range(len(BEADS))
                                if np.isfinite(means[m, j]).all()]))
    lost = float(np.mean([np.isnan(z).mean() for z in zz]))
    return {"z_noise_nm": round(float(noise), 2), "z_err_nm": round(rms, 1), "slope": round(slope, 4),
            "t_z_ms": round(t_z, 3), "lost": round(lost, 4)}


def main():
    quick = "--quick" in sys.argv
    crops, sl = zscan_slices()
    if quick:
        sl = sl[::5]
    fr_all = np.concatenate([fr for _, fr in sl])
    res = {"beads": BEADS, "nm_px": NM_PX, "slices": len(sl), "stages": {}}
    print(f"z-scan: {len(sl)} slices, {len(fr_all)} frames x {len(BEADS)} beads", flush=True)

    stage_out = {}
    for xy_name, xy_fn in XY.items():
        for rad_name, rad_fn in RADIAL.items():
            key = f"{xy_name}+{rad_name}"
            t0 = time.time()
            xy, prof, t_xy, t_rad = run_stage(crops, fr_all, xy_fn, rad_fn)
            stage_out[key] = (xy, prof)
            # xy noise within slices (bead at rest)
            noise = []
            pos = 0
            for _, fr in sl:
                n = len(fr)
                noise.append(diff_noise(xy[pos:pos + n]))
                pos += n
            xy_noise = np.nanmedian(noise, 0) * NM_PX
            res["stages"][key] = {"t_xy_ms": round(t_xy, 3), "t_rad_ms": round(t_rad, 3),
                                  "xy_noise_nm": xy_noise.round(2).tolist(), "wall_s": round(time.time() - t0)}
            print(f"  {key:16s} xy noise {xy_noise[0]:.2f} / {xy_noise[1]:.2f} nm  t_xy {t_xy:.2f} ms  "
                  f"t_rad {t_rad:.2f} ms  ({time.time() - t0:.0f} s)", flush=True)

    # Z: per XY+radial combination, build LUT (first half) and evaluate every z stage (second half)
    res["z"] = {}
    for key, (xy, prof) in stage_out.items():
        pos = 0
        first, second = [], []
        for zc, fr in sl:
            n = len(fr)
            first.append(np.nanmean(prof[pos:pos + n // 2], 0))
            second.append((zc, prof[pos + n // 2:pos + n]))
            pos += n
        stack = np.array(first)                                   # (S, beads, 60)
        if np.isnan(stack).any():
            print(f"  {key}: LUT incomplete, skipped", flush=True)
            continue
        zs = np.array([zc for zc, _ in sl])
        step = zs[1] - zs[0]
        cals, phasors = [], []
        for j in range(len(BEADS)):
            mir = np.concatenate([stack[:, j, 1:][:, ::-1], stack[:, j]], 1)
            cals.append(calib.prep_bead(mir, LOW, HIGH, FORGET, step, CROSS))
            phasors.append(Phasor(stack[:, j], LOW, HIGH, FORGET))
        if key == "current+current":                             # the LabVIEW baseline: its own LUT settings 0/25/20
            cals_lv = [calib.prep_bead(np.concatenate([stack[:, j, 1:][:, ::-1], stack[:, j]], 1), 0, 25, 20, step,
                                       CROSS) for j in range(len(BEADS))]
            r = eval_z(second, zs, step, lambda p, j, c=cals_lv: z_current(p, c[j]))
            res["z"]["labview(0/25/20)"] = r
            print(f"  {'labview(0/25/20)':24s} z noise {r['z_noise_nm']:5.2f} nm  err {r['z_err_nm']:5.1f} nm  "
                  f"slope {r['slope']:.4f}", flush=True)
        for z_name in ("current", "spline", "phasor"):
            fn = {"current": lambda p, j, c=cals: z_current(p, c[j]), "spline": lambda p, j, c=cals: z_spline(p, c[j]),
                  "phasor": lambda p, j, ph=phasors: ph[j].z(p)}[z_name]
            r = eval_z(second, zs, step, fn)
            res["z"][f"{key}+{z_name}"] = r
            print(f"  {key + '+' + z_name:24s} z noise {r['z_noise_nm']:5.2f} nm  err {r['z_err_nm']:5.1f} nm  "
                  f"slope {r['slope']:.4f}  t_z {r['t_z_ms']:.2f} ms  lost {r['lost']:.3f}", flush=True)
    out = os.path.join(ROOT, "docs", "results", "2026-10-28-track-bench.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print("->", out)


if __name__ == "__main__":
    main()
