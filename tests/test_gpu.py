"""The CUDA Z executor must agree with the numba executor for every Z method (skipped without a CUDA device)."""
import numpy as np
import pytest
from conftest import read_image

from mtpy.fast import FastKernel
from mtpy.track import Z_METHODS, lv_round

cuda = pytest.importorskip("numba.cuda")
if not cuda.is_available():
    pytest.skip("no CUDA device", allow_module_level=True)

from mtpy.gpu import GpuKernel

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
