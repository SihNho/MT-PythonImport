import datetime

import numpy as np
import pytest
from conftest import DATA, FIXTURE, need

from mtpy.lvfiles import read_cal, read_tra, tra_header, write_cal, write_tra

TRA = [DATA / "tra001-000", FIXTURE / "tra002-000"]
CAL = [DATA / "cal001", FIXTURE / "cal002"]


def test_tra_roundtrip_synthetic(tmp_path):
    rows = np.arange(36, dtype=float).reshape(3, 12) / 7
    hdr = tra_header(datetime.datetime(2026, 9, 7, 0, 34, 54), r"C:\x\cal001", 0, 3, 2000000)
    write_tra(tmp_path / "t", hdr, rows)
    h2, r2 = read_tra(tmp_path / "t")
    assert h2 == hdr and np.array_equal(r2, rows)


@pytest.mark.parametrize("path", TRA, ids=lambda p: p.name)
def test_tra_byte_identical(path, tmp_path):
    need(path)
    hdr, rows = read_tra(path)
    write_tra(tmp_path / "t", hdr, rows)
    assert (tmp_path / "t").read_bytes() == path.read_bytes()
    lines = hdr.split("\n")
    created = datetime.datetime.strptime(lines[0][2:], "%Y-%m-%d %H:%M:%S")
    n_act, n_nom = lines[5].split(": ")[1].split("/")
    assert tra_header(created, lines[3], 0, int(n_act), int(n_nom)) == hdr
    assert int(n_act) == len(rows)


@pytest.mark.parametrize("path", CAL, ids=lambda p: p.name)
def test_cal_byte_identical(path, tmp_path):
    need(path)
    cal = read_cal(path)
    assert cal["stack"].shape[1:] == (60, 119) and cal["z_step"] == pytest.approx(0.1) and cal["nm_per_px"] == 84.0
    write_cal(tmp_path / "c", cal)
    assert (tmp_path / "c").read_bytes() == path.read_bytes()
