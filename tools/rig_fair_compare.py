"""Rig 2026-11-01 (owner: focus set by hand, GUI closed, "run it as a script"): the four reference beads at the owner's
focus. LUT (60 x 100 nm, 0.2 s settle) -> five recorded 20 s runs (frame-loss check) -> one piezo step run whose bead
windows (WIN x WIN px around each pick) are saved from the pipeline's frame tap -> offline: the SAME frames through the
three Z methods (the fair comparison; the online `current` result is checked against the offline one). Beads 1 and 4
are invalid by the owner's judgement (doublet, fragment); the numbers are reported for all four, the verdict uses 2 and 3.

Output in OUT: cal_focus, run_1..5.h5, piezo_current_numba.h5, windows.npz, report.json, compare.json.
"""
import json
import os
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
import rig_refbead_track as T

from mtpy import api
from mtpy.acq.pipeline import BeadTracker, make_kernel
from mtpy.api import events
from mtpy.data import read_run
from mtpy.gui import zscan
from mtpy.lvfiles import read_cal, write_cal

OUT = os.environ.get("OUT", r"G:\l2s_rig_data\2026-11-01_fair_compare")
T.OUT = OUT
PICKS = [(1075.42, 572.24), (680.63, 703.4), (565.13, 792.07), (430.85, 476.99)]     # owner 2026-11-01 15:0x: beads 1, 13, 11, 8 of candidates_numbered.png
WIN = 160                                                                     # window per bead (cross 120 -> 144 used)
RUNS, RUN_S = int(os.environ.get("RUNS", "5")), float(os.environ.get("RUN_S", "20"))
Z_METHODS = ("current", "spline", "phase_spline")
say = T.say


def check_picks():
    api.acq.start(record=False, name="check")
    try:
        img = api.acq.average(10, timeout_s=10)
    finally:
        api.acq.stop()
    np.save(os.path.join(OUT, "frame.npy"), np.clip(np.rint(img), 0, 255).astype(np.uint8))
    say(f"  frame mean {img.mean():.1f}, max {img.max():.0f}, pixels at 255: {(img >= 254.5).sum()}")
    xy = []
    for x, y in PICKS:
        xo, yo, _ = zscan.bead_profile(img, x, y, 120)
        say(f"  pick ({x:.1f}, {y:.1f}) -> refined ({xo:.2f}, {yo:.2f}), moved {np.hypot(xo - x, yo - y):.2f} px")
        if np.hypot(xo - x, yo - y) > 15:
            raise RuntimeError(f"bead at {x, y} moved too far: picks need redoing (frame.npy saved)")
        xy.append((xo, yo))
    return np.array(xy)


