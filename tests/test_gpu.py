"""The CUDA Z executor must agree with the numba executor for every Z method (skipped without a CUDA device)."""
import numpy as np
import pytest
from conftest import read_image

from mtpy.fast import FastKernel
from mtpy.track import Z_METHODS, lv_round

cuda = pytest.importorskip("numba.cuda")
if not cuda.is_available():
    pytest.skip("no CUDA device", allow_module_level=True)

from mtpy.gpu import GpuKernel, GpuKernel32

CROSS = 120


@pytest.mark.parametrize("z_method", list(Z_METHODS))
def test_gpu_matches_numba(replay, z_method):
    rows, cals = replay["rows"], replay["cals"]
    fk = FastKernel(CROSS, replay["win_rs"], replay["win_h"], cals, z_method=z_method)
    gk = GpuKernel(CROSS, replay["win_rs"], replay["win_h"], cals, z_method=z_method)
    worst, n = 0.0, 0
    for k in range(1, len(rows), 397):
        prev, row = rows[k - 1], rows[k]
        if any(v == -1.0 for v in prev["ff"]):
            continue
        img = read_image(row["frame"]).astype(np.uint8)
        st = np.array(prev["ff"]).reshape(-1, 3)
        xin = [lv_round(v) for v in st[:, 0]]
        yin = [lv_round(v) for v in st[:, 1]]
        a, b = fk.track(img, xin, yin, prev["good"]), gk.track(img, xin, yin, prev["good"])
        assert (a[1] == b[1]).all() and (a[2] == b[2]).all()
        worst = max(worst, float(np.abs(a[0] - b[0]).max()))
        n += 1
    print(f"{z_method}: {n} frames, gpu vs numba {worst:.2e}")
    assert n > 20 and worst < 1e-9        # the GPU band-pass is a direct DFT, the CPU's an FFT: rounding only


@pytest.mark.parametrize("z_method", list(Z_METHODS))
def test_gpu_fp32_within_the_0030_limits(replay, z_method):
    """Decision 0030: the FP32 kernel is judged by measurement against current_v1 numba FP64 - no LUT index jump,
    z within 0.01 nm (spline: 0.5 nm, its golden section on an FP32 SSD) and xy within 1e-4 px on the replay
    frames (offline 2026-11-07: 0.0018 / 0.13 / 0.0018 nm and 2e-6 px worst)."""
    rows, cals = replay["rows"], replay["cals"]
    fk = FastKernel(CROSS, replay["win_rs"], replay["win_h"], cals, z_method=z_method)
    gk = GpuKernel32(CROSS, replay["win_rs"], replay["win_h"], cals, z_method=z_method)
    assert (gk.executor, gk.precision) == ("cuda", "fp32")
    worst_z = worst_xy = 0.0
    n = 0
    for k in range(1, len(rows), 397):
        prev, row = rows[k - 1], rows[k]
        if any(v == -1.0 for v in prev["ff"]):
            continue
        img = read_image(row["frame"]).astype(np.uint8)
        st = np.array(prev["ff"]).reshape(-1, 3)
        xin = [lv_round(v) for v in st[:, 0]]
        yin = [lv_round(v) for v in st[:, 1]]
        a, b = fk.track(img, xin, yin, prev["good"]), gk.track(img, xin, yin, prev["good"])
        assert (a[1] == b[1]).all() and (a[2] == b[2]).all()          # the same slice, the same good flags
        worst_z = max(worst_z, float(np.abs(a[0][:, 2] - b[0][:, 2]).max()) * 1000.0)
        worst_xy = max(worst_xy, float(np.abs(a[0][:, :2] - b[0][:, :2]).max()))
        n += 1
    print(f"{z_method}: {n} frames, fp32 vs numba z {worst_z:.2e} nm, xy {worst_xy:.2e} px")
    z_limit = 0.5 if z_method.startswith("spline") else 0.01     # the SSD / NCC minimum's position is FP32-limited (0.13 nm seen)
    assert n > 20 and worst_z < z_limit and worst_xy < 1e-4


def test_acquisition_records_fp32_for_the_gpu_by_default(tmp_path):
    """Decision 0030: gpu=True means the FP32 kernel unless precision="fp64" is asked; the start event says so."""
    from conftest import FIXTURE

    from mtpy import api
    from mtpy.api import events
    api.devices.connect({"backend": "sim"})
    try:
        api.beads.select([1, 2], cal_path=str(FIXTURE / "cal002"))
        api.acq.start(record=False, name="p32", gpu=True)
        ev = [e for e in events.events() if e.kind == "acquisition" and e.extra.get("action") == "start"][-1].extra
        assert (ev["z_method"], ev["executor"], ev["precision"]) == ("current_v1", "cuda", "fp32")
        api.acq.stop()
        api.acq.start(record=False, name="p64", gpu=True, precision="fp64", z_method="spline")
        ev = [e for e in events.events() if e.kind == "acquisition" and e.extra.get("action") == "start"][-1].extra
        assert (ev["z_method"], ev["executor"], ev["precision"]) == ("spline_v1", "cuda", "fp64")
        api.acq.stop()
    finally:
        api.devices.disconnect()
