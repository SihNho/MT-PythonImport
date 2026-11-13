"""program_running.py - PreToolUse hook: no code change and no test run while the program is running.

Owner 2026-11-13, during a 500 Hz recording: "the code is running; what if you change it now" -> "keep it as a hook".
While a `python -m mtpy.engine` or `python -m mtpy.gui` process is alive this blocks
  - Write / Edit / MultiEdit / NotebookEdit of a file under src/, tools/ or config/ of this repository
    (a module not imported yet would load the new version next to the old ones; config is read at run time);
  - shell commands that change the working tree or load the PC: pytest, a Python script or `python -c`,
    `sed -i`, and git checkout / switch / restore / reset / stash / merge / pull / rebase / apply / cherry-pick / clean.
Reading (git status / diff / log, grep, a process listing) stays allowed, and so do docs, tests and memory edits.
Exit 2 = blocked (the reason goes to stderr and back to the assistant); exit 0 = allowed.
A process listing that fails allows the call: the hook must not lock the repository when PowerShell is missing.
Self-check: `py program_running.py --self-test`.
"""
import json
import os
import re
import subprocess
import sys

GUARDED_DIRS = ("src", "tools", "config")
PROGRAM = re.compile(r"-m\s+mtpy\.(engine|gui)\b")
SHELL = re.compile(
    r"\bpytest\b|\bsed\s+(-\w+\s+)*-i\b"
    r"|\bgit\s+(checkout|switch|restore|reset|stash|merge|pull|rebase|apply|cherry-pick|clean)\b"
    # python / py in command position (start, after ; & | (, or the end of a path), not as an argument of grep
    r"|(^\s*|[;&|(]\s*|[/\\])(\w+=\S+\s+)*(python[\w.]*|py)(\.exe)?[\"']?\s+(?!-V\b|--version\b)")


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))           # <repo>/.claude/hooks
    return os.path.normcase(os.path.dirname(os.path.dirname(here)))


def guarded_file(path, root):
    p = os.path.normcase(os.path.abspath(path))
    return any(p.startswith(os.path.join(root, d) + os.sep) for d in GUARDED_DIRS)


def blocked(tool, inp, root):
    """Why this call must not run while the program is alive, or None."""
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        return f"it edits {path}" if path and guarded_file(path, root) else None
    if tool in ("Bash", "PowerShell"):
        m = SHELL.search(inp.get("command", ""))
        return f"the command runs `{m.group(0).strip()}`" if m else None
    return None


def running():
    """Command lines of the live program processes ([] when none or when the listing failed)."""
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
           "ForEach-Object { '{0} {1}' -f $_.ProcessId, $_.CommandLine }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in out.splitlines() if PROGRAM.search(line)]


def self_test():
    root = repo_root()
    src = os.path.join(root, "src", "mtpy", "fast.py")
    assert blocked("Edit", {"file_path": src}, root)
    assert blocked("Write", {"file_path": os.path.join(root, "config", "rig_presets.json")}, root)
    assert blocked("Edit", {"file_path": os.path.join(root, "docs", "plan.md")}, root) is None
    assert blocked("Edit", {"file_path": os.path.join(root, ".claude", "hooks", "x.py")}, root) is None
    for c in (".venv/Scripts/python.exe -m pytest tests -q", "cd x && python patch.py", "py -I tool.py",
              "sed -i 's/a/b/' f.py", "git stash -q", "git checkout -- src", '"C:/p/python.exe" "s.py"'):
        assert blocked("Bash", {"command": c}, root), c
    for c in ("git status --short", "git diff --stat", "grep -n python src/x.py", "ls -la", "python --version",
              "Get-Process python*", "graphify.exe update ."):
        assert blocked("Bash", {"command": c}, root) is None, c
    assert PROGRAM.search('"python.exe" -m mtpy.engine') and not PROGRAM.search("python -m pytest tests")
    print("ok")


def main():
    if "--self-test" in sys.argv:
        return self_test()
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    why = blocked(data.get("tool_name", ""), data.get("tool_input") or {}, repo_root())
    if not why:
        return
    procs = running()
    if procs:
        sys.stderr.write("BLOCKED (.claude/hooks/program_running.py): the program is running and " + why + ".\n"
                         "Code, config and tests wait until the owner has closed the program (owner 2026-11-13).\n"
                         "Running: " + " | ".join(p[:120] for p in procs[:3]) + "\n"
                         "Tell the owner what is waiting; do not work around this hook.\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