class Tap:
    """Keeps the WIN x WIN window of every bead for every frame the worker sees (uint8), with the frame record."""
    def __init__(self, xy, n_max):
        self.org = [(int(np.rint(x)) - WIN // 2, int(np.rint(y)) - WIN // 2) for x, y in xy]
        self.win = np.zeros((n_max, len(xy), WIN, WIN), dtype=np.uint8)
        self.buf, self.t_host, self.n = np.zeros(n_max, np.int64), np.zeros(n_max), 0

    def __call__(self, rec, image, res):
        if self.n >= len(self.buf):
            return
        for b, (ox, oy) in enumerate(self.org):
            self.win[self.n, b] = image[oy:oy + WIN, ox:ox + WIN]
        self.buf[self.n], self.t_host[self.n] = rec.buffer_number, rec.t_pc_s
        self.n += 1


def offline(cal_path, xy, tap, h5_path):
    """The saved windows on a 2 x 2 canvas through every Z method; holds from the piezo marks of the online run."""
    cal = read_cal(cal_path)
    canvas_xy = np.array([[(b % 2) * WIN + (x - tap.org[b][0]), (b // 2) * WIN + (y - tap.org[b][1])]
                          for b, (x, y) in enumerate(xy)])
    cal["xy"] = canvas_xy
    canvas_cal = os.path.join(OUT, "cal_canvas")
    write_cal(canvas_cal, cal)
    api.beads.select(list(range(1, len(xy) + 1)), cal_path=canvas_cal)
    beads = api.beads.selected()
    n = tap.n
    frames = np.zeros((n, 2 * WIN, 2 * WIN), dtype=np.uint8)
    for b in range(len(xy)):
        frames[:, (b // 2) * WIN:(b // 2 + 1) * WIN, (b % 2) * WIN:(b % 2 + 1) * WIN] = tap.win[:n, b]
    run = read_run(h5_path)
    marks = sorted(zip(run["events"]["mark"]["t_host"], run["events"]["mark"]["data"]))
    out = {"frames": int(n), "methods": {}}
    z_online = run["mt"]["z_um"]
    buf_online = run["mt"]["buffer_number"]
    t_of = dict(zip(buf_online.tolist(), run["mt"]["t_host"].tolist()))       # the run's clock (s since start)
    t_tap = np.array([t_of.get(int(b), np.nan) for b in tap.buf[:n]])
    for zm in Z_METHODS:
        t0 = time.perf_counter()
        trk = BeadTracker(beads, make_kernel(beads, zm, False))
        z = np.full((n, len(xy)), np.nan)
        for i in range(n):
            xyz, good = trk.step(frames[i])
            z[i] = np.where(good & (xyz[:, 2] != -1.0), xyz[:, 2], np.nan)
        holds = []
        for i, (tm, data) in enumerate(marks):
            text = (data if isinstance(data, dict) else json.loads(data)).get("text", "")
            if not text.startswith("piezo ") or text.startswith("piezo back"):
                continue
            t1 = marks[i + 1][0] if i + 1 < len(marks) else np.nanmax(t_tap)
            m = (t_tap > tm + 0.8) & (t_tap < t1 - 0.2)
            holds.append((float(text.split()[1]), np.nanmean(z[m], axis=0).tolist(), int(m.sum())))
        cmd = np.array([h[0] for h in holds])
        fit = []
        for b in range(len(xy)):
            zz = np.array([h[1][b] for h in holds])
            g = ~np.isnan(zz)
            slope, off = np.polyfit(cmd[g], zz[g], 1)
            resid = zz[g] - (slope * cmd[g] + off)
            fit.append({"slope": float(slope), "rms_resid_nm": float(np.sqrt(np.mean(resid ** 2)) * 1000)})
        dz = np.diff(z, axis=0)
        noise = float(np.nanstd(dz[:, 1] - dz[:, 2]) / np.sqrt(2) * 1000)       # beads 2 - 3 differential, nm
        row = {"fit_per_bead": fit, "holds": holds, "diff_noise_z_nm_beads_2_3": noise,
               "offline_s": time.perf_counter() - t0, "nan_frames": int(np.isnan(z).any(axis=1).sum())}
        if zm == "current":                        # the online run was `current`: same frames, same numbers?
            idx = {int(b): i for i, b in enumerate(buf_online)}
            keep = [i for i, b in enumerate(tap.buf[:n]) if int(b) in idx]
            sel = [idx[int(tap.buf[i])] for i in keep]
            d = np.abs(z[keep] - z_online[sel])
            row["online_vs_offline_max_dz_nm"] = float(np.nanmax(d) * 1000)
        out["methods"][zm] = row
        say(f"RESULT offline {zm}: slopes " + ", ".join(f"{f['slope']:.4f}" for f in fit) + "; rms nm "
            + ", ".join(f"{f['rms_resid_nm']:.0f}" for f in fit) + f"; z noise (2-3) {noise:.1f} nm; "
            + (f"online vs offline max |dz| {row['online_vs_offline_max_dz_nm']:.3f} nm" if zm == "current" else "")
            + f"; {row['offline_s']:.0f} s")
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "settle_s": zscan.SETTLE_S, "runs": []}
    tap = None
    with events.as_caller("script:rig-fair-compare@1"):
        report["connect"] = T.connect()
        try:
            xy = check_picks()
            report["xy"] = xy.tolist()
            cal_path = os.path.join(OUT, "cal_focus")
            api.acq.start(record=False, name="zscan")
            try:
                t0 = time.monotonic()
                zscan.run(cal_path, xy, slices=60, step_nm=100.0, n_avg=10, cross=120,
                          progress=lambda i, n: (i % 20 == 0) and say(f"  slice {i}/{n}"))
                say(f"RESULT z scan in {time.monotonic() - t0:.0f} s; focus back at {api.focus.position():.3f} um")
            finally:
                api.acq.stop()
            ids = list(range(1, len(xy) + 1))
            api.beads.select(ids, cal_path=cal_path)
            roles = {i: "reference" for i in ids}
            for r in range(RUNS):
                report["runs"].append(T.one_run(f"run_{r + 1}", "current", False, RUN_S, roles))
                T.dump(report, "report.json")
            tap = Tap(xy, int(90 * (len(T.PIEZO_UM) * T.HOLD_S + 20)))

            def piezo_with_tap():
                api.acq._pipe.frame_tap = tap          # tools-only hook (pipeline.frame_tap)
                T.piezo_steps()
            report["runs"].append(T.one_run("piezo_current_numba", "current", False, 0, roles, during=piezo_with_tap))
            report["piezo_um"] = T.PIEZO_UM
            say(f"windows kept: {tap.n} frames x {len(xy)} beads x {WIN} px")
            np.savez_compressed(os.path.join(OUT, "windows.npz"), win=tap.win[:tap.n], buf=tap.buf[:tap.n],
                                t_host=tap.t_host[:tap.n], org=np.array(tap.org), xy=xy)
        except Exception as e:  # noqa: BLE001
            say(f"RESULT session FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
            report["error"] = f"{type(e).__name__}: {e}"
            if api.acq.running():
                say("acq status:", json.dumps(api.acq.status(), default=str)[:1200])
        finally:
            if api.acq.running():
                api.acq.stop()
            t1 = time.monotonic()
            try:
                api.devices.disconnect()
                report["disconnect_s"] = time.monotonic() - t1
                say(f"RESULT disconnect clean in {report['disconnect_s']:.1f} s; lock {api.rig.status()}")
            except Exception as e:  # noqa: BLE001
                report["disconnect_error"] = f"{type(e).__name__}: {e}"
                say(f"RESULT disconnect FAILED: {type(e).__name__}: {e}")
    report["error_events"] = [{"kind": e.kind, "extra": e.extra} for e in events.events()
                              if e.kind in ("device_error", "refused", "estop")]
    for e in report["error_events"]:
        say("EVENT", e["kind"], json.dumps(e["extra"], default=str)[:300])
    T.dump(report, "report.json")
    if tap is not None and tap.n and "error" not in report:
        cmp = offline(os.path.join(OUT, "cal_focus"), np.array(report["xy"]), tap, os.path.join(OUT, "piezo_current_numba.h5"))
        T.dump(cmp, "compare.json")


class SavedTap:
    def __init__(self, path):
        w = np.load(path)
        self.win, self.buf, self.t_host, self.org = w["win"], w["buf"], w["t_host"], [tuple(o) for o in w["org"]]
        self.n, self.xy = len(self.buf), w["xy"]


if __name__ == "__main__":
    if os.environ.get("OFFLINE"):                 # the offline part alone, from windows.npz
        tap = SavedTap(os.path.join(OUT, "windows.npz"))
        T.dump(offline(os.path.join(OUT, "cal_focus"), tap.xy, tap, os.path.join(OUT, "piezo_current_numba.h5")), "compare.json")
    else:
        main()
