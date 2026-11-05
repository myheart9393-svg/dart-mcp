"""blocks.json → 단일 파일 HTML (표지·목차·표·SVG 차트, 밝은/어두운 테마, 인쇄용)."""
from __future__ import annotations

import html as stdlib_html
import re
from pathlib import Path

E = stdlib_html.escape


def _runs(rs: list[dict]) -> str:
    out = []
    for r in rs:
        t = E(r["t"])
        if r.get("code"):
            t = f"<code>{t}</code>"
        elif r.get("k") == "cite":
            t = f'<span class="cite">{t}</span>'
        elif r.get("k") == "est":
            t = f'<strong class="est">{t}</strong>'
        elif r.get("k") == "fn":
            t = f"<sup>{t}</sup>"
        if r.get("b"):
            t = f"<strong>{t}</strong>"
        out.append(t)
    return "".join(out)


class _Slugs:
    def __init__(self) -> None:
        self.seen: dict[str, int] = {}

    def make(self, text: str) -> str:
        base = "sec-" + re.sub(r"[^0-9A-Za-z가-힣]+", "-", text).strip("-")
        self.seen[base] = self.seen.get(base, 0) + 1
        return base if self.seen[base] == 1 else f"{base}-{self.seen[base]}"


def _chart(spec: dict) -> str:
    W, H, pad, top, bottom = 640, 270, 28, 34, 236
    series = spec["series"]
    cats = spec["categories"]
    all_vals = [v for s in series for v in s["values"]]
    hi, lo = max(all_vals + [0]), min(all_vals + [0])
    span = (hi - lo) or 1
    scale = (bottom - top) / span
    base = top + hi * scale
    gw = (W - 2 * pad) / len(cats)
    bw = gw * 0.8 / len(series)
    title = spec["title"] + (f" ({spec['unit']})" if spec["unit"] else "")
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{E(title)}" class="chart">',
             f'<line x1="{pad}" y1="{base:.1f}" x2="{W - pad}" y2="{base:.1f}" class="axis"/>']
    for g, cat in enumerate(cats):
        x0 = pad + gw * g + gw * 0.1
        for s, ser in enumerate(series):
            value = ser["values"][g]
            label = E(ser["labels"][g])
            h = abs(value) * scale
            x = x0 + s * bw
            y = base - h if value >= 0 else base
            ty = y - 5 if value >= 0 else y + h + 12
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw * 0.9:.1f}" height="{h:.1f}" '
                         f'class="s{s % 4}"><title>{E(ser["name"])} {E(cat)} {label}</title></rect>')
            parts.append(f'<text x="{x + bw * 0.45:.1f}" y="{ty:.1f}" text-anchor="middle" class="lab">{label}</text>')
        parts.append(f'<text x="{x0 + gw * 0.4:.1f}" y="{H - 8}" text-anchor="middle" class="cat">{E(cat)}</text>')
    parts.append("</svg>")
    legend = ""
    if len(series) > 1:
        legend = '<div class="legend">' + "".join(
            f'<span><i class="sw s{i % 4}"></i>{E(s["name"])}</span>' for i, s in enumerate(series)) + "</div>"
    unit = f' <span class="unit">({E(spec["unit"])})</span>' if spec["unit"] else ""
    return (f'<figure><figcaption>{E(spec["title"])}{unit}</figcaption>{legend}{"".join(parts)}'
            f'<p class="figsrc">표의 값으로 그린 그림</p></figure>')


def _table(b: dict) -> str:
    def align(i: int) -> str:
        return ' class="r"' if b["align"][i] == "r" else ""

    head = ""
    if b.get("groups"):
        head += f'<tr><th rowspan="2">{_runs(b["header"][0])}</th>' + "".join(
            f'<th colspan="{g["span"]}">{E(g["label"])}</th>' for g in b["groups"]) + "</tr>"
        head += "<tr>" + "".join(f"<th>{E(s)}</th>" for s in b["subheader"]) + "</tr>"
    else:
        head += "<tr>" + "".join(f"<th>{_runs(c)}</th>" for c in b["header"]) + "</tr>"
    rows = "".join("<tr>" + "".join(f"<td{align(i)}>{_runs(c)}</td>" for i, c in enumerate(r)) + "</tr>"
                   for r in b["rows"])
    cap = f'[표] {b["n"]}' + (f' {E(b["caption"])}' if b.get("caption") else "")
    return (f'<div class="tblwrap"><p class="cap">{cap}</p>'
            f'<div class="scroll"><table><thead>{head}</thead><tbody>{rows}</tbody></table></div></div>')


