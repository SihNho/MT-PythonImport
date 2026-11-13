---
name: release
description: >
  Give a code change its version and put it on GitHub: test, bump the version in pyproject.toml, commit, push.
  Use after every change under src/, tools/ or config/, when the Stop hook says "Release pending", and when the
  owner says "release", "commit and push", or asks which version wrote a data file.
---

# release - one code change = one version on GitHub

Owner 2026-11-13: every code change gets a new version number and is pushed, so an old version can be looked up
and a run file can name the code that wrote it. The hook `.claude/hooks/release_pending.py` asks for this skill at
the end of a turn that leaves code uncommitted or unpushed.

## Steps (in this order; stop at the first one that fails and tell the owner)

1. **The program must not be running.** `.claude/hooks/program_running.py` blocks tests and code edits while
   `python -m mtpy.engine` / `mtpy.gui` is alive. If it blocks, the release waits: say so in one line, do not work
   around it.
2. **Look at what will go in:** `git status --short` and `git diff --stat`. Only project files: `src/`, `tools/`,
   `config/`, `tests/`, `docs/`, `.claude/`, `STATUS.md`, `pyproject.toml`. Never data or local files: `runs/`,
   `bench_out/`, `.obsidian/`, pasted images, `*.h5`, anything the owner did not ask to publish. Work of another
   session that is mixed into the tree is named in the commit message, not silently bundled; ask when unsure.
3. **Test:** `.venv/Scripts/python.exe -m pytest tests -q --ignore=tests/test_gui.py`, then `tests/test_gui.py`
   (an access violation there is the known intermittent crash: rerun up to three times), then
   `.venv/Scripts/python.exe -m ruff check` on the files changed. A real failure stops the release.
4. **Bump the version** in `pyproject.toml` (`version = "X.Y.Z"`): Z + 1 for a fix or a small change, Y + 1 (Z = 0)
   for a new feature the owner would name, X only on the owner's word. One bump per release, whatever its size.
5. **Commit** on the current branch (never on `main` directly): the message starts with `vX.Y.Z:`, says in plain
   English what changed and why (the owner's request and its date), what was tested, and what is not verified on
   the rig. End it with the attribution line the session gives.
6. **Push:** `git push origin <current branch>`. No force push, no tags, no pull request unless the owner asks.
7. **Report** in one or two lines: the version, the short commit hash, the branch, and what stays unverified.

## Looking up an old version

`git log --oneline -- pyproject.toml` lists the releases; `git show <hash>:pyproject.toml` gives the number of any
commit; `git checkout <hash>` in a separate worktree gives the code (never in the rig's working tree while the
program runs).

shortcut: the version is not yet written into the run file's metadata (the owner's deferred item of 2026-11-13);
until then a data file is matched to a version by its date against `git log`.
