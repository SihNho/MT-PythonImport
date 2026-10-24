"""Export an HDF5 v1 run file to the LabVIEW `.tra` / `.cal` layouts the existing MATLAB analysis reads (decisions
0006 item 1 and 0011; layouts in docs/format/tra-cal.md, written with `mtpy.lvfiles`).

`.tra` rows are the tracked frames only (pipeline drops and frames whose tracking raised have no positions and are
left out, so they show as gaps in the frame column, as lost frames do in LabVIEW's files). Column 0 is
`buffer_number - first buffer number of its segment`; buffer numbers restart in every segment, so a run with more
than one segment gives one `.tra` series per segment (`<base>-s<segment>-000`, ...); a one-segment run gives
`<base>-000`, ... as LabVIEW. A series is split every `nominal` rows (LabVIEW: 2,000,000), `file k of a series`.
Column 1 is the magnet position (mm) and column 2 the rotor (deg) last read before the frame (NaN before the first
reading: the writer has no motor polling yet).
"""
import datetime
import hashlib
from pathlib import Path

import h5py
import numpy as np

from mtpy.api.errors import NotReady
from mtpy.lvfiles import tra_header, write_tra

NOMINAL = 2_000_000


def _segment_first(f):
    seg = f["segments"]
    return dict(zip(seg["number"][()].tolist(), seg["first_buffer"][()].tolist()))


def legacy_matrix(path, segment=None):
    """{segment: rows} with the `.tra` columns: frame, magnet (mm), rotor (deg), then x, y, z per bead (the
    /beads order); only tracked frames. segment: one segment number, or None for every segment with rows."""
    with h5py.File(path, "r") as f:
        if "mt" not in f:
            return {}
        mt = f["mt"]
        seg, buf = mt["segment"][()], mt["buffer_number"][()].astype(np.int64)
        ok = (mt["dropped"][()] == 0) & (mt["track_error"][()] == 0)
        n_beads = int(mt.attrs["n_beads"])
        xyz = [mt[k][()] for k in ("x_px", "y_px", "z_um")] if n_beads else []
        mag, rot = mt["magnet_mm"][()], mt["rotor_deg"][()]
        firsts = _segment_first(f)
    out = {}
    for s in sorted(set(seg.tolist()) if segment is None else {segment}):
        sel = ok & (seg == s)
        if not sel.any():
            continue
        first = firsts.get(s, -1)
        if first < 0:                               # segment end never received: the smallest recorded buffer
            first = int(buf[seg == s].min())
        cols = [buf[sel] - first, mag[sel], rot[sel]]
        for i in range(n_beads):
            cols += [xyz[0][sel, i], xyz[1][sel, i], xyz[2][sel, i]]
        order = np.argsort(buf[sel], kind="stable")
        out[s] = np.column_stack(cols).astype(np.float64)[order]
    return out


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
    mats = legacy_matrix(path)
    if not mats:
        raise NotReady(f"{path}: no tracked frames to export")
    written = []
    for s, rows in mats.items():
        stem = f"{base}-s{s}" if len(mats) > 1 else str(base)
        for k, start in enumerate(range(0, len(rows), nominal)):
            part = rows[start:start + nominal]
            out = Path(f"{stem}-{k:03d}")
            if out.exists():
                raise FileExistsError(f"{out} exists; export never overwrites")
            write_tra(out, tra_header(created, cal, k, len(part), nominal), part)
            written.append(out)
    return written


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
