import datetime

import numpy as np
import pytest
from conftest import DATA, FIXTURE, need

from mtpy.lvfiles import cal_date, read_cal, read_tra, tra_header, write_cal, write_tra

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



def test_cal_date_as_labview_writes_it():
    """Owner 2026-11-05: the .cal must stay the LabVIEW file; its date string is the long Korean date and a 12-hour
    time, neither zero-padded, each ended by CR (read from the 2023-2026 files)."""
    assert cal_date(datetime.datetime(2024, 7, 19, 10, 10, 34)) == "2024\ub144 7\uc6d4 19\uc77c \uae08\uc694\uc77c\r\uc624\uc804 10:10:34\r"
    assert cal_date(datetime.datetime(2023, 7, 28, 15, 5, 32)) == "2023\ub144 7\uc6d4 28\uc77c \uae08\uc694\uc77c\r\uc624\ud6c4 3:05:32\r"
    assert cal_date(datetime.datetime(2024, 7, 10, 0, 12, 16)).endswith("\r\uc624\uc804 12:12:16\r")
