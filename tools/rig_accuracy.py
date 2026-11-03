"""Rig 2026-11-01 (owner: "now the accuracy test: per method, frame rate and bead count; frame loss and processing
time; script alone and under the GUI; not still - step the piezo, compare each bead raw and after reference-bead
correction, and move the magnet too"). Per point: FPS x bead count x z method x executor, a recorded run during which
the focus piezo steps (FOCUS_UM) and then the magnet moves (MAGNET_MM); frames / drops / tracking time from the status,
accuracy from the run file (`accuracy`). The beads are copies of the owner's four (cal tiled as in rig_bead_count), so
the accuracy uses the first len(base) distinct beads only. STAGE=1 (default) adds the stage xy steps between the focus
and the magnet; STEP_NM=20|50|100 replaces the +-1 um pattern by a staircase of five steps up and down; SPEED_FACTOR=0.1
runs the focus at a tenth of its opening speed; EXEC=numba limits the executors. Output in OUT: cal_acc_<fps>, cal_<fps>_<n>, acc_<fps>_<n>_<zm>_<ex>.h5,
report.json. FPS=max takes the camera's cap at the ROI in force; ROI=x,y,w,h runs in a smaller ROI (PICK_IDS
chooses the owner's beads that fit it; positions are ROI pixels). GUI mode of the same bench: gui_rig_isolate.py with STEPS=1.
"""
import json
import os
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
import rig_motion_noise as M
import rig_refbead_track as T

from mtpy import api, calib, track
from mtpy.api import events, zscan
from mtpy.data import read_run
from mtpy.lvfiles import read_cal, write_cal

OUT = os.environ.get("OUT", r"G:\l2s_rig_data\2026-11-01_accuracy")
CAL = os.environ.get("CAL")                 # None: a fresh z scan per frame rate (the beads drift ~13 px in 5 h; at 150 Hz
                                            # the auto exposure is shorter, and a 90-Hz LUT read z 0.9 um low, bead 1 ambiguous)
T.OUT = OUT
FPS = [f if f == "max" else float(f) for f in os.environ.get("FPS", "90,150").split(",")]   # max: the camera's cap
ROI = tuple(int(v) for v in os.environ["ROI"].split(",")) if os.environ.get("ROI") else None     # x,y,w,h
PICK_IDS = [int(i) for i in os.environ.get("PICK_IDS", "1,2,3,4").split(",")]   # of M.PICKS; a half ROI holds 2-4
COUNTS = [int(c) for c in os.environ.get("COUNTS", "5,10,20").split(",")]
Z_METHODS = os.environ.get("ZMETHODS", "current,spline,phase_spline").split(",")
EXECUTORS = [(e, e == "gpu") for e in os.environ.get("EXEC", "numba,gpu").split(",")]
SPEED_FACTOR = float(os.environ.get("SPEED_FACTOR", "1"))     # focus speed = opening speed x this (1/10 in the bench)
SPEED_MM_S = float(os.environ["SPEED_MM_S"]) if os.environ.get("SPEED_MM_S") else None   # or an absolute speed (0.001 = 1 um/s)
STEP_NM = float(os.environ["STEP_NM"]) if os.environ.get("STEP_NM") else None   # staircase of 5 steps up and down
STAGE = os.environ.get("STAGE", "1") != "0"                   # include the stage xy steps (owner: "motor motion too")
M.HOLD_S = float(os.environ.get("HOLD_S", "2"))
M.FOCUS_UM = ([k * STEP_NM / 1000.0 for k in (0, 1, 2, 3, 4, 5, 4, 3, 2, 1, 0)] if STEP_NM else
              [float(v) for v in os.environ.get("FOCUS_UM", "0,0.5,1,0,-1,0").split(",")])
M.STAGE_UM = [tuple(int(v) for v in p.split(":")) for p in
              os.environ.get("STAGE_UM", "0:0,1:0,2:0,5:0,0:0,0:1,0:2,0:5,0:0").split(",")]
M.MAGNET_MM = [float(v) for v in os.environ.get("MAGNET_MM", "0,10,30,0").split(",")]
RING_PX = float(os.environ.get("RING_PX") or 0) if "RING_PX" in os.environ else 12.2     # bright-ring radius of beads 2-4 at the owner's 11-01 focus; "" = no match
RING_TOL, RING_PX_PER_UM = 0.15, 0.9                 # the 11-01 LUT: the ring grows 0.9 px per um of focus
LATEST = r"G:\l2s_rig_data\bead_picks_latest.json"    # the owner's four beads where they were last found (full frame)
say = T.say


