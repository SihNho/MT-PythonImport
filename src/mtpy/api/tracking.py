"""Tracking results (docs/design/api.md 2.4), WP3: the latest position of a bead. Zeroing, exclusions and swappable
stages come later.

    api.tracking.latest(1)    # {'x_px': ..., 'y_px': ..., 'z_um': ..., 'good': True, 'buffer_number': ..., ...}
"""
from .errors import NotReady

UNCERTAINTY_NOTE = "not yet computed"     # U34: per-frame uncertainty is a later work package; no number is invented


def latest(bead):
    """Latest x, y (px) and z (um) of bead `bead` (1-based id) from the running (or last) acquisition, with its frame
    (segment, buffer number, camera time). -1.0 marks a lost bead, as in LabVIEW. The per-frame uncertainty is
    None with the note "not yet computed". NotReady before the first tracked frame or for a bead not selected."""
    from . import acq
    pipe = acq._pipe or acq._last
    res = pipe.latest() if pipe is not None else None
    if res is None or res.xyz is None:
        raise NotReady("no tracked frame yet: select beads (api.beads.select) and start acquisition (api.acq.start)")
    if bead not in res.bead_ids:
        raise NotReady(f"bead {bead!r} is not tracked; tracked beads: {list(res.bead_ids)}")
    i = res.bead_ids.index(bead)
    x, y, z = (float(v) for v in res.xyz[i])
    r = res.record
    return {"x_px": x, "y_px": y, "z_um": z, "good": bool(res.good[i]), "segment": r.segment,
            "buffer_number": r.buffer_number, "t_camera_s": r.t_camera_s, "t_source": r.t_source,
            "uncertainty": None, "uncertainty_note": UNCERTAINTY_NOTE}
