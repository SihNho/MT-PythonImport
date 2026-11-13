"""release_pending.py - Stop hook: a code change is not left without a version and a commit on GitHub.

Owner 2026-11-13: "at every code change, change the version number and put it on GitHub - as a skill and a hook"
(so an old version can be looked up and a data file can name the code that wrote it). When the turn ends with
  - uncommitted changes under src/, tools/, config/ or in pyproject.toml, or
  - commits on the current branch that are not on its upstream,
this hook blocks the stop and asks for the `release` skill (.claude/skills/release/SKILL.md).
It stays silent while the program runs (program_running.py: nothing is tested or changed then), when the stop is
already the answer to this hook (`stop_hook_active`, no loop), and when git cannot answer.
Exit 2 = the turn goes on with the reason; exit 0 = the turn may end.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from program_running import GUARDED_DIRS, repo_root, running  # noqa: E402


def git(*args):
    r = subprocess.run(["git", "-C", repo_root(), *args], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else None


def pending():
    """What waits for a release: a list of short sentences ([] = nothing)."""
    out = []
    dirty = git("status", "--porcelain", "--", *GUARDED_DIRS, "pyproject.toml")
    if dirty:
        out.append(f"{len(dirty.splitlines())} uncommitted code file(s)")
    ahead = git("rev-list", "--count", "@{upstream}..HEAD")
    if ahead and ahead != "0":
        out.append(f"{ahead} commit(s) not pushed")
    return out


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    if data.get("stop_hook_active") or running():
        return
    try:
        what = pending()
    except (OSError, subprocess.SubprocessError):
        return
    if what:
        sys.stderr.write("Release pending (.claude/hooks/release_pending.py): " + "; ".join(what) + ".\n"
                         "Run the `release` skill now (test, bump the version in pyproject.toml, commit, push),\n"
                         "or tell the owner in one line why it waits (owner 2026-11-13).\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
