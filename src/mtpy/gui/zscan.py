"""Calibration z scan from the GUI (spec F3.02): step the focus, average frames at each slice, take each bead's
radial profile as the tracker does, write a LabVIEW-compatible `.cal` (lvfiles.write_cal). Frames come from the
display tap of the running acquisition (api.acq.display), so acquisition must be running; the focus moves go through
api.focus (refused unless the safety profile has a focus window).
shortcut: the simulated camera's image does not change with focus, so a .cal made on the simulator is flat (every
slice alike); it exercises the flow only. Real slices come with phase 6."""
import time
from datetime import datetime

import numpy as np

from mtpy import api, calib, track
from mtpy.lvfiles import write_cal


def mean_image(n_avg, timeout_s=10.0):
    """The mean of the next n_avg distinct display snapshots (float64)."""
    acc, seen, t_end = None, set(), time.monotonic() + timeout_s
    while len(seen) < n_avg:
        snap = api.acq.display()
        if snap is None or snap.seq in seen:
            if time.monotonic() > t_end:
                raise TimeoutError(f"only {len(seen)} of {n_avg} frames in {timeout_s} s: is acquisition running?")
            time.sleep(0.005)
            continue
        seen.add(snap.seq)
        img = snap.image.astype(np.float64)
        acc = img if acc is None else acc + img
    return acc / n_avg


def bead_profile(image, x, y, cross):
    """XY (Croquette) then the mirrored radial profile (length cross - 1) of one bead at (x, y) px, as the tracker."""
    h = track.lv_round(cross * 0.6)
    half = cross // 2
    xi, yi = int(np.rint(x)), int(np.rint(y))
    sub = image[yi - h:yi + h, xi - h:xi + h]
    win_rs, win_h = calib.windows(cross)
    xo, yo, sx, sy = track.xy_croquette(sub, h, xi, yi, cross, win_rs, win_h, track.DEFAULT)
    prof = track.radial_profile(sub, h + sx, h + sy, half)
    return xo, yo, np.concatenate([prof[1:][::-1], prof])


def run(path, xy, slices=60, step_nm=100.0, n_avg=20, cross=120, nm_per_px=84.0, progress=None):
    """Scan `slices` focus positions `step_nm` apart centred on the current focus, write the .cal to `path`, return
    the focus to where it was. xy: (n, 2) bead positions in px. progress(i, slices) is called per slice."""
    xy = np.asarray(xy, dtype=np.float64)
    z0 = api.focus.position()
    step_um = step_nm / 1000.0
    stack = np.zeros((len(xy), slices, cross - 1))
    try:
        for s in range(slices):
            api.focus.move_to(z0 + (s - slices // 2) * step_um).wait(10)
            img = mean_image(n_avg)
            for b, (x, y) in enumerate(xy):
                stack[b, s] = bead_profile(img, x, y, cross)[2]
            if progress:
                progress(s + 1, slices)
    finally:
        api.focus.move_to(z0).wait(10)
    cal = {"xy": xy, "stack": stack, "n_slices": slices,
           "bead_i32": np.array([[int(np.rint(x)), int(np.rint(y)), cross] for x, y in xy], dtype=np.int32),
           "z_step": step_um, "n_avg": n_avg, "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "bead_flags": np.zeros(len(xy), dtype=np.int32), "nm_per_px": nm_per_px}
    write_cal(path, cal)
    api.events.log("calibration", request={"slices": slices, "step_nm": step_nm, "n_avg": n_avg, "cross": cross},
                   path=str(path), beads=len(xy))
    return cal
