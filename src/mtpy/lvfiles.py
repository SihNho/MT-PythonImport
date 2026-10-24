"""Readers and writers for the LabVIEW `.tra` and `.cal` files, byte-identical to what LabVIEW writes
(decision 0006; layouts in docs/format/tra-cal.md)."""
import struct
from pathlib import Path

import numpy as np

ENCODING = "cp949"                      # header and date strings are written in the Korean Windows code page
WEEKDAYS = "월화수목금토일"   # Monday..Sunday as LabVIEW's %a writes them in this locale


# ------------------------------------------------------------------------------------------------------- .tra ---
def read_tra(path):
    """Returns (header text, rows). rows[:, 0] frame, [:, 1] magnet, [:, 2] rotor, then x, y, z per bead."""
    b = Path(path).read_bytes()
    n = struct.unpack("<I", b[:4])[0]
    rows, cols = struct.unpack("<II", b[4 + n:12 + n])
    data = np.frombuffer(b, dtype="<f8", count=rows * cols, offset=12 + n).reshape(rows, cols)
    if 12 + n + 8 * rows * cols != len(b):
        raise ValueError(f"{path}: {len(b)} bytes, expected {12 + n + 8 * rows * cols}")
    return b[4:4 + n].decode(ENCODING), data.astype(np.float64)


def write_tra(path, header, rows):
    h = header.encode(ENCODING)
    rows = np.ascontiguousarray(rows, dtype="<f8")
    with open(path, "wb") as f:
        f.write(struct.pack("<I", len(h)) + h + struct.pack("<II", *rows.shape) + rows.tobytes())


def tra_header(created, cal_path, file_index, n_actual, n_nominal):
    """The header text LabVIEW writes; `created` is a datetime."""
    return (f"{WEEKDAYS[created.weekday()]} {created:%Y-%m-%d %H:%M:%S}\n"
            "Raw data file of N bead xyz trace\n"
            f"cal cluster:\n{cal_path}\n"
            f"file {file_index} of a series\n"
            f"actual data points/nominal: {n_actual}/{n_nominal}\n"
            "Data follows in order:\ntime, trans, rot x1,y1,z1,x2,y2,z2,....\n"
            "NOTE: x,y are msd in PIXELS;\nz is measured in UNCORRECTED nm\n"
            "(the index difference of oil/water is not in z!)")


# ------------------------------------------------------------------------------------------------------- .cal ---
class _Reader:
    def __init__(self, b):
        self.b, self.o = b, 0

    def i32s(self, k):
        v = struct.unpack_from(f">{k}i", self.b, self.o)
        self.o += 4 * k
        return v

    def i32(self):
        return self.i32s(1)[0]

    def f8(self, count):
        v = np.frombuffer(self.b, dtype=">f8", count=count, offset=self.o).astype(np.float64)
        self.o += 8 * count
        return v


def read_cal(path):
    """Returns a dict: xy (n, 2) picked bead positions, stack (n, S, L) radial-profile stack, n_slices, bead_i32 (n, 3),
    z_step (um), n_avg, date (text), bead_flags (n,), nm_per_px."""
    r = _Reader(Path(path).read_bytes())
    n, m = r.i32s(2)
    xy = r.f8(n * m).reshape(n, m)
    n2, S, L = r.i32s(3)
    stack = r.f8(n2 * S * L).reshape(n2, S, L)
    n_slices = r.i32()
    k, c = r.i32s(2)
    bead_i32 = np.array(r.i32s(k * c), dtype=np.int32).reshape(k, c)
    z_step = float(r.f8(1)[0])
    n_avg = r.i32()
    ln = r.i32()
    date = r.b[r.o:r.o + ln].decode(ENCODING)
    r.o += ln
    k = r.i32()
    flags = np.array(r.i32s(k), dtype=np.int32)
    nm_per_px = float(r.f8(1)[0])
    if r.o != len(r.b):
        raise ValueError(f"{path}: {len(r.b) - r.o} bytes left after the tail")
    return {"xy": xy, "stack": stack, "n_slices": n_slices, "bead_i32": bead_i32, "z_step": z_step, "n_avg": n_avg,
            "date": date, "bead_flags": flags, "nm_per_px": nm_per_px}


def write_cal(path, cal):
    xy, stack, bi, flags = cal["xy"], cal["stack"], np.asarray(cal["bead_i32"]), np.asarray(cal["bead_flags"])
    date = cal["date"].encode(ENCODING)
    out = [struct.pack(">2i", *xy.shape), np.asarray(xy, ">f8").tobytes(),
           struct.pack(">3i", *stack.shape), np.asarray(stack, ">f8").tobytes(),
           struct.pack(">i", cal["n_slices"]), struct.pack(">2i", *bi.shape), bi.astype(">i4").tobytes(),
           struct.pack(">d", cal["z_step"]), struct.pack(">i", cal["n_avg"]), struct.pack(">i", len(date)), date,
           struct.pack(">i", len(flags)), flags.astype(">i4").tobytes(), struct.pack(">d", cal["nm_per_px"])]
    with open(path, "wb") as f:
        f.write(b"".join(out))
