"""Paths to the recorded fixture and the MT_LabVIEW reference (pinned in third_party/MANIFEST). Tests that need them
skip when they are absent, so the unit tests still run on any PC."""
import json
import os
from pathlib import Path

import numpy as np
import pytest

DATA = Path(os.environ.get("MTPY_DATA", r"G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch"))
MT_LABVIEW = Path(os.environ.get(
    "MTPY_MT_LABVIEW", r"G:\Codes\LabVIEW_Codes\MinLab\zz_LabView VI\AAA_UNIST\2. Tracking\V6_ParallelLoop"))
FIXTURE = DATA / "test"
HARNESS = MT_LABVIEW / "tools" / "gpu" / "harness_inputs.npz"
REFERENCE = MT_LABVIEW / "tools" / "bench" / "fixture_compare_results.jsonl"


def need(*paths):
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"fixture not on this PC: {missing}")


def load_harness_inputs(path=HARNESS):
    """The windows and per-bead calibration cluster LabVIEW handed its kernel (captured by MT_LabVIEW)."""
    z = np.load(path)
    nb = max(int(k[1]) for k in z.files if k.startswith("b") and k[1].isdigit()) + 1
    cals = []
    for b in range(nb):
        c = {n: z[f"b{b}_{n}"] for n in ("forget_radius", "z_step", "cosband", "ampl", "cork", "real")}
        if c["cork"].ndim == 3:                       # COM delivered complex numbers as (re, im) pairs
            c["cork"] = c["cork"][..., 0] + 1j * c["cork"][..., 1]
        if c["cosband"].ndim == 2:
            c["cosband"] = c["cosband"][:, 0] + 1j * c["cosband"][:, 1]
        cals.append(c)
    return z["realspace"], z["hilbert"], cals


def load_reference(path=REFERENCE):
    """The last full session of LabVIEW kernel output: rows of {frame, ff: x1,y1,z1,..., good, pos}."""
    sessions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if "session" in d:
                sessions.append({"meta": d, "frames": []})
            elif sessions:
                sessions[-1]["frames"].append(d)
    full = [s for s in sessions if s["meta"].get("frames", 0) >= 10000]
    return (full or sessions)[-1]["frames"]


def read_image(frame):
    from PIL import Image
    return np.asarray(Image.open(FIXTURE / f"img{frame:05d}.tif"), dtype=np.float64)


@pytest.fixture(scope="session")
def replay():
    need(HARNESS, REFERENCE, FIXTURE / "cal002")
    from mtpy.lvfiles import read_cal
    win_rs, win_h, cals = load_harness_inputs()
    return {"win_rs": win_rs, "win_h": win_h, "cals": cals, "rows": load_reference(),
            "xy0": read_cal(FIXTURE / "cal002")["xy"]}
