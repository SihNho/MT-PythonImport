"""What a run file (.h5) holds, as one HTML page (owner 2026-11-06: "list what the .h5 file holds and what the
metadata is, as an html file"). The page is generated from a REAL run file, so every group, dataset, dtype, unit
and description is what the writer (src/mtpy/data/hdf5.py) put there, never a hand-copied list; the paragraphs on
when the data reach the disk are the hand-written part below.

    python tools/run_file_doc.py runs/tra002.h5 docs/format/run-file.html [--ko]

The GUI's Save page opens docs/format/run-file.html (English) or run-file.ko.html (Korean)."""
import argparse
import html
import json
from pathlib import Path

import h5py

EN = {
    "title": "The run file (.h5): what it holds",
    "intro": (
        "One run file per tracking run, <code>tra001.h5</code> next to the calibration <code>cal001</code>. It is the "
        "raw record: every recorded frame's tracking result and motor readings, the segments and recordings, every "
        "event, and the metadata (devices, run, the .cal used). The <code>.tra</code> files are exported from it "
        "(Save the traces) and hold only the tracked rows."),
    "when_h": "When the data reach the disk",
    "when": [
        "The file is created when tracking starts (beads selected, camera running) and opened at the first "
        "<b>Record on</b>; frames are written only while recording is on.",
        "Writing is <b>in real time</b>, not at Save: rows wait in memory for at most <code>flush_s</code> = 1 s or "
        "<code>flush_frames</code> = 150 rows, then go to disk (root attributes <code>flush_s</code>, "
        "<code>flush_frames</code>, <code>frames_written</code>). A crash loses at most the rows since the last flush; "
        "<code>closed_cleanly</code> = 0 then says so and a reader uses <code>frames_written</code> rows.",
        "Record off ends a recording interval; the file stays open. It closes when the camera stops, at Reset "
        "calibration or a new bead selection, or when the program ends; the close writes <code>end_utc</code>, "
        "<code>frame_rate_hz</code> and <code>closed_cleanly</code> = 1, and the sidecar <code>tra001.meta.json</code> "
        "(the <code>/metadata</code> group as JSON without the .cal copy (<code>cal_bytes</code>, <code>stack</code>), for a quick look without HDF5).",
        "<b>Save the traces (.tra)</b> reads this file and writes LabVIEW's <code>tra001-000</code>, "
        "<code>tra001-001</code>, ... (one per 2,000,000 rows) next to it: frame, magnet mm, rotor deg, x y z per bead; "
        "dropped and tracking-error rows left out. The .h5 is not changed by the export.",
        "Lost beads: x, y, z = -1 (the LabVIEW marker); <code>bead_lost</code> = 1. Force is not a column: the magnet "
        "position is stored raw (<code>magnet_mm</code>, the last read-back before each frame, ~10 per second) and the "
        "force follows from the calibration recorded in <code>/metadata/devices/magnet/force_calibration_at_start</code> "
        "(the <code>motor_reading</code> events carry <code>force_pN</code> per reading).",
    ],
    "layout_h": "Layout of this file",
    "generated": "Generated from",
    "root": "Root attributes",
    "attr": "attribute", "value": "value", "dataset": "dataset", "shape": "shape", "dtype": "dtype",
    "unit": "unit", "description": "description", "group_attrs": "group attributes",
}
KO = {
    "title": "런 파일(.h5)에 담기는 것",
    "intro": (
        "추적 한 번에 런 파일 하나, 보정 파일 <code>cal001</code> 옆의 <code>tra001.h5</code>. 원본 기록입니다: 기록된 "
        "모든 프레임의 추적 결과와 모터 읽기값, 세그먼트와 녹화 구간, 모든 이벤트, 메타데이터(장치, 런, 사용한 .cal). "
        "<code>.tra</code>는 이 파일에서 내보내며(Save the traces) 추적된 행만 담습니다."),
    "when_h": "데이터가 디스크에 쓰이는 시점",
    "when": [
        "파일은 추적이 시작될 때(비드 선택, 카메라 동작 중) 만들어지고 첫 <b>Record on</b>에 열립니다. 프레임은 녹화가 "
        "켜진 동안만 기록됩니다.",
        "쓰기는 Save 때가 아니라 <b>실시간</b>입니다: 행은 메모리에 최대 <code>flush_s</code> = 1초 또는 "
        "<code>flush_frames</code> = 150행까지만 머물다 디스크로 갑니다(루트 속성 <code>flush_s</code>, "
        "<code>flush_frames</code>, <code>frames_written</code>). 프로그램이 죽어도 마지막 flush 이후 행만 잃고, "
        "<code>closed_cleanly</code> = 0이 그 사실을 알리며 읽는 쪽은 <code>frames_written</code>행만 씁니다.",
        "Record off는 녹화 구간만 끝내고 파일은 열린 채입니다. 카메라 정지, Reset calibration, 새 비드 선택, 프로그램 "
        "종료 때 닫히며, 닫을 때 <code>end_utc</code>, <code>frame_rate_hz</code>, <code>closed_cleanly</code> = 1과 "
        "사이드카 <code>tra001.meta.json</code>(<code>/metadata</code> 그룹을 JSON으로, .cal 사본(<code>cal_bytes</code>, <code>stack</code>)은 제외; HDF5 없이 빠르게 보기용)을 씁니다.",
        "<b>Save the traces (.tra)</b>는 이 파일을 읽어 LabVIEW의 <code>tra001-000</code>, <code>tra001-001</code>, ... "
        "(2,000,000행마다 하나)을 옆에 씁니다: frame, magnet mm, rotor deg, 비드별 x y z; 드롭된 행과 추적 오류 행은 "
        "제외. 내보내기는 .h5를 바꾸지 않습니다.",
        "잃어버린 비드: x, y, z = -1(LabVIEW 표식), <code>bead_lost</code> = 1. 힘은 열이 아닙니다: 자석 위치를 원본 그대로 "
        "저장하고(<code>magnet_mm</code>, 각 프레임 직전의 마지막 읽기값, 초당 약 10회) 힘은 "
        "<code>/metadata/devices/magnet/force_calibration_at_start</code>에 기록된 보정으로 구합니다"
        "(<code>motor_reading</code> 이벤트에는 읽기마다 <code>force_pN</code>이 있음).",
    ],
    "layout_h": "이 파일의 구조",
    "generated": "생성 원본",
    "root": "루트 속성",
    "attr": "속성", "value": "값", "dataset": "데이터셋", "shape": "shape", "dtype": "dtype",
    "unit": "단위", "description": "설명", "group_attrs": "그룹 속성",
}
CSS = """body{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222}
table{border-collapse:collapse;width:100%;margin:8px 0 20px}th,td{border:1px solid #ccc;padding:4px 8px;
text-align:left;vertical-align:top;font-size:13px}th{background:#f3f3f3}code{background:#f6f6f6;padding:0 3px}
h2{margin-top:28px;border-bottom:1px solid #ddd}h3{margin-top:22px;font-family:Consolas,monospace}
p.note{color:#555;font-size:13px}"""


