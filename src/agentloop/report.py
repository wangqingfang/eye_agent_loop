"""HTML 报告：单个文件，图表内嵌，断网也能双击打开。所有文本都经过 HTML 转义。"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from . import report_model

CSS = """
body{font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;max-width:1100px;
margin:24px auto;padding:0 20px;color:#222;line-height:1.6}
h1{border-bottom:3px solid #2c3e50;padding-bottom:8px}h2{border-left:6px solid #2c3e50;padding-left:10px;margin-top:40px}
h3{color:#2c3e50;margin-top:24px}table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
th,td{border:1px solid #ccc;padding:5px 8px;text-align:left;vertical-align:top}th{background:#ecf0f1}
tr:nth-child(even) td{background:#fafafa}.warn{background:#fff3cd;border:1px solid #e0b100;padding:8px 12px;margin:8px 0}
figure{margin:14px 0}figure img{max-width:100%}figcaption{font-size:12px;color:#555}a{color:#1a5fb4}
@media print{h2{page-break-before:always}}
"""


def _cell(c) -> str:
    if isinstance(c, dict):
        return f'<a href="{html.escape(c["href"], quote=True)}" target="_blank">{html.escape(str(c["text"]))}</a>'
    return html.escape(str(c))


def render_html(blocks) -> str:
    parts = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
             "<title>干眼共病研究循环 · 研究报告</title>", f"<style>{CSS}</style></head><body>"]
    for blk in blocks:
        kind = blk[0]
        if kind in ("h1", "h2", "h3"):
            parts.append(f"<{kind}>{html.escape(blk[1])}</{kind}>")
        elif kind == "p":
            parts.append(f"<p>{html.escape(blk[1])}</p>")
        elif kind == "warn":
            parts.append(f'<div class="warn">{html.escape(blk[1])}</div>')
        elif kind == "table":
            head = "".join(f"<th>{html.escape(h)}</th>" for h in blk[1])
            body = "".join("<tr>" + "".join(f"<td>{_cell(c)}</td>" for c in row) + "</tr>" for row in blk[2])
            parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif kind == "img":
            data = base64.b64encode(blk[1]).decode()
            parts.append(f'<figure><img src="data:image/png;base64,{data}"><figcaption>{html.escape(blk[2])}</figcaption></figure>')
    parts.append("<p style='color:#888;font-size:12px'>本报告由干眼共病研究循环自动生成。</p></body></html>")
    return "\n".join(parts)


def write_html(run_dir: Path, state, rounds, concl, ev, n_tests) -> Path:
    blocks = report_model.build(state, rounds, concl, ev, n_tests)
    path = Path(run_dir) / "研究报告.html"
    path.write_text(render_html(blocks), encoding="utf-8")
    return path