def _list(items: list[dict]) -> str:
    def render(start: int, lvl: int) -> tuple[str, int]:
        ordered = "marker" in items[start]
        tag = "ol" if ordered else "ul"
        out = [f'<{tag} class="plain">' if ordered else f"<{tag}>"]
        i = start
        while i < len(items) and items[i]["lvl"] >= lvl:
            it = items[i]
            if it["lvl"] > lvl:
                inner, i = render(i, it["lvl"])
                out.append(inner)
                continue
            marker = f'{E(it["marker"])} ' if it.get("marker") else ""
            out.append(f'<li>{marker}{_runs(it["runs"])}</li>')
            i += 1
        out.append(f"</{tag}>")
        return "".join(out), i

    parts, i = [], 0
    base = min(it["lvl"] for it in items)
    while i < len(items):
        chunk, i = render(i, base)
        parts.append(chunk)
    return "".join(parts)


CSS = """
:root{--bg:#fff;--fg:#1f1f1f;--muted:#595959;--navy:#%(navy)s;--blue:#%(blue)s;--accent:#%(accent)s;--line:#a6a6a6;--thbg:#bfbfbf;--boxbg:#f2f2f2;--verdict:#eef3fa;--est:#%(est)s;--cite:#7f7f7f;--s0:#%(s0)s;--s1:#%(s1)s;--s2:#%(s2)s;--s3:#%(s3)s;--tb:#7f7f7f}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15171c;--fg:#e6e6e6;--muted:#a8a8a8;--navy:#9fb8e8;--blue:#8db3e6;--accent:#ff7b7b;--line:#4a4f5a;--thbg:#2e3440;--boxbg:#1e222a;--verdict:#1c2433;--est:#f0b45a;--cite:#8d93a0;--s0:#6ea0e0;--s1:#f0b73a;--s2:#5fc08a;--s3:#c79be6;--tb:#5a606c}}
:root[data-theme="dark"]{--bg:#15171c;--fg:#e6e6e6;--muted:#a8a8a8;--navy:#9fb8e8;--blue:#8db3e6;--accent:#ff7b7b;--line:#4a4f5a;--thbg:#2e3440;--boxbg:#1e222a;--verdict:#1c2433;--est:#f0b45a;--cite:#8d93a0;--s0:#6ea0e0;--s1:#f0b73a;--s2:#5fc08a;--s3:#c79be6;--tb:#5a606c}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 "%(font)s","Malgun Gothic","맑은 고딕","Apple SD Gothic Neo","Noto Sans KR",sans-serif}
.top{border-bottom:1px solid var(--line);padding:8px 16px;font-style:italic;font-weight:700;font-size:12px;color:var(--muted)}
.bottom{border-top:1px solid var(--line);padding:8px 16px;font-style:italic;font-size:12px;color:var(--muted);text-align:center}
.wrap{max-width:900px;margin:0 auto;padding:0 16px 64px}
.cover{padding:56px 0 28px}.cover .t{color:var(--accent);font-size:32px;line-height:1.3;margin:0;font-weight:700}.cover .s{color:var(--accent);font-size:16px;margin:6px 0 4px}.cover .date{font-size:14px;color:var(--muted);margin:0 0 26px}
.cover .src{border:1px solid var(--fg);padding:12px 16px;font-size:13px;margin-top:22px}.cover .src p{margin:4px 0}
nav.toc{border:1px solid var(--line);padding:6px 18px 12px;margin:0 0 8px;background:var(--boxbg)}nav.toc h2{border:0;margin:8px 0 4px;font-size:17px}
nav.toc ul{list-style:none;margin:0;padding:0}nav.toc li{margin:2px 0}nav.toc .l1{font-weight:700;margin-top:6px}nav.toc .l2{padding-left:22px;font-size:14px}
nav.toc a{color:var(--fg);text-decoration:none}nav.toc a:hover{text-decoration:underline}
h1,h2{color:var(--navy);font-size:21px;margin:40px 0 12px;padding-bottom:4px;border-bottom:1px solid var(--line)}
h3{color:var(--navy);font-size:17px;margin:26px 0 8px}h4,h5,h6{color:var(--navy);font-size:15px;margin:18px 0 6px}
p{margin:0 0 10px}ul,ol{margin:0 0 12px;padding-left:22px}ol.plain{list-style:none;padding-left:10px}li{margin:3px 0}
.box{background:var(--boxbg);border:1px solid var(--line);padding:10px 14px;margin:0 0 14px;font-size:14px}.box p{margin:3px 0}
.verdict{background:var(--verdict);border-left:5px solid var(--navy);padding:8px 12px;margin:6px 0 14px}
.label{color:var(--navy);font-weight:700;margin:14px 0 4px}
.note,.source{font-size:12px;color:var(--muted);margin:2px 0}.source{font-style:italic;margin:4px 0 12px}
.cite{color:var(--cite);font-size:.92em}.est{color:var(--est)}
code{font:12.5px/1.4 Consolas,"Courier New",monospace;background:var(--boxbg);padding:1px 4px}
.closing{font-weight:700;color:var(--navy);margin-top:26px}
.tblwrap{margin:12px 0 4px}.cap{font-weight:700;font-size:13px;margin:0 0 4px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%%;font-size:13px}
th,td{border:1px solid var(--tb);padding:4px 8px;vertical-align:middle}
th{background:var(--thbg);text-align:center;font-weight:700}td.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin:14px 0 6px}
figure{margin:0;border:1px solid var(--line);padding:10px 12px}figcaption{font-weight:700;font-size:14px}.unit{font-weight:400;color:var(--muted);font-size:12px}
.legend{font-size:12px;margin:4px 0 0}.legend span{margin-right:14px}.sw{display:inline-block;width:10px;height:10px;margin-right:5px;vertical-align:-1px}
.chart{width:100%%;height:auto}.chart .axis{stroke:var(--line);stroke-width:1}
.chart .s0,.sw.s0{fill:var(--s0);background:var(--s0)}.chart .s1,.sw.s1{fill:var(--s1);background:var(--s1)}.chart .s2,.sw.s2{fill:var(--s2);background:var(--s2)}.chart .s3,.sw.s3{fill:var(--s3);background:var(--s3)}
.chart .lab{font-size:10.5px;fill:var(--fg)}.chart .cat{font-size:12px;fill:var(--muted)}.figsrc{font-size:11px;color:var(--muted);margin:2px 0 0}
@media print{nav.toc{break-after:page}h2{break-after:avoid}.tblwrap,figure,.verdict{break-inside:avoid}body{font-size:11pt}}
@media (max-width:560px){body{font-size:14px}.cover .t{font-size:25px}td:first-child,th:first-child{min-width:6.5em}}
"""