def find_picks(img, picks, cross=120):
    """The owner's beads on today's frame: Croquette XY iterated from the last known positions (the beads drift a
    dozen px in hours; one pass leaves the radial window out of bounds). The stage drift is the same for every
    bead, so a bead whose shift disagrees with the others' median is retried from that median (20:32: bead 2 locked
    onto a neighbour 31 px left while the others went 18 px right) and refused if it still disagrees."""
    h, (win_rs, win_h) = track.lv_round(cross * 0.6), calib.windows(cross)

    def refine(x, y):
        for _ in range(4):
            xi, yi = int(np.rint(x)), int(np.rint(y))
            xo, yo, sx, sy = track.xy_croquette(img[yi - h:yi + h, xi - h:xi + h], h, xi, yi, cross, win_rs, win_h, track.DEFAULT)
            x, y = float(xo), float(yo)
            if abs(sx) < 4 and abs(sy) < 4:
                return x, y
        raise RuntimeError(f"bead near {x, y} not found (frame.npy saved)")

    def from_shift(shift):
        out = np.array([refine(*(p + shift)) for p in picks])
        median = np.median(out - picks, axis=0)
        for i in np.flatnonzero(np.abs(out - picks - median).max(axis=1) > 5):
            out[i] = refine(*(picks[i] + median))
        if np.abs(out - picks - median).max() > 5:
            raise RuntimeError(f"the beads did not move alike (shifts {(out - picks).round(1).tolist()}); frame.npy saved")
        return out

    picks = np.array(picks, dtype=float)
    try:
        out = from_shift(np.zeros(2))
    except (RuntimeError, IndexError, ValueError, TypeError) as e:
        # 23:19: the beads moved 27 px during one GUI block (~55 px/h), past what one Croquette start converges from:
        # search the common shift on a grid around the last positions, nearest first, until all beads agree
        grid = sorted(((dx, dy) for dx in range(-90, 91, 10) for dy in range(-90, 91, 10)), key=lambda d: d[0] ** 2 + d[1] ** 2)
        for d in grid[1:]:
            try:
                out = from_shift(np.array(d, dtype=float))
                break
            except (RuntimeError, IndexError, ValueError, TypeError):
                continue
        else:
            raise RuntimeError(f"beads not found within 90 px of the last positions ({e}); frame.npy saved") from e
    for (x0, y0), (x, y) in zip(picks, out):
        say(f"  pick ({x0:.1f}, {y0:.1f}) -> ({x:.2f}, {y:.2f}), moved {np.hypot(x - x0, y - y0):.1f} px")
    return out


def ring_radius(prof, lo=5, hi=40):
    """Radius (px, sub-pixel) of the first bright ring of a mirrored radial profile: the brightest point within
    `hi` px of the centre, parabola-refined. Grows ~0.9 px per um of focus (11-01 LUT), 12.2 px at the owner's focus."""
    half = len(prof) // 2
    p = np.asarray(prof, dtype=float)[half:]
    i = lo + int(np.argmax(p[lo:hi]))
    a, b, c = p[i - 1], p[i], p[i + 1]
    return i + ((a - c) / (2 * (a - 2 * b + c)) if (a - 2 * b + c) != 0 else 0.0)


def focus_match(xy, target=RING_PX, tol=RING_TOL, tries=8):
    """Owner 2026-11-03: "check the bead radius before the calibration and match it with the piezo". Steps the focus
    until the beads' median bright-ring radius is within `tol` px of `target` (the owner's focus of 11-01); the focus
    stays where it ends. Acquisition must be running. Returns (radius, focus z um)."""
    z = api.focus.position()
    for _ in range(tries):
        img = api.acq.average(5, timeout_s=10)
        r = float(np.median([ring_radius(zscan.bead_profile(img, x, y, 120)[2]) for x, y in xy]))
        say(f"  ring radius {r:.2f} px (target {target}), focus {z:.3f} um")
        if abs(r - target) <= tol:
            return r, z
        dz = float(np.clip((target - r) / RING_PX_PER_UM, -1.5, 1.5))
        z = api.focus.move_to(z + dz).wait(10)
        time.sleep(0.3)
    raise RuntimeError(f"focus match did not converge: ring radius {r:.2f} px, target {target}")


