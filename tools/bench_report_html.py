"""The user report of a bench (decision 0030 item 6): one HTML page (and its .ko.html) for the experimenter, built
from the run files and the blocks' report.json / isolate.json - a conclusion, the conditions, the tables (condition x
method x executor: precision, accuracy, robustness, throughput; coloured), a few figures (inline SVG, no plotting
library), the invalid runs greyed with a reason, and the data paths. The project's own record stays in docs/results.

  py tools/bench_report_html.py [--out docs/reports/2026-11-07-bench]
     [--new G:\\l2s_rig_data\\2026-11-07b_] [--baseline G:\\l2s_rig_data\\2026-11-07_]
     [--offline bench_out/1107/offline_compare_stride8.json]
"""
import argparse
import glob
import html
import json
import os
from pathlib import Path

import h5py
import numpy as np

T = {
    "en": {
        "title": "MT tracking bench, 2026-11-07", "conclusion": "Conclusion", "conditions": "Conditions",
        "offline": "Offline: every variant against the reference on the same recorded frames",
        "stage1": "Stage 1: the standard condition (90 Hz, 20 beads), every method x executor",
        "stage2": "Stage 2: rate x bead count (the zero-drop boundary) and the other blocks",
        "boundary": "Zero-drop boundary: pipeline drops per run (rate x beads x executor)",
        "figures": "Figures", "data": "Data and how to regenerate", "invalid": "greyed: invalid run (reason in the last column)",
        "cols": ["run", "rate Hz", "beads", "z method", "executor", "precision", "frames", "gaps", "drops",
                 "tracking ms p50 / p99 / max", "focus step error nm raw / corrected (median / max)",
                 "stage shift nm raw / corrected", "magnet shift nm raw / corrected", "hold noise nm", "lost bead-frames",
                 "follow ms", "overshoot nm", "hold moves", "note"],
        "offcols": ["z method", "executor", "precision", "ms p50 / p99 / max", "index jumps %", "|dz| nm median / p99 / max",
                    "|dxy| px max"],
        "fig_ms": "Tracking time p99 per frame against the bead count (full frame; dashed: the frame period)",
        "fig_stair": "The focus staircase as tracked (median z of the beads, reference-corrected to bead 1)",
    },
    "ko": {
        "title": "MT 추적 벤치, 2026-11-07", "conclusion": "결론", "conditions": "조건",
        "offline": "오프라인: 같은 녹화 프레임에서 레퍼런스 대비 각 변형",
        "stage1": "1단계: 표준 조건(90 Hz, 20 비드), 모든 방법 × 실행기",
        "stage2": "2단계: 레이트 × 비드 수(드랍 0 경계)와 나머지 블록",
        "boundary": "드랍 0 경계: 런당 파이프라인 드랍 (레이트 × 비드 × 실행기)",
        "figures": "그림", "data": "데이터와 재생성 방법", "invalid": "회색: 무효 런(마지막 열에 이유)",
        "cols": ["런", "레이트 Hz", "비드", "z 방법", "실행기", "정밀도", "프레임", "갭", "드랍",
                 "추적 ms p50 / p99 / max", "focus 스텝 오차 nm raw / 보정 (중앙값 / 최대)",
                 "스테이지 이동 nm raw / 보정", "자석 이동 nm raw / 보정", "hold 노이즈 nm", "lost 비드-프레임",
                 "추종 ms", "오버슈트 nm", "hold 이동", "비고"],
        "offcols": ["z 방법", "실행기", "정밀도", "ms p50 / p99 / max", "인덱스 점프 %", "|dz| nm 중앙값 / p99 / 최대",
                    "|dxy| px 최대"],
        "fig_ms": "비드 수에 따른 프레임당 추적 시간 p99 (풀 프레임; 점선: 프레임 주기)",
        "fig_stair": "추적된 focus 계단 (비드 z 중앙값, 비드 1 기준 보정)",
    },
}
CONCLUSION = {"en": [], "ko": []}        # filled by --conclusion <file> (one paragraph per line; .ko file for Korean)
# a note on a run that stays valid (its drops / ms / medians stand; the max columns do not): block -> (first run index, note)
B3 = "six beads; the owner's bead 3 answered the magnet (-0.7..-0.9 um at 10 mm) in every run: the magnet max column is bead 3"
NOTES = {"m90": [(0, B3)], "s90": [(0, B3)], "s150": [(0, B3)],
         "s248": [(0, B3), (3, "bead 5 loose from this run on (lost 37 %): the max accuracy columns inflated, medians stand")]}


