"""WP6: the walking skeleton end to end (tools/walking_skeleton.py) - simulators and files only. Needs the recorded G:
fixture (frames and `cal002`, for beads incl. the reference bead) and skips without it."""
import importlib.util
from pathlib import Path

import pytest
from conftest import FIXTURE, need

from mtpy.api import safety

REPO = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("walking_skeleton", REPO / "tools" / "walking_skeleton.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("estop_variant", [False, True], ids=["protocol", "estop"])
def test_walking_skeleton(tmp_path, estop_variant):
    need(FIXTURE / "cal002", FIXTURE / "img00004.tif")
    before = (safety.CONFIG, safety.profile()["version"])
    r = _tool().run(tmp_path / "out", fixture=FIXTURE, estop_variant=estop_variant)
    assert r.ok, "\n".join(f"{c['check']}: {c['detail']}" for c in r.failed)
    assert len(r.checks) == (19 if estop_variant else 17)
    assert (safety.CONFIG, safety.profile()["version"]) == before          # the tool restored the profile in force
