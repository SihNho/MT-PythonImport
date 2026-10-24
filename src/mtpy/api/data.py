"""Run data files (docs/design/api.md 2.3), WP4: open a recorded HDF5 v1 run and export it to the LabVIEW layouts.

    api.acq.start(record=True, name="run01", folder="D:/data")   # recorded frames -> D:/data/run01.h5
    ...
    api.acq.stop()
    run = api.data.open_run("D:/data/run01.h5")
    api.data.export("tra", "D:/data/run01.h5")                    # -> D:/data/run01-000 (LabVIEW .tra layout)
    api.data.export("cal", "D:/data/run01.h5", "D:/data/cal_run01")
"""
from pathlib import Path


def open_run(path):
    """The whole run file as nested dicts (`mtpy.data.read_run`): attrs, mt, beads, segments, recordings, events,
    metadata."""
    from mtpy.data import read_run
    return read_run(path)


def export(kind, path, out=None):
    """Export an HDF5 run file. kind "tra": the `.tra` series (out = base path without suffix, default the .h5 path
    without `.h5`), returns the paths written; kind "cal": the `.cal` file byte for byte (out required), returns it.
    Never overwrites a file (FileExistsError)."""
    from mtpy.data import export_cal, export_tra
    if kind == "tra":
        return export_tra(path, out)
    if kind == "cal":
        if out is None:
            raise ValueError("export('cal', path, out): out is required")
        return export_cal(path, Path(out))
    raise ValueError(f"export kind {kind!r}: 'tra' or 'cal' (HDF5 is the run file itself; .trace and MATLAB later)")
