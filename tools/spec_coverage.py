"""spec_coverage.py - mechanical check of docs/spec/coverage.md against the step files and the source inventory.

Checks (exit 1 on any structural error; `unknown` rows are counted, not errors):
  - every panel row (P###) and frame row (D###) names feature IDs that exist as `### F<step>.<nn>` headings in
    docs/spec/[0-5]-*.md, or the literal `unknown` / `unused`; `unknown` and `unused` rows carry a note;
  - every feature heading appears in at least one coverage row; no heading is defined twice; no row twice;
  - the row counts equal the declared inventory (`<!-- inventory: panel=N frames=M -->`), and, when the V6 source
    files named by `<!-- source-dir: ... -->` are readable, equal the source itself (panel labels in tab order,
    case / event frame indices and owners).
Standard library only. Usage: py tools/spec_coverage.py [repo_root]
"""
import glob
import json
import os
import re
import sys

HEADING = re.compile(r"^###\s+(F\d\.\d{2})\b", re.MULTILINE)
FEATURE = re.compile(r"F\d\.\d{2}")
FRAME_OWNERS = ("CaseStructure", "EventStructure")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def main(root):
    spec = os.path.join(root, "docs", "spec")
    errors = []
    headings = {}
    for path in sorted(glob.glob(os.path.join(spec, "[0-5]-*.md"))):
        for fid in HEADING.findall(read(path)):
            if fid in headings:
                errors.append(f"feature {fid} defined in {headings[fid]} and {os.path.basename(path)}")
            headings[fid] = os.path.basename(path)
    text = read(os.path.join(spec, "coverage.md"))
    inv = re.search(r"<!--\s*inventory:\s*panel=(\d+)\s+frames=(\d+)\s*-->", text)
    if not inv:
        return report(["coverage.md has no '<!-- inventory: panel=N frames=M -->' line"], {})
    want_panel, want_frames = int(inv.group(1)), int(inv.group(2))

    rows = {}                                     # id -> (label or owner, feature cell, note)
    for line in text.splitlines():
        if not re.match(r"\|\s*[PD]\d{3}\s*\|", line):
            continue
        c = cells(line)
        rid = c[0]
        if rid in rows:
            errors.append(f"row {rid} appears twice")
        if rid.startswith("P") and len(c) == 6:
            rows[rid] = (c[1].strip("`"), c[4], c[5])
        elif rid.startswith("D") and len(c) == 5:
            rows[rid] = (c[1], c[3], c[4])
        else:
            errors.append(f"row {rid} has {len(c)} cells")
    used = set()
    counts = {"mapped": 0, "unknown": 0, "unused": 0}
    for rid, (_, feat, note) in rows.items():
        if feat in ("unknown", "unused"):
            counts[feat] += 1
            if not note:
                errors.append(f"row {rid} is {feat} without a note")
            continue
        ids = [t.strip() for t in feat.split(",")]
        if not ids or any(not FEATURE.fullmatch(t) or t not in headings for t in ids):
            errors.append(f"row {rid} names no existing feature: {feat!r}")
        used.update(ids)
        counts["mapped"] += 1
    errors += [f"feature {fid} ({headings[fid]}) is not in coverage.md" for fid in sorted(set(headings) - used)]

    panel = [r for r in rows if r.startswith("P")]
    frames = [r for r in rows if r.startswith("D")]
    if len(panel) != want_panel:
        errors.append(f"panel rows {len(panel)} != declared inventory {want_panel}")
    if len(frames) != want_frames:
        errors.append(f"frame rows {len(frames)} != declared inventory {want_frames}")
    counts["panel rows"], counts["frame rows"], counts["features"] = len(panel), len(frames), len(headings)

    src = re.search(r"<!--\s*source-dir:\s*(.+?)\s*-->", text)
    src = src.group(1) if src else ""
    pw, dt = os.path.join(src, "main_vi_panel_wiring.json"), os.path.join(src, "diagram_tree_main.json")
    if src and os.path.isfile(pw) and os.path.isfile(dt):
        labels = [r["label"].replace("\n", "\\n") for r in json.loads(read(pw))["rows"]]
        if len(labels) != want_panel:
            errors.append(f"source panel has {len(labels)} objects, inventory says {want_panel}")
        for i, lab in enumerate(labels):
            got = rows.get(f"P{i:03d}", ("<missing>",))[0]
            if got != lab:
                errors.append(f"P{i:03d} label {got!r} != source {lab!r}")
        owners = json.loads(read(dt))["owners"]
        src_frames = {f"D{i:03d}" for i, o in enumerate(owners) if o in FRAME_OWNERS}
        if src_frames != set(frames):
            errors.append(f"frame rows differ from source: missing {sorted(src_frames - set(frames))}, "
                          f"extra {sorted(set(frames) - src_frames)}")
        for rid in frames:
            if rid in src_frames and rows[rid][0] != owners[int(rid[1:])]:
                errors.append(f"{rid} owner {rows[rid][0]!r} != source {owners[int(rid[1:])]!r}")
        counts["source"] = "checked"
    else:
        counts["source"] = f"not readable, declared counts only ({src or 'no source-dir'})"
    return report(errors, counts)


def report(errors, counts):
    for k, v in counts.items():
        print(f"{k}: {v}")
    for e in errors:
        print("ERROR: " + e)
    return 1 if errors else 0


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else here))
