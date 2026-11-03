"""Word 导出：与 HTML 报告内容一致，图表以图片形式嵌入。"""

from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import report_model


def _font(doc):
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(9.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def render_docx(blocks) -> Document:
    doc = Document()
    _font(doc)
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    for m in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, m, Cm(1.6))
    for blk in blocks:
        kind = blk[0]
        if kind in ("h1", "h2", "h3"):
            doc.add_heading(blk[1], level={"h1": 0, "h2": 1, "h3": 2}[kind])
        elif kind == "p":
            doc.add_paragraph(blk[1])
        elif kind == "warn":
            run = doc.add_paragraph().add_run("注意：" + blk[1])
            run.font.color.rgb = RGBColor(0x9A, 0x6A, 0x00)
        elif kind == "table":
            table = doc.add_table(rows=1, cols=len(blk[1]))
            table.style = "Table Grid"
            for cell, text in zip(table.rows[0].cells, blk[1]):
                cell.text = str(text)
                for r in cell.paragraphs[0].runs:
                    r.font.bold = True
            for row in blk[2]:
                cells = table.add_row().cells
                for cell, value in zip(cells, row):
                    cell.text = str(value["text"] if isinstance(value, dict) else value)
        elif kind == "img":
            doc.add_picture(io.BytesIO(blk[1]), width=Cm(22))
            doc.add_paragraph(blk[2]).runs[0].font.size = Pt(8)
    return doc


def write_docx(run_dir: Path, state, rounds, concl, ev, n_tests) -> Path:
    blocks = report_model.build(state, rounds, concl, ev, n_tests)
    path = Path(run_dir) / "研究报告.docx"
    render_docx(blocks).save(path)
    return path
