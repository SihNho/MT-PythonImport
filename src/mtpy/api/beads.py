"""Bead selection (docs/design/api.md 2.4), minimal WP3 version: the beads picked in a LabVIEW `.cal` file, with their
calibration-time positions and calibration clusters. Bead finding (`find`, U23) and roles (`set_role`) come later.

    api.beads.select([1, 2, 3, 4, 5])          # cal file from the simulated camera's fixture folder
    api.beads.select([1, 3], cal_path="D:/run/cal002")

Bead ids are 1-based, as in the `.cal` and `.tra` files (bead 1 = x1, y1, z1).
"""
from pathlib import Path

from mtpy import calib
from mtpy.acq import Beads

from . import events
from .errors import NotReady

_selected = None


def _fixture_cal():
    from .devices import service
    src = getattr(service("camera").device, "source", "")
    cals = sorted(Path(src).glob("cal*")) if src and Path(src).is_dir() else []
    if not cals:
        raise NotReady("no calibration file: the simulated camera has no fixture folder with a cal* file; "
                       "pass cal_path=")
    return cals[0]


def _camera_roi():
    """The camera ROI read back now, or None when no camera is connected (U23, WP6: kept with the selection and its
    origin compared at api.acq.start, since bead positions are ROI pixels)."""
    from .devices import _services
    svc = _services.get("camera")
    if svc is None or not svc.connected:
        return None
    return tuple(int(v) for v in svc.call(svc.device.settings, what="read settings")["roi"])


def select(ids, cal_path=None):
    """Select beads by their 1-based id in the `.cal` file and load their calibration (positions in px and the
    calibration clusters). cal_path None: the first `cal*` file in the simulated camera's fixture folder.
    The camera ROI read back now is kept with the selection (WP6 / U23): api.acq.start refuses a camera whose ROI
    origin differs from it (None when no camera is connected: then only the size is checked at start).
    Refused (NotReady) while acquisition runs. Returns {id: {"x_px", "y_px"}} (calibration-time positions)."""
    global _selected
    from mtpy.lvfiles import read_cal

    from . import acq
    if acq.running():
        raise NotReady("beads cannot change while acquisition runs; api.acq.stop() first")
    path = Path(cal_path) if cal_path is not None else _fixture_cal()
    cal = read_cal(path)
    n = len(cal["stack"])
    ids = tuple(ids)
    if not ids or len(set(ids)) != len(ids) or not all(isinstance(i, int) and 1 <= i <= n for i in ids):
        raise ValueError(f"bead ids must be distinct integers 1..{n} (the beads of {path.name}); got {ids!r}")
    clusters = calib.clusters(cal)
    cross = cal["stack"].shape[2] + 1
    win_rs, win_h = calib.windows(cross)
    idx = [i - 1 for i in ids]
    roi = _camera_roi()
    _selected = Beads(ids, cal["xy"][idx, :2].copy(), [clusters[i] for i in idx], cross, win_rs, win_h, str(path),
                      roi)
    events.log("beads", request={"select": list(ids)}, cal=str(path), roi=roi)
    return {i: {"x_px": float(x), "y_px": float(y)} for i, (x, y) in zip(ids, _selected.xy0)}


def selected():
    """The selected `mtpy.acq.Beads`, or None."""
    return _selected
