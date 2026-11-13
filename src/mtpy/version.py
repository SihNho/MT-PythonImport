"""The version of the code that runs (owner 2026-11-13: every data file must name the code that wrote it).

`code_version()` -> {"version", "commit", "branch", "dirty", "remote"}: the release number of pyproject.toml
(bumped at every code change, the `release` skill) and the git commit of the working tree, read once per process - the code a process
runs is the code it loaded at its start; `remote` is the address of the repository
(origin) where that commit is found. A field that cannot be read is None (no git, an installed copy).
"""
import functools
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE_PATHS = ("src", "tools", "config", "pyproject.toml")


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


@functools.lru_cache(maxsize=1)
def code_version():
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        m = None
    status = _git("status", "--porcelain", "--untracked-files=no", "--", *CODE_PATHS)
    return {"version": m.group(1) if m else None, "commit": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"), "remote": _git("remote", "get-url", "origin"),
            "dirty": None if status is None else bool(status)}     # True: code edited since that commit
