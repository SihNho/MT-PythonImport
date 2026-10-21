"""english_only.py - PreToolUse hook: documents and code in this repository are written in English.

Blocks a Write / Edit / MultiEdit / NotebookEdit inside the repository when the new text contains Hangul OUTSIDE a
quoted span. Allowed:
  - Hangul inside quotes on one line: "...", '...', `...`, \u201c...\u201d, \u2018...\u2019
    (verbatim quotes of the owner's words, Korean data strings such as a date in a .cal file, accepted aliases)
  - Korean translations in files named *.ko.<ext> (e.g. README.ko.md)
  - files outside the repository
Exit 2 = blocked (the reason goes to stderr and back to the assistant); exit 0 = allowed.
Decision: docs/decisions/0009-development-method.md (documents in English; Korean optional).
"""
import json
import os
import re
import sys

HANGUL = re.compile("[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")
QUOTED = re.compile(r'"[^"\n]*"|`[^`\n]*`|\u201c[^\u201d\n]*\u201d|\u2018[^\u2019\n]*\u2019|\'[^\'\n]*\'')


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))           # <repo>/.claude/hooks
    return os.path.normcase(os.path.dirname(os.path.dirname(here)))


def new_texts(tool, inp):
    if tool == "Write":
        return [inp.get("content", "")]
    if tool == "Edit":
        return [inp.get("new_string", "")]
    if tool == "MultiEdit":
        return [e.get("new_string", "") for e in inp.get("edits", [])]
    if tool == "NotebookEdit":
        return [inp.get("new_source", "")]
    return []


def offending_lines(text):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if HANGUL.search(QUOTED.sub("", line)):
            out.append((n, line.strip()))
    return out


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))   # Claude Code sends UTF-8; never the locale codec
    except Exception:
        return 0                                                  # not our payload: never block on parse errors
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    if not path:
        return 0
    full = os.path.normcase(os.path.abspath(path))
    root = repo_root()
    if not (full == root or full.startswith(root + os.sep)):
        return 0
    name = os.path.basename(full)
    if re.search(r"\.ko\.[^.]+$", name):
        return 0
    bad = []
    for t in new_texts(tool, inp):
        bad += offending_lines(t or "")
    if not bad:
        return 0
    shown = "\n".join("  line %d: %s" % (n, s[:120]) for n, s in bad[:3])
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stderr.write(
        "BLOCKED by .claude/hooks/english_only.py: documents and code in this repository are written in English.\n"
        "Korean found outside quotes in %s:\n%s\n"
        "Write it in English. Korean is allowed only inside quotes (verbatim quotes, data strings) "
        "or in a separate translation file named *.ko.md.\n" % (os.path.relpath(full, root), shown))
    return 2


if __name__ == "__main__":
    sys.exit(main())