def make_cal(path):
    api.acq.start(record=False, name="check")
    try:
        img = api.acq.average(10, timeout_s=10)
        np.save(os.path.join(OUT, "frame.npy"), np.clip(np.rint(img), 0, 255).astype(np.uint8))
        origin = np.array(ROI[:2] if ROI else (0, 0), dtype=float)      # bead positions are ROI pixels
        picks = M.PICKS
        if os.path.exists(LATEST):              # the beads drift ~15 px/h: start from where they were last found
            with open(LATEST, encoding="utf-8") as f:
                picks = json.load(f)["picks"]
        xy = find_picks(img, [np.array(picks[i - 1]) - origin for i in PICK_IDS])
        if RING_PX:
            r, z = focus_match(xy[1:] if PICK_IDS == [1, 2, 3, 4] else xy)      # bead 1 reads 1.2 px larger: use 2-4
            say(f"RESULT focus matched: ring {r:.2f} px at focus {z:.3f} um")
            img = api.acq.average(10, timeout_s=10)
            xy = find_picks(img, xy)
        if PICK_IDS == [1, 2, 3, 4]:
            with open(LATEST, "w", encoding="utf-8") as f:
                json.dump({"picks": (xy + origin).tolist(), "time": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
        zscan.run(path, xy, slices=60, step_nm=100.0, n_avg=10, cross=120)
        say(f"RESULT z scan done -> {path}; focus back at {api.focus.position():.3f} um")
    finally:
        api.acq.stop()
    return xy


def steps():
    M.focus_steps()
    if STAGE:
        M.stage_steps()
    M.magnet_steps()


def tiled_cal(base, n, path):
    """`base` (the owner's beads) repeated to n beads (the kernel's work per bead is the same whether beads are distinct
    or not; rig_bead_count), written to `path`."""
    k = -(-n // len(base["xy"]))
    cal = dict(base)
    cal["xy"] = np.tile(base["xy"], (k, 1))[:n]
    cal["stack"] = np.tile(base["stack"], (k, 1, 1))[:n]
    cal["bead_i32"] = np.tile(base["bead_i32"], (k, 1))[:n]
    cal["bead_flags"] = np.zeros(n, dtype=np.int32)
    write_cal(path, cal)
    return path


FOLLOW_NM = 50.0


def _holds(run, nb):
    """(kind, commanded, per-bead mean z nm (nb,), per-bead std z nm, lost, follow ms, overshoot nm) per hold from
    the marks; follow = time from the mark until the beads' median z is within FOLLOW_NM of the hold's mean (piezo +
    tracking); overshoot = the beads' median z 0.1-0.3 s after the mark minus the settled mean (owner 2026-11-01:
    "a slower move may leave less to correct")."""
    mt = run["mt"]
    t = mt["t_host"]
    z = mt["z_um"][:, :nb] * 1000.0
    ok = (mt["bead_lost"][:, :nb] == 0) & (mt["bead_good"][:, :nb] > 0)
    z = np.where(ok, z, np.nan)
    marks = sorted(zip(run["events"]["mark"]["t_host"], run["events"]["mark"]["data"]))
    out = []
    for i, (t0, data) in enumerate(marks):
        text = (data if isinstance(data, dict) else json.loads(data)).get("text", "")
        if text.endswith("back to start"):
            continue
        t1 = marks[i + 1][0] if i + 1 < len(marks) else t[-1]
        m = (t > t0 + 0.5) & (t < t1 - 0.1)
        if m.sum() < 10:
            continue
        kind, value = text.split()[:2]
        mean = np.nanmean(z[m], axis=0)
        after = (t >= t0) & (t < t1)
        near = np.abs(np.nanmedian(z[after] - mean, axis=1)) < FOLLOW_NM
        follow = float((t[after][np.argmax(near)] - t0) * 1000.0) if near.any() else None
        early = (t > t0 + 0.1) & (t < t0 + 0.3)
        overshoot = float(np.nanmedian(np.nanmean(z[early], axis=0) - mean)) if early.sum() >= 3 else None
        out.append((kind, float(value), mean, np.nanstd(z[m], axis=0), int((~ok[m]).sum()), follow, overshoot))
    return out


def accuracy(path, nb=4):
    """z accuracy of the first nb beads over the piezo and magnet holds, in nm.
    raw: each bead's z change from the first hold of its kind against the commanded piezo step (focus holds) or
    against zero (magnet holds; stuck beads must not move). ref: the same after subtracting bead 1 (the reference) -
    for the focus holds the corrected change must be zero (all beads move together), so the error is the change itself.
    Each as median |error| / max |error| over beads 2..nb and holds; noise = median per-hold std of a bead's z."""
    run = read_run(path)
    holds = _holds(run, nb)
    err = {k: {"raw": [], "ref": []} for k in ("focus", "stage", "magnet")}
    noise, follow, overshoot = [], [], []
    first = {}
    for kind, value, mean, std, _lost, fol, over in holds:
        if kind == "focus" and value != 0.0:
            if fol is not None:
                follow.append(fol)
            if over is not None:
                overshoot.append(abs(over))
        if kind not in first:
            first[kind] = mean
        target = value * 1000.0 if kind == "focus" else 0.0
        raw = (mean - first[kind]) - target
        ref = (mean - mean[0]) - (first[kind] - first[kind][0])
        err[kind]["raw"] += list(np.abs(raw[1:]))
        err[kind]["ref"] += list(np.abs(ref[1:]))
        noise += list(std)

    def mm(v):
        v = [x for x in v if np.isfinite(x)]
        return [float(np.median(v)), float(np.max(v))] if v else [None, None]
    return {"holds": len(holds), "lost": int(sum(h[4] for h in holds)),
            "focus_raw_nm": mm(err["focus"]["raw"]), "focus_ref_nm": mm(err["focus"]["ref"]),
            "stage_raw_nm": mm(err["stage"]["raw"]), "stage_ref_nm": mm(err["stage"]["ref"]),
            "magnet_raw_nm": mm(err["magnet"]["raw"]), "magnet_ref_nm": mm(err["magnet"]["ref"]),
            "noise_nm": mm(noise)[0], "follow_ms": mm(follow), "overshoot_nm": mm(overshoot)}


def fmt(a):
    if a is None:
        return "-"

    def f(v):
        return "-" if v is None else f"{v:.0f}"
    cols = [f"{f(a[k][0]):>4}/{f(a[k][1]):<5}" for k in ("focus_raw_nm", "focus_ref_nm", "stage_raw_nm", "stage_ref_nm",
                                                        "magnet_raw_nm", "magnet_ref_nm")]
    return (" ".join(cols) + f" {f(a['noise_nm']):>5} {a['lost']:4d}  {f(a['follow_ms'][0]):>4}/{f(a['follow_ms'][1]):<5}"
            f" {f(a.get('overshoot_nm', [None])[0]):>4}")


HEADER = ("fps  beads z method      exec   frames  gaps drops  track ms median/std/p99/max   "
          "focus raw  focus ref  stage raw  stage ref  magnet raw magnet ref noise lost  follow ms  over  (nm: median/max |error|)")


def table(rows):
    say(HEADER)
    for r in rows:
        if "error" in r:
            say(f"{r.get('fps', 0):4.0f} {r.get('beads', 0):5d}  {r.get('z_method', ''):12s}  {r['name'].split('_')[-1]:5s}  {r['error'][:80]}")
            continue
        say(f"{r['fps']:4.0f} {r['beads']:5d}  {r['z_method']:12s}  {r['name'].split('_')[-1]:5s}  {r['frames_tracked']:6d}  "
            f"{r['camera_gaps']:4d} {r['pipeline_drops']:5d}  {T.ms4(r):>28s}   {fmt(r.get('accuracy'))}")


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "cal": CAL or "per frame rate", "speed_factor": SPEED_FACTOR, "speed_mm_s": SPEED_MM_S,
              "step_nm": STEP_NM, "stage": STAGE, "stage_um": M.STAGE_UM, "executors": [e for e, _ in EXECUTORS], "fps": FPS, "counts": COUNTS, "hold_s": M.HOLD_S,
              "focus_um": M.FOCUS_UM, "magnet_mm": M.MAGNET_MM, "runs": []}
    with events.as_caller("script:rig-accuracy@1"):
        report["connect"] = T.connect()
        rate0 = report["connect"]["camera"]["settings"]["rate_Hz"]
        roi0 = tuple(report["connect"]["camera"]["settings"]["roi"])
        try:
            report["focus_speed_mm_s"] = speed0 = api.focus.speed()
            if SPEED_FACTOR != 1 or SPEED_MM_S:
                report["focus_speed_set_mm_s"] = api.focus.set_speed(SPEED_MM_S or speed0 * SPEED_FACTOR)
                say(f"focus speed {speed0} -> {report['focus_speed_set_mm_s']} mm/s")
            if ROI:
                report["roi"] = api.camera.set_roi(*ROI, confirm=True)
                say(f"camera ROI {ROI} -> {report['roi']}; limits {api.devices.info('camera')['limits']}")
            for fps in FPS:
                if fps == "max":
                    fps = float(api.devices.info("camera")["limits"]["rate_Hz"][1])
                    exp = api.devices.info("camera")["settings"]["exposure_ms"]
                    if exp > 0.95 * 1000.0 / fps:        # the exposure must fit the frame period (554.9 Hz at 640 x 512)
                        say(f"exposure {exp} ms -> {api.camera.set_exposure(round(0.9 * 1000.0 / fps, 3))} (fixed until the camera closes)")
                report.setdefault("rate_readback", {})[str(fps)] = api.camera.set_rate(fps, confirm=True)
                report.setdefault("camera_settings", {})[str(fps)] = api.devices.info("camera")["settings"]
                say(f"camera rate {fps} -> {report['rate_readback'][str(fps)]}; {report['camera_settings'][str(fps)]}")
                cal_src = CAL or os.path.join(OUT, f"cal_acc_{fps:.0f}")
                if CAL is None:
                    report.setdefault("xy", {})[str(fps)] = make_cal(cal_src).tolist()
                base = read_cal(cal_src)
                nb = len(base["xy"])
                for n in COUNTS:
                    cal_path = tiled_cal(base, n, os.path.join(OUT, f"cal_{fps:.0f}_{n}"))
                    ids = list(range(1, n + 1))
                    api.beads.select(ids, cal_path=cal_path)
                    roles = {i: "reference" for i in ids}
                    for zm in Z_METHODS:
                        for ex, gpu in EXECUTORS:
                            name = f"acc_{fps:.0f}_{n}_{zm}_{ex}"
                            row = T.one_run(name, zm, gpu, 0, roles, during=steps)
                            if row.get("frames_tracked") == 0:      # IMAQdx gave no frame after a restart (seen at 248 Hz, 20:40)
                                say(f"RESULT {name}: 0 frames (camera_error {row.get('camera_error')}); one retry")
                                report.setdefault("zero_frame_runs", []).append(row)
                                name += "_r"
                                row = T.one_run(name, zm, gpu, 0, roles, during=steps)
                            row["fps"], row["beads"], row["z_method"] = fps, n, zm
                            if "error" not in row and row.get("frames_tracked"):
                                row["accuracy"] = accuracy(os.path.join(OUT, name + ".h5"), min(nb, n))
                                say("   accuracy:", fmt(row["accuracy"]))
                            report["runs"].append(row)
                            T.dump(report, "report.json")
        except Exception as e:  # noqa: BLE001
            say(f"RESULT session FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
            report["error"] = f"{type(e).__name__}: {e}"
        finally:
            if api.acq.running():
                api.acq.stop()
            try:
                say("camera rate back:", api.camera.set_rate(rate0, confirm=True))      # initial condition
                if SPEED_FACTOR != 1 or SPEED_MM_S:
                    say("focus speed back:", api.focus.set_speed(report["focus_speed_mm_s"]))
                if ROI:
                    say("camera ROI back:", api.camera.set_roi(*roi0, confirm=True))
                api.devices.disconnect()
                say(f"RESULT disconnect clean; lock {api.rig.status()}")
            except Exception as e:  # noqa: BLE001
                say(f"RESULT disconnect FAILED: {type(e).__name__}: {e}")
    report["error_events"] = [{"kind": e.kind, "extra": e.extra} for e in events.events()
                              if e.kind in ("device_error", "refused", "estop")]
    T.dump(report, "report.json")
    table(report["runs"])
    say(json.dumps(report["error_events"], default=str)[:400])


if __name__ == "__main__":
    main()
