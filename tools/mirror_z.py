"""Mirror the tracked z of run files written with the UPWARD z scan (before Requests/Request1, 2026-11-06): that scan
made a rising bead read a lower slice, so z = index x step fell with the extension. The downward scan would have
given slice n - 1 - index, so the repair is the mirror inside the LUT,

    z' = (n_slices - 1) * z_step - z        (0 .. top stays 0 .. top; the LUT's middle stays the middle)

for every tracked cell; the lost marker -1 is kept. Nothing else changes: reference-subtracted extensions only
change sign, offsets and the .tra header stay as they were (MATLAB reads them unchanged).

    python tools/mirror_z.py <run.h5> [<run>-000 ...]

The .h5 gives n_slices and z_step (metadata/calibration) and gets the root attribute `z_mirrored`; a file that has
it is refused (never mirrored twice). Every file is copied to <file>.before-zmirror first."""
import shutil
import sys
from pathlib import Path

import h5py
import numpy as np

from mtpy.lvfiles import read_tra, write_tra

NOTE = ("2026-11-06 Requests/Request1: z -> (n_slices - 1) * z_step - z, the mirror the downward scan would have given "
        "(the upward scan inverted z against the extension); lost cells (-1) kept")


def mirror_h5(path):
    with h5py.File(path, "r+") as f:
        if "z_mirrored" in f.attrs:
            raise SystemExit(f"{path}: already mirrored ({f.attrs['z_mirrored']})")
        n, step = int(f["metadata/calibration/n_slices"][()]), float(f["metadata/calibration/z_step_um"][()])
        top = (n - 1) * step
        z, lost = f["mt/z_um"][:], f["mt/bead_lost"][:].astype(bool)
        tracked = ~lost & (z != -1.0) & np.isfinite(z)
        z[tracked] = top - z[tracked]
        f["mt/z_um"][...] = z
        f.attrs["z_mirrored"] = NOTE
        f.flush()
    return n, step, int(tracked.sum())


def mirror_tra(path, top):
    header, rows = read_tra(path)
    x, y, z = rows[:, 3::3], rows[:, 4::3], rows[:, 5::3]
    tracked = ~((x == -1.0) & (y == -1.0) & (z == -1.0)) & np.isfinite(z)   # the LabVIEW lost marker is x = y = z = -1
    z[tracked] = top - z[tracked]
    rows[:, 5::3] = z
    write_tra(path, header, rows)
    return int(tracked.sum())


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    h5 = Path(argv[0])
    for p in map(Path, argv):
        bak = p.with_name(p.name + ".before-zmirror")
        if bak.exists():
            raise SystemExit(f"{bak} exists: refusing to overwrite a backup")
        shutil.copy2(p, bak)
    n, step, cells = mirror_h5(h5)
    print(f"{h5.name}: n_slices {n}, z_step {step:.10g} um, top {(n - 1) * step:.6f} um, {cells} cells mirrored")
    for p in map(Path, argv[1:]):
        print(f"{p.name}: {mirror_tra(p, (n - 1) * step)} cells mirrored")


if __name__ == "__main__":
    main(sys.argv[1:])