def build(data: dict, style: dict, out: Path) -> None:
    meta, blocks = data["meta"], data["blocks"]
    colors = style["colors"]
    chart_colors = (colors["chart"] * 4)[:4]
    css = CSS % {
        "font": style["font"], "navy": colors["navy"], "blue": colors["blue"], "accent": colors["accent"],
        "est": colors["est"], "s0": chart_colors[0], "s1": chart_colors[1], "s2": chart_colors[2], "s3": chart_colors[3],
    }
    slugs = _Slugs()
    toc, main = [], []
    for b in blocks:
        kind = b["type"]
        if b.get("is_caption"):
            continue
        if kind == "h":
            sid = slugs.make(b["text"])
            if b["lvl"] <= 3:
                cls = "l1" if b["lvl"] <= 2 else "l2"
                toc.append(f'<li class="{cls}"><a href="#{sid}">{E(b["text"])}</a></li>')
            main.append(f'<h{b["lvl"]} id="{sid}">{_runs(b["runs"])}</h{b["lvl"]}>')
        elif kind == "quote":
            main.append('<div class="box">' + "".join(f"<p>{_runs(p)}</p>" for p in b["paras"]) + "</div>")
        elif kind == "ul":
            main.append(_list(b["items"]))
        elif kind == "table":
            main.append(_table(b))
            if b.get("charts"):
                main.append('<div class="charts">' + "".join(_chart(c) for c in b["charts"]) + "</div>")
        elif b.get("closing"):
            main.append(f'<p class="closing">{_runs(b["runs"])}</p>')
        else:
            cls = "" if kind == "p" else f' class="{kind}"'
            main.append(f"<p{cls}>{_runs(b['runs'])}</p>")

    title = E(meta["title"])
    src = "".join(f"<p>{_runs(p)}</p>" for p in meta["cover"])
    if meta.get("closing"):
        src += f'<p><strong>{E(meta["closing"])}</strong></p>'
    cover = f'<header class="cover"><p class="t">{title}</p>'
    if meta.get("subtitle"):
        cover += f'<p class="s">{E(meta["subtitle"])}</p>'
    if meta.get("date"):
        cover += f'<p class="date">{E(meta["date"])}</p>'
    if src:
        cover += f'<div class="src">{src}</div>'
    cover += "</header>"
    nav = f'<nav class="toc"><h2>목 차</h2><ul>{"".join(toc)}</ul></nav>' if toc else ""
    top = f'<div class="top">{E(style["header"])}</div>' if style.get("header") else ""
    bottom = f'<div class="bottom">{E(style["footer"])}</div>' if style.get("footer") else ""
    doc = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
           f"<style>{css}</style></head><body>{top}<div class=\"wrap\">{cover}{nav}"
           f'<main>{"".join(main)}</main></div>{bottom}</body></html>')
    out.write_text(doc, encoding="utf-8")