def invalid(r):
    return r["note"].startswith(("failed", "no frames"))


def block_folders(prefix):
    """The runner's blocks under prefix, in list order; folders set aside (_failed_bead5, _false_lock, _no_start) skipped."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import rig_bench_1107
    return [prefix + name for name, _, _ in rig_bench_1107.R.BLOCKS if os.path.isdir(prefix + name)]
CSS = """
body{font:14px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:1400px;margin:24px auto;padding:0 16px;color:#1b1b1b}
h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}
table{border-collapse:collapse;font-size:12px;margin:8px 0}th,td{border:1px solid #ccc;padding:3px 6px;text-align:right;white-space:nowrap}
th{background:#f3f3f3;text-align:center}td:first-child,td:nth-child(4),td:nth-child(5),td:nth-child(6){text-align:left}
.ok{background:#e6f4e6}.warn{background:#fff3d6}.bad{background:#fbe0e0}.inv{color:#999;background:#f5f5f5}
.con p{font-size:15px}.small{font-size:12px;color:#555}svg{max-width:100%}
"""
PERIOD_MS = {90: 11.1, 150: 6.67, 248: 4.03, 555: 1.80}


def f0(v):
    return "-" if v is None else f"{v:.0f}"


def pair(a, k):
    return f"{f0(a[k][0])} / {f0(a[k][1])}" if a and a.get(k) else "-"


def cls_drops(d):
    return "ok" if d == 0 else ("warn" if d < 20 else "bad")


def hold_moves(h5):
    try:
        with h5py.File(h5, "r") as f:
            if "events/mark" not in f:
                return "-"
            texts = [json.loads(d).get("text", "") for d in f["events/mark"]["data"][:]]
    except OSError:
        return "?"
    moves = [t.split(" (")[0].replace("hold ", "") for t in texts if t.startswith("hold")]
    return "; ".join(moves) if moves else "none"


def rows_of(folder, baseline):
    """Normalised rows of one block folder (script report.json or GUI isolate.json)."""
    out = []
    for fn in ("report.json", "isolate.json"):
        p = os.path.join(folder, fn)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            rep = json.load(f)
        for i, r in enumerate(rep.get("runs", [])):
            gui = fn == "isolate.json"
            if gui:
                name = f"iso_{r['fps']:.0f}_{r['beads']}_{r['z_method']}_{'gpu' if r['gpu'] else 'numba'}_{r['condition']}"
                ex = "gpu" if r["gpu"] else "numba"
                frames, gaps, drops = r.get("frames"), r.get("gaps"), r.get("drops")
                ms = (r.get("track_p50"), r.get("track_p99"), r.get("track_max"))
                h5 = os.path.join(folder, "runs", name + ".h5")
            else:
                name = r["name"]
                ex = name.split("_")[-1] if not name.endswith("_r") else name.split("_")[-2]
                frames, gaps, drops = r.get("frames_tracked"), r.get("camera_gaps"), r.get("pipeline_drops")
                ms = (r.get("track_ms_p50"), r.get("track_ms_p99"), r.get("track_ms_max"))
                h5 = os.path.join(folder, name + ".h5")
            zm = r.get("z_method", "")
            zm = {"current": "current_v1", "spline": "spline_v1", "phase_spline": "phase_spline_v1"}.get(zm, zm)
            prec = "fp64" if ex == "numba" or ex == "gpu64" or baseline else "fp32"
            ex_name = "cuda" if ex.startswith("gpu") else "numba"
            note = ""
            if "error" in r:
                note = "failed: " + r["error"][:60]
            elif not frames:
                note = "no frames"
            else:
                note = "; ".join(n for i0, n in NOTES.get(os.path.basename(folder).split("_", 1)[-1], []) if i >= i0)
            acc = r.get("accuracy")
            out.append({"run": name, "fps": r.get("fps"), "beads": r.get("beads"), "zm": zm, "ex": ex_name, "prec": prec,
                        "frames": frames, "gaps": gaps, "drops": drops, "ms": ms, "acc": acc, "note": note,
                        "gui": gui, "h5": h5, "block": os.path.basename(folder)})
    return out


def table(lang, rows):
    L = T[lang]
    h = ["<table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in L["cols"]) + "</tr>"]
    for r in rows:
        inv = invalid(r)
        a = r["acc"]
        ms = "-" if r["ms"][0] is None else " / ".join(f"{v:.2f}" for v in r["ms"])
        cells = [r["run"], f0(r["fps"]), str(r["beads"]), r["zm"], r["ex"], r["prec"], str(r["frames"] or "-"),
                 str(r["gaps"] if r["gaps"] is not None else "-"), str(r["drops"] if r["drops"] is not None else "-"), ms,
                 pair(a, "focus_raw_nm") + " / " + pair(a, "focus_ref_nm") if a else "-",
                 pair(a, "stage_raw_nm") + " / " + pair(a, "stage_ref_nm") if a else "-",
                 pair(a, "magnet_raw_nm") + " / " + pair(a, "magnet_ref_nm") if a else "-",
                 f0(a.get("noise_nm")) if a else "-", str(a.get("lost", "-")) if a else "-",
                 pair(a, "follow_ms") if a else "-", f0((a.get("overshoot_nm") or [None])[0]) if a else "-",
                 hold_moves(r["h5"]), r["note"]]
        tds = []
        for i, c in enumerate(cells):
            k = ""
            if not inv and i == 8 and r["drops"] is not None:
                k = cls_drops(r["drops"])
            if not inv and i == 14 and a and r["frames"] and r["beads"]:
                lost_pct = 100.0 * a.get("lost", 0) / max(1, r["frames"] * min(r["beads"], 7))
                k = "ok" if lost_pct < 2 else ("warn" if lost_pct < 10 else "bad")
            tds.append(f'<td class="{k}">{html.escape(str(c))}</td>')
        h.append(f'<tr class="{"inv" if inv else ""}">' + "".join(tds) + "</tr>")
    h.append("</table>")
    return "\n".join(h)


def offline_table(lang, off):
    L = T[lang]
    h = ["<table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in L["offcols"]) + "</tr>"]
    for r in off.get("rows", []):
        f = lambda v: "-" if v is None else f"{v:.2f}"
        j = r["index_jump_pct"]
        h.append(f"<tr><td>{r['z_method']}</td><td>{r['executor']}</td><td>{r['precision']}</td>"
                 f"<td>{r['ms_p50']:.2f} / {r['ms_p99']:.2f} / {r['ms_max']:.2f}</td>"
                 f'<td class="{"ok" if j < 0.1 else "bad"}">{j:.2f}</td>'
                 f"<td>{f(r['dz_nm_median'])} / {f(r['dz_nm_p99'])} / {f(r['dz_nm_max'])}</td><td>{r['dxy_px_max']:.1e}</td></tr>")
    h.append("</table>")
    return "\n".join(h)


def boundary_table(rows):
    """drops per run, rate x beads, one column per executor / precision (stage 2 script rows, current_v1 only)."""
    sel = [r for r in rows if not r["gui"] and r["zm"] == "current_v1" and r["drops"] is not None]
    if not sel:
        return ""
    rates = sorted({round(r["fps"]) for r in sel})
    beads = sorted({r["beads"] for r in sel})
    execs = sorted({(r["ex"], r["prec"]) for r in sel})
    h = ["<table><tr><th>rate Hz</th><th>beads</th>" + "".join(f"<th>{e} {p}</th>" for e, p in execs) + "</tr>"]
    for fps in rates:
        for n in beads:
            cells = []
            for e, p in execs:
                rr = [r for r in sel if round(r["fps"]) == fps and r["beads"] == n and (r["ex"], r["prec"]) == (e, p)]
                if not rr:
                    cells.append("<td>-</td>")
                else:
                    d = max(r["drops"] for r in rr)
                    ms = max(r["ms"][1] or 0 for r in rr)
                    cells.append(f'<td class="{cls_drops(d)}">{d} ({ms:.1f} ms p99)</td>')
            if any("ms p99" in c for c in cells):
                h.append(f"<tr><td>{fps}</td><td>{n}</td>" + "".join(cells) + "</tr>")
    h.append("</table>")
    return "\n".join(h)


def svg_lines(series, xlabel, ylabel, w=640, h=320, hline=None, logy=False):
    """A plain SVG line chart: series = [(label, xs, ys)]; hline = [(label, y)] dashed lines."""
    xs = np.concatenate([np.asarray(s[1], float) for s in series]) if series else np.array([0, 1])
    ys = np.concatenate([np.asarray(s[2], float) for s in series]) if series else np.array([0, 1])
    if hline:
        ys = np.concatenate([ys, [y for _, y in hline]])
    x0, x1 = float(xs.min()), float(xs.max()) or 1.0
    y0, y1 = 0.0, float(ys.max()) * 1.1 or 1.0
    ml, mr, mt, mb = 56, 16, 16, 40
    px = lambda x: ml + (x - x0) / ((x1 - x0) or 1) * (w - ml - mr)
    py = lambda y: h - mb - (y - y0) / ((y1 - y0) or 1) * (h - mt - mb)
    colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b"]
    out = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg" style="font:11px sans-serif">',
           f'<rect x="{ml}" y="{mt}" width="{w - ml - mr}" height="{h - mt - mb}" fill="#fff" stroke="#999"/>']
    for k in range(6):
        y = y0 + (y1 - y0) * k / 5
        out.append(f'<line x1="{ml}" x2="{w - mr}" y1="{py(y):.1f}" y2="{py(y):.1f}" stroke="#eee"/>'
                   f'<text x="{ml - 6}" y="{py(y) + 4:.1f}" text-anchor="end">{y:.3g}</text>')
    for k in range(6):
        x = x0 + (x1 - x0) * k / 5
        out.append(f'<text x="{px(x):.1f}" y="{h - mb + 14}" text-anchor="middle">{x:.3g}</text>')
    out.append(f'<text x="{(ml + w - mr) / 2:.0f}" y="{h - 6}" text-anchor="middle">{html.escape(xlabel)}</text>')
    out.append(f'<text transform="translate(14,{(mt + h - mb) / 2:.0f}) rotate(-90)" text-anchor="middle">{html.escape(ylabel)}</text>')
    for label, y in (hline or []):
        out.append(f'<line x1="{ml}" x2="{w - mr}" y1="{py(y):.1f}" y2="{py(y):.1f}" stroke="#444" stroke-dasharray="4 3"/>'
                   f'<text x="{w - mr - 2}" y="{py(y) - 3:.1f}" text-anchor="end" fill="#444">{html.escape(label)}</text>')
    for i, (label, sx, sy) in enumerate(series):
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(sx, sy))
        c = colors[i % len(colors)]
        out.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.5"/>')
        out.append(f'<rect x="{ml + 8}" y="{mt + 6 + 14 * i}" width="10" height="10" fill="{c}"/>'
                   f'<text x="{ml + 22}" y="{mt + 15 + 14 * i}">{html.escape(label)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def fig_ms(rows):
    sel = [r for r in rows if not r["gui"] and r["zm"] == "current_v1" and r["ms"][1] and not invalid(r)]
    series = []
    for fps in sorted({round(r["fps"]) for r in sel}):
        for e, p in sorted({(r["ex"], r["prec"]) for r in sel}):
            pts = sorted((r["beads"], r["ms"][1]) for r in sel if round(r["fps"]) == fps and (r["ex"], r["prec"]) == (e, p))
            if len(pts) >= 2:
                series.append((f"{fps} Hz {e} {p}", [b for b, _ in pts], [m for _, m in pts]))
    hl = [(f"{fps} Hz: {PERIOD_MS[fps]} ms", PERIOD_MS[fps]) for fps in (555, 248, 150) if any(s[0].startswith(f"{fps} ") for s in series)]
    return svg_lines(series, "beads", "tracking ms p99", hline=hl) if series else ""


def fig_staircase(rows):
    """z (median of the beads, corrected to bead 1) against time over the focus holds, one run per executor."""
    series = []
    for e, p in (("numba", "fp64"), ("cuda", "fp32"), ("cuda", "fp64")):
        cand = [r for r in rows if not r["gui"] and r["zm"] == "current_v1" and (r["ex"], r["prec"]) == (e, p)
                and not invalid(r) and os.path.exists(r["h5"])]
        if not cand:
            continue
        r = cand[0]
        try:
            with h5py.File(r["h5"], "r") as f:
                t = f["mt/t_host"][:]
                z = f["mt/z_um"][:, :min(7, f["mt/z_um"].shape[1])] * 1000.0
                lost = f["mt/bead_lost"][:, :z.shape[1]] > 0
                marks = sorted(zip(f["events/mark"]["t_host"][:], [json.loads(d).get("text", "") for d in f["events/mark"]["data"][:]]))
        except (OSError, KeyError):
            continue
        focus = [m for m in marks if m[1].startswith("focus")]
        if not focus:
            continue
        t0, t1 = focus[0][0] - 1.0, focus[-1][0] + 3.0
        sel = (t >= t0) & (t <= t1)
        zz = np.where(lost[sel], np.nan, z[sel])
        corr = np.nanmedian(zz[:, 1:] - zz[:, :1], axis=1) if zz.shape[1] > 1 else zz[:, 0]
        corr = corr - np.nanmedian(corr[:50])
        step = max(1, sel.sum() // 400)
        series.append((f"{r['run']} ({e} {p})", (t[sel] - t0)[::step], np.nan_to_num(corr[::step])))
    return svg_lines(series, "s", "z nm (corrected)") if series else ""


def page(lang, new_rows, base_rows, off, args):
    L = T[lang]
    stage1 = [r for r in new_rows if r["block"].endswith("m90")]
    stage2 = [r for r in new_rows if not r["block"].endswith("m90")]
    parts = [f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'><title>{html.escape(L['title'])}</title><style>{CSS}</style></head><body>",
             f"<h1>{html.escape(L['title'])}</h1>", f"<h2>{L['conclusion']}</h2><div class='con'>"]
    parts += [f"<p>{html.escape(p)}</p>" for p in CONCLUSION[lang]] or ["<p class='small'>(no conclusion text given)</p>"]
    parts.append("</div>")
    parts.append(f"<h2>{L['conditions']}</h2><ul>" + "".join(f"<li>{html.escape(c)}</li>" for c in CONDITIONS[lang]) + "</ul>")
    if off:
        parts.append(f"<h2>{L['offline']}</h2><p class='small'>{off.get('frames')} frames x {off.get('beads')} beads, "
                     f"reference {html.escape(str(off.get('reference')))}</p>" + offline_table(lang, off))
    if stage1:
        parts.append(f"<h2>{L['stage1']}</h2><p class='small'>{L['invalid']}</p>" + table(lang, stage1))
    if stage2:
        parts.append(f"<h2>{L['boundary']}</h2>" + boundary_table(stage2))
        parts.append(f"<h2>{L['stage2']}</h2><p class='small'>{L['invalid']}</p>" + table(lang, stage2))
    if base_rows:
        parts.append("<h2>cuda fp64 baseline (the first attempt, 2026-11-07 01:47-02:19)</h2>" + table(lang, base_rows))
    figs = [(L["fig_ms"], fig_ms(new_rows + base_rows)), (L["fig_stair"], fig_staircase(new_rows))]
    figs = [(c, s) for c, s in figs if s]
    if figs:
        parts.append(f"<h2>{L['figures']}</h2>" + "".join(f"<p>{html.escape(c)}</p>{s}" for c, s in figs))
    parts.append(f"<h2>{L['data']}</h2><p class='small'>{html.escape(args.new)}&lt;block&gt;, {html.escape(args.baseline)}&lt;block&gt;, "
                 f"{html.escape(args.offline)}; <code>py tools/bench_report_html.py</code> rebuilds this page.</p></body></html>")
    return "\n".join(parts)


CONDITIONS = {
    "en": ["Sample: the owner's six picked beads (stuck, all reference) for m90 / s90 / s150 / s248; bead 5 came loose at 03:35 and bead 3 at 04:00 (the channel drying), so the blocks from s555 on ran on the four left (three inside the 640 x 512 ROI). The stage where the owner left it, (0.0239, -2.9383) mm, focus 5.8 um; the hold followed the drift to (0.0288, -2.9402) mm, focus 6.7-7.1 um.",
           "LUT per block: 60 slices x 100 nm centred on the current focus, 10 frames per slice (17 / 28 / 62 in the n-blocks), magnet at Cal+ 37.4 mm.",
           "Per run: the drift hold (stage xy and focus z back to the LUT), focus steps (+-1 um pattern or a 20 / 50 / 100 nm staircase), stage steps 1 / 2 / 5 um, magnet 30 / 10 / 0 mm and back.",
           "Executors: numba fp64 (the LabVIEW-identical reference), cuda fp32 (the production candidate), cuda fp64 (baseline).",
           "Frame loss is the pipeline's own count (raw data), never the display."],
    "ko": ["샘플: m90 / s90 / s150 / s248은 본인이 고른 비드 6개(붙은 비드, 전부 reference); 03:35에 비드 5, 04:00에 비드 3이 떨어져(채널 건조) s555부터는 남은 4개(640 × 512 ROI 안에는 3개). 스테이지는 본인이 둔 (0.0239, -2.9383) mm, focus 5.8 µm에서 시작, hold가 드리프트를 따라 (0.0288, -2.9402) mm, focus 6.7-7.1 µm까지 이동.",
           "블록마다 LUT: 60 슬라이스 × 100 nm, 현재 focus 중심, 슬라이스당 10 프레임(n 블록은 17 / 28 / 62), 자석 Cal+ 37.4 mm.",
           "런마다: 드리프트 hold(스테이지 xy와 focus z를 LUT 기준으로 복귀), focus 스텝(±1 µm 패턴 또는 20 / 50 / 100 nm 계단), 스테이지 1 / 2 / 5 µm, 자석 30 / 10 / 0 mm 후 복귀.",
           "실행기: numba fp64(LabVIEW와 동일한 레퍼런스), cuda fp32(운용 후보), cuda fp64(기준선).",
           "프레임 로스는 파이프라인 자체 카운트(raw data)이며 화면 표시와 무관."],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "docs" / "reports" / "2026-11-07-bench"))
    ap.add_argument("--new", default=r"G:\l2s_rig_data\2026-11-07b_")
    ap.add_argument("--baseline", default=r"G:\l2s_rig_data\2026-11-07_")
    ap.add_argument("--offline", default=str(Path(__file__).resolve().parent.parent / "bench_out" / "1107" / "offline_compare_stride8.json"))
    ap.add_argument("--conclusion", default=None, help="text file, one paragraph per line; <name>.ko.txt beside it for Korean")
    a = ap.parse_args()
    if a.conclusion:
        CONCLUSION["en"] = [ln for ln in Path(a.conclusion).read_text(encoding="utf-8").splitlines() if ln.strip()]
        ko = Path(a.conclusion).with_suffix(".ko.txt")
        CONCLUSION["ko"] = [ln for ln in ko.read_text(encoding="utf-8").splitlines() if ln.strip()] if ko.exists() else CONCLUSION["en"]
    new_rows = [r for f in block_folders(a.new) for r in rows_of(f, False)]
    base_rows = [r for f in sorted(glob.glob(a.baseline + "*")) for r in rows_of(f, True)]
    off = json.load(open(a.offline, encoding="utf-8")) if os.path.exists(a.offline) else None  # noqa: SIM115
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    for lang, suffix in (("en", ".html"), ("ko", ".ko.html")):
        Path(a.out + suffix).write_text(page(lang, new_rows, base_rows, off, a), encoding="utf-8")
        print("->", a.out + suffix, f"({len(new_rows)} new rows, {len(base_rows)} baseline rows)")


if __name__ == "__main__":
    main()
