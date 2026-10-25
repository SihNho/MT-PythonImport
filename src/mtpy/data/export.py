"""Export an HDF5 v1 run file to the LabVIEW `.tra` / `.cal` layouts the existing MATLAB analysis reads (decisions
0006 item 1 and 0011; layouts in docs/format/tra-cal.md, written with `mtpy.lvfiles`).

`.tra` rows are the tracked frames only (pipeline drops and frames whose tracking raised have no positions and are
left out, so they show as gaps in the frame column, as lost frames do in LabVIEW's files). Column 0, the frame
number (decision 0016 item 4 as refined by the owner, 2026-10-25), runs over the whole FILE and never restarts:
- 0 = the first recorded frame of the run (its first `/mt` row, a dropped or untracked one included, so gaps show);
- within a segment, frame = buffer_number - the segment's base (its first recorded buffer number) + the segment's
  offset, so a recording off / on gap inside a segment stays a visible jump (time information kept);
- across segments (buffer numbers restart at every camera start) the numbers continue: a segment's first recorded
  frame = the previous segment's last recorded frame number + 1 (the frames between segments cannot be counted, so
  the boundary is counted as one step).
One `.tra` series per run, `<base>-000`, `<base>-001`, ... as LabVIEW (no per-segment split, so the `.cal` ~ `.tra`
naming stays intact), split every `nominal` rows (LabVIEW: 2,000,000), `file k of a series`.
Column 1 is the magnet position (mm) and column 2 the rotor (deg) last read before the frame: since WP6 from the
acquisition's motor poller (`api.acq`, a reading every 50 ms and one before the first frame) and every move's
read-back; NaN only without a reading (e.g. a motor not connected).
"""
import datetime
import hashlib
from pathlib import Path

import h5py
import numpy as np

from mtpy.api.errors import NotReady
from mtpy.lvfiles import tra_header, write_tra

from .hdf5 import mt_rows

NOMINAL = 2_000_000


def legacy_matrix(path, segment=None):
    """{segment: rows} with the `.tra` columns: frame (file-wide, see the module text: 0 = the run's first recorded
    frame, continuing +1 across segments), magnet (mm), rotor (deg), then x, y, z per bead (the /beads order); only
    tracked frames. segment: one segment number, or None for every segment with tracked rows. `legacy_rows` joins
    them into the one matrix the `.tra` series holds."""
    with h5py.File(path, "r") as f:
        if "mt" not in f:
            return {}
        mt, n = f["mt"], mt_rows(f)                 # a crashed file: rows of an unfinished flush left out (WP6)
        seg, buf = mt["segment"][:n], mt["buffer_number"][:n].astype(np.int64)
        ok = (mt["dropped"][:n] == 0) & (mt["track_error"][:n] == 0)
        n_beads = int(mt.attrs["n_beads"])
        xyz = [mt[k][:n] for k in ("x_px", "y_px", "z_um")] if n_beads else []
        mag, rot = mt["magnet_mm"][:n], mt["rotor_deg"][:n]
    shift, nxt = {}, 0                               # frame = buffer + shift[segment]
    for s in sorted(set(seg.tolist())):
        b = buf[seg == s]
        shift[s] = nxt - int(b.min())                # the segment's first recorded frame = previous last + 1
        nxt = int(b.max()) + shift[s] + 1
    out = {}
    for s in sorted(shift) if segment is None else [segment]:
        sel = ok & (seg == s)
        if not sel.any():
            continue
        cols = [buf[sel] + shift[s], mag[sel], rot[sel]]
        for i in range(n_beads):
            cols += [xyz[0][sel, i], xyz[1][sel, i], xyz[2][sel, i]]
        order = np.argsort(buf[sel], kind="stable")
        out[s] = np.column_stack(cols).astype(np.float64)[order]
    return out


def legacy_rows(path):
    """The rows of the run's one `.tra` series: every segment of legacy_matrix() in segment order (frame numbers
    already continue across segments), or None when no frame was tracked."""
    mats = legacy_matrix(path)
    return np.vstack([mats[s] for s in sorted(mats)]) if mats else None


def export_tra(path, base=None, nominal=NOMINAL):
    """Write the `.tra` file(s) of an HDF5 run file. base: output path without suffix (default: the .h5 path
    without `.h5`). Returns the paths written. Refuses (FileExistsError) to overwrite a file."""
    path = Path(path)
    base = Path(base) if base is not None else path.with_suffix("")
    with h5py.File(path, "r") as f:
        t0 = float(f.attrs["t0_unix"])
        cal = f.attrs.get("legacy_cal_file", "")
        cal = cal.decode() if isinstance(cal, bytes) else str(cal)
    created = datetime.datetime.fromtimestamp(t0).replace(microsecond=0)   # local time, as LabVIEW's header
    rows = legacy_rows(path)
    if rows is None:
        raise NotReady(f"{path}: no tracked frames to export")
    outs = [Path(f"{base}-{k:03d}") for k in range((len(rows) + nominal - 1) // nominal)]
    for out in outs:                                 # checked before writing anything: never a partial series
        if out.exists():
            raise FileExistsError(f"{out} exists; export never overwrites")
    for k, out in enumerate(outs):
        part = rows[k * nominal:(k + 1) * nominal]
        write_tra(out, tra_header(created, cal, k, len(part), nominal), part)
    return outs


def export_cal(path, out):
    """Write the `.cal` file stored in the run file byte for byte (checked against its sha256). Returns out."""
    out = Path(out)
    with h5py.File(path, "r") as f:
        g = f["metadata/calibration"]
        if "cal_bytes" not in g:
            raise NotReady(f"{path}: no .cal content stored ({g.attrs.get('note', '')})")
        raw = g["cal_bytes"][()].tobytes()
        sha = g["sha256"][()]
    sha = sha.decode() if isinstance(sha, bytes) else sha
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError(f"{path}: stored .cal content does not match its sha256")
    if out.exists():
        raise FileExistsError(f"{out} exists; export never overwrites")
    out.write_bytes(raw)
    return out