def _s(v):
    """An attribute value as short text."""
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    if hasattr(v, "tolist"):
        v = v.tolist()
    t = str(v)
    return t if len(t) <= 160 else t[:157] + "..."


def _attrs_table(attrs, T, skip=()):
    rows = [(k, _s(v)) for k, v in sorted(attrs.items()) if k not in skip]
    if not rows:
        return ""
    body = "".join(f"<tr><td><code>{html.escape(k)}</code></td><td>{html.escape(v)}</td></tr>" for k, v in rows)
    return f"<table><tr><th>{T['attr']}</th><th>{T['value']}</th></tr>{body}</table>"


def _group(name, g, T, out):
    dsets = [(k, v) for k, v in g.items() if isinstance(v, h5py.Dataset)]
    subs = [(k, v) for k, v in g.items() if isinstance(v, h5py.Group)]
    out.append(f"<h3>/{html.escape(name)}</h3>")
    if dict(g.attrs):
        out.append(f"<p class=note>{T['group_attrs']}:</p>" + _attrs_table(g.attrs, T))
    if dsets:
        rows = []
        for k, d in dsets:
            a = d.attrs
            extra = {x: _s(a[x]) for x in a if x not in ("unit", "description")}
            desc = html.escape(_s(a.get("description", "")))
            if extra:
                desc += " <span class=note>" + html.escape(json.dumps(extra, ensure_ascii=False)) + "</span>"
            rows.append(f"<tr><td><code>{html.escape(k)}</code></td><td>{d.shape}</td><td>{d.dtype}</td>"
                        f"<td>{html.escape(_s(a.get('unit', '')))}</td><td>{desc}</td></tr>")
        out.append(f"<table><tr><th>{T['dataset']}</th><th>{T['shape']}</th><th>{T['dtype']}</th><th>{T['unit']}</th>"
                   f"<th>{T['description']}</th></tr>{''.join(rows)}</table>")
    for k, sg in subs:
        _group(f"{name}/{k}" if name else k, sg, T, out)


def render(h5_path, ko=False):
    T = KO if ko else EN
    out = [f"<!DOCTYPE html><html lang={'ko' if ko else 'en'}><head><meta charset=utf-8><title>{T['title']}</title>"
           f"<style>{CSS}</style></head><body><h1>{T['title']}</h1><p>{T['intro']}</p><h2>{T['when_h']}</h2><ul>"]
    out += [f"<li>{p}</li>" for p in T["when"]]
    out.append("</ul>")
    with h5py.File(h5_path, "r") as f:
        out.append(f"<h2>{T['layout_h']}</h2><p class=note>{T['generated']}: <code>{html.escape(Path(h5_path).name)}</code>"
                   f" (schema {html.escape(_s(f.attrs.get('schema_version', '?')))}, n_beads "
                   f"{html.escape(_s(f['mt'].attrs.get('n_beads', '?')))})</p><h3>{T['root']}</h3>")
        out.append(_attrs_table(f.attrs, T))
        for k in ("mt", "beads", "segments", "recordings", "events", "metadata"):
            if k in f:
                _group(k, f[k], T, out)
        for k, g in f.items():
            if k not in ("mt", "beads", "segments", "recordings", "events", "metadata") and isinstance(g, h5py.Group):
                _group(k, g, T, out)
    out.append("</body></html>")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("h5")
    ap.add_argument("out")
    ap.add_argument("--ko", action="store_true", help="Korean page (run-file.ko.html)")
    a = ap.parse_args(argv)
    Path(a.out).write_text(render(a.h5, a.ko), encoding="utf-8")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
