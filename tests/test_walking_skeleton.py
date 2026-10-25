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
    assert len(r.checks) == (21 if estop_variant else 18)          # + the default-equation check (decision 0018)
    assert (safety.CONFIG, safety.profile()["version"]) == before          # the tool restored the profile in force


def _tree(folder):
    return sorted((str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*"))


def test_destination_overlapping_the_repository_config_is_refused_before_writing(tmp_path, monkeypatch):
    """Review l2s-wp6-r1: <out>/config equal to, inside, or containing the repository's config/ is refused before
    anything is written; the shipped files are untouched."""
    tool, cfg = _tool(), REPO / "config"
    before = _tree(cfg)
    for out in (REPO, cfg, cfg / "safety_profiles"):            # <out>/config = config/, or inside it
        with pytest.raises(ValueError, match="overlap"):
            tool.run(out, fixture=FIXTURE)
    assert _tree(cfg) == before
    monkeypatch.setattr(tool, "REPO", tmp_path / "x" / "config" / "repo")    # <out>/config would contain it
    with pytest.raises(ValueError, match="overlap"):
        tool.run(tmp_path / "x", fixture=FIXTURE)
    assert not (tmp_path / "x").exists()


def test_existing_config_in_the_destination_is_refused_and_kept(tmp_path):
    out = tmp_path / "out"
    (out / "config").mkdir(parents=True)
    keep = out / "config" / "mine.json"
    keep.write_text('{"keep": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        _tool().run(out, fixture=FIXTURE)
    assert keep.read_text(encoding="utf-8") == '{"keep": true}' and [p.name for p in out.iterdir()] == ["config"]
