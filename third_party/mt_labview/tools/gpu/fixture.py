"""fixture.py - NumPy access to the recorded fixture (no LabVIEW):
  * cal002  : LabVIEW flattened data, big-endian. [I32 n][I32 2] n x 2 DBL bead (x, y); [I32 n][I32 S][I32 L] n x S x L DBL
              calibration stack (S slices, L = cross-1 = mirrored radial profile per slice); then a tail (see tail_fields).
  * tra002-000 : [U32 hdr_len][hdr bytes] then little-endian DBL: 1 lead value, rows of 18 (frame, trans, rot, x1,y1,z1..x5,y5,z5).
  * img%05d.tif : 1280 x 1024 8-bit (PIL).
  * tools/bench/fixture_compare_results.jsonl : per-frame CPU-kernel reference (x,y,z of the four-fold/v3 kernels, good flags,
              cal index) produced by run_fixture_compare.py - the acceptance reference for the NumPy/CUDA ports.
"""
import json
import os
import struct

import numpy as np

DATA = r"G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch\test"
CAL = os.path.join(DATA, "cal002")
TRA = os.path.join(DATA, "tra002-000")
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(os.path.dirname(HERE), "bench", "fixture_compare_results.jsonl")


def read_cal(path=CAL):
    b = open(path, "rb").read()
    n, m = struct.unpack(">ii", b[:8]); o = 8
    xy = np.frombuffer(b, dtype=">f8", count=n * m, offset=o).reshape(n, m).astype(np.float64); o += 8 * n * m
    n2, S, L = struct.unpack(">iii", b[o:o + 12]); o += 12
    assert n2 == n, (n, n2)
    stack = np.frombuffer(b, dtype=">f8", count=n * S * L, offset=o).reshape(n, S, L).astype(np.float64); o += 8 * n * S * L
    tail = b[o:]
    return {"n_beads": n, "xy": xy, "n_slices": S, "profile_len": L, "stack": stack, "tail": tail, "tail_fields": tail_fields(tail)}


def tail_fields(t):
    """Best-effort decode of the 155-byte tail (verified fields only: leading I32s, the DBL 0.1 z-step, the I32 20 averages,
    the trailing DBL 84.0 nm/px). Everything else is returned raw for the loader-VI wiring read to settle."""
    out = {"i32_head": list(struct.unpack(">3i", t[:12]))}
    o = 12
    per = []
    for _ in range(out["i32_head"][1]):
        per.append(list(struct.unpack(">3i", t[o:o + 12]))); o += 12
    out["per_bead_i32"] = per
    out["dbl_a"] = struct.unpack(">d", t[o:o + 8])[0]; o += 8
    out["i32_b"] = struct.unpack(">i", t[o:o + 4])[0]; o += 4
    slen = struct.unpack(">i", t[o:o + 4])[0]; o += 4
    out["string"] = t[o:o + slen].decode("latin-1"); o += slen
    k = (len(t) - o - 8) // 4
    out["rest_i32"] = list(struct.unpack(">%di" % k, t[o:o + 4 * k]))
    out["dbl_last"] = struct.unpack(">d", t[-8:])[0]
    return out


def read_tra(path=TRA):
    b = open(path, "rb").read()
    n = struct.unpack("<I", b[:4])[0]
    hdr = b[4:4 + n].decode("latin-1", errors="replace")
    vals = np.frombuffer(b, dtype="<f8", offset=4 + n)
    rows = vals[1:1 + 18 * ((len(vals) - 1) // 18)].reshape(-1, 18)
    return hdr, rows          # rows[:,0] frame, [:,1] trans, [:,2] rot, [:,3:18] x1,y1,z1..x5,y5,z5


def read_image(frame, data=DATA):
    from PIL import Image
    im = Image.open(os.path.join(data, f"img{frame:05d}.tif"))
    return np.asarray(im, dtype=np.float64)     # (rows=1024, cols=1280), 8-bit values


def read_reference(path=REF):
    """The last complete session in the jsonl (the 2026-09-07 --reseed=main full run): {"meta", "frames": [row dicts]},
    row = {frame, same, dt, v3, ff, tra, good, pos, dev_vs_tra} (ff = four-fold kernel x1,y1,z1,...; good/pos per bead)."""
    sessions = []
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        if "session" in d:
            sessions.append({"meta": d, "frames": []})
        elif sessions:
            sessions[-1]["frames"].append(d)
    full = [s for s in sessions if s["meta"].get("frames", 0) >= 10000]
    return (full or sessions)[-1]


if __name__ == "__main__":
    import sys; sys.stdout.reconfigure(errors="replace")
    c = read_cal()
    print("cal:", c["n_beads"], "beads", c["xy"].tolist(), "stack", c["stack"].shape, "tail", c["tail_fields"])
    hdr, rows = read_tra()
    print("tra rows", rows.shape, "first frame", rows[0, :6], "header:", hdr[:160].replace("\r", " ").replace("\n", " | "))
    ref = read_reference()
    print("reference session", ref["meta"], "frames", len(ref["frames"]), "first", ref["frames"][0])
    im = read_image(int(rows[0, 0]))
    print("image", im.shape, im.min(), im.max())
# ---
# labview: none
# hardware: none
# ---
