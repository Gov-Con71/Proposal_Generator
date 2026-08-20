"""Real proposal-export renderers (Sprint 5).

Turns an assembled proposal (title + sections + compliance matrix) into actual
file bytes per format:

    pdf   → fpdf2 (already a dependency, used by the RFP toolchain)
    xlsx  → openpyxl (pulled in by markitdown[all])
    zip   → stdlib zipfile (proposal.md + compliance.csv)
    docx  → hand-rolled minimal WordprocessingML (stdlib zipfile — no new dep)

The worker (`export_service.run_export_render`) builds the `ExportDoc` from the
DB and calls `render`. Keeping assembly (service) separate from formatting
(here) means new formats slot in without touching the pipeline.
"""

import csv
import io
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "zip": "application/zip",
}


@dataclass
class ExportDoc:
    title: str
    subtitle: str = ""
    sections: list[dict] = field(default_factory=list)      # {title, content}
    requirements: list[dict] = field(default_factory=list)  # {number, section, text, status}


def render(fmt: str, doc: ExportDoc) -> tuple[bytes, str]:
    """Returns (bytes, mime_type) for the requested format."""
    renderers = {"pdf": _render_pdf, "docx": _render_docx, "xlsx": _render_xlsx, "zip": _render_zip}
    if fmt not in renderers:
        raise ValueError(f"Unsupported export format: {fmt!r}")
    return renderers[fmt](doc), MIME[fmt]


# --- PDF (fpdf2) ------------------------------------------------------------

def _latin1(text: str) -> str:
    """fpdf2's core fonts are latin-1 only; drop characters it can't encode."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


# Headings, bullets, and bold spans in drafted content are parsed by
# markdown_lite and rendered with real formatting instead of dumping the raw
# `##`/`-`/`**` Markdown syntax as literal characters into the delivered
# document — see markdown_lite's module docstring for why that used to happen.
_PDF_HEADING_SIZES = {1: 15, 2: 13, 3: 12, 4: 11, 5: 11, 6: 11}
_PDF_BODY_SIZE = 11
_PDF_LINE_HEIGHT = 6
# Latin-1 (fpdf2's core-font encoding) middle dot — a plain "•" (U+2022) falls
# outside Latin-1 and would silently become "?" via `_latin1`'s replace-on-encode.
_PDF_BULLET = "·"


def _emit_pdf_block(pdf, blk) -> None:
    if blk.kind == "heading":
        size = _PDF_HEADING_SIZES.get(blk.level, _PDF_BODY_SIZE)
        pdf.ln(2)
        for text, _bold in blk.runs:  # headings render bold regardless of ** markers
            pdf.set_font("Helvetica", "B", size)
            pdf.write(_PDF_LINE_HEIGHT, _latin1(text))
        pdf.ln(_PDF_LINE_HEIGHT)
        pdf.ln(1)
        return

    if blk.kind == "bullet":
        pdf.set_x(pdf.l_margin + 5)
        pdf.set_font("Helvetica", "", _PDF_BODY_SIZE)
        pdf.write(_PDF_LINE_HEIGHT, _latin1(f"{_PDF_BULLET} "))
        for text, is_bold in blk.runs:
            pdf.set_font("Helvetica", "B" if is_bold else "", _PDF_BODY_SIZE)
            pdf.write(_PDF_LINE_HEIGHT, _latin1(text))
        pdf.ln(_PDF_LINE_HEIGHT)
        return

    for text, is_bold in blk.runs:
        pdf.set_font("Helvetica", "B" if is_bold else "", _PDF_BODY_SIZE)
        pdf.write(_PDF_LINE_HEIGHT, _latin1(text))
    pdf.ln(_PDF_LINE_HEIGHT)
    pdf.ln(1)


def _render_pdf(doc: ExportDoc) -> bytes:
    from fpdf import FPDF

    from app.services.markdown_lite import parse as parse_markdown

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # new_x=LMARGIN resets the cursor to the left margin after each block so the
    # next full-width (w=0) multi_cell always has horizontal space.
    def block(text: str, height: float) -> None:
        pdf.multi_cell(0, height, _latin1(text), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 18)
    block(doc.title, 10)
    if doc.subtitle:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(90, 90, 90)
        block(doc.subtitle, 7)
        pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    for section in doc.sections:
        pdf.set_font("Helvetica", "B", 13)
        block(section.get("title", "Untitled section"), 8)
        content = section.get("content") or "(no content)"
        for blk in parse_markdown(content):
            _emit_pdf_block(pdf, blk)
        pdf.ln(3)

    if doc.requirements:
        pdf.set_font("Helvetica", "B", 14)
        block("Compliance Matrix", 9)
        pdf.set_font("Helvetica", "", 10)
        for r in doc.requirements:
            block(f"#{r.get('number', '')} [{r.get('section', '')}] ({r.get('status', '')}): {r.get('text', '')}", 6)

    # fpdf2 returns a bytearray from output(); normalise to bytes.
    return bytes(pdf.output())


# --- XLSX (openpyxl) --------------------------------------------------------

def _render_xlsx(doc: ExportDoc) -> bytes:
    from openpyxl import Workbook

    from app.services.markdown_lite import parse as parse_markdown
    from app.services.markdown_lite import to_plain_text

    wb = Workbook()
    ws = wb.active
    ws.title = "Proposal"
    ws.append([doc.title])
    if doc.subtitle:
        ws.append([doc.subtitle])
    ws.append([])
    ws.append(["Section", "Content"])
    for section in doc.sections:
        content = to_plain_text(parse_markdown(section.get("content") or ""))
        ws.append([section.get("title", ""), content])

    grid = wb.create_sheet("Compliance Matrix")
    grid.append(["#", "Section", "Status", "Requirement"])
    for r in doc.requirements:
        grid.append([r.get("number", ""), r.get("section", ""), r.get("status", ""), r.get("text", "")])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- ZIP (stdlib) -----------------------------------------------------------

def _render_zip(doc: ExportDoc) -> bytes:
    md = [f"# {doc.title}", ""]
    if doc.subtitle:
        md.append(f"_{doc.subtitle}_\n")
    for section in doc.sections:
        md.append(f"## {section.get('title', 'Untitled section')}\n")
        md.append((section.get("content") or "(no content)") + "\n")

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["number", "section", "status", "text"])
    for r in doc.requirements:
        writer.writerow([r.get("number", ""), r.get("section", ""), r.get("status", ""), r.get("text", "")])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("proposal.md", "\n".join(md))
        zf.writestr("compliance.csv", csv_buf.getvalue())
    return buf.getvalue()


# --- DOCX (hand-rolled WordprocessingML, stdlib zipfile) --------------------

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


def _para(text: str, bold: bool = False, size: int | None = None) -> str:
    """One WordprocessingML paragraph. `size` is half-points (e.g. 36 = 18pt)."""
    run_props = ""
    if bold or size:
        run_props = "<w:rPr>" + ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/>' if size else "") + "</w:rPr>"
    return f'<w:p><w:r>{run_props}<w:t xml:space="preserve">{escape(text or "")}</w:t></w:r></w:p>'


def _para_runs(runs, *, size: int | None = None) -> str:
    """One WordprocessingML paragraph with several runs, each independently
    bold or not (e.g. a sentence with an inline `**bold**` span) — `_para`
    only supports one run, uniformly formatted."""
    run_xml = []
    for text, bold in runs:
        props = ""
        if bold or size:
            props = "<w:rPr>" + ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/>' if size else "") + "</w:rPr>"
        run_xml.append(f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')
    return f"<w:p>{''.join(run_xml)}</w:p>"


# Headings, bullets, and bold spans in drafted content are parsed by
# markdown_lite and rendered as real WordprocessingML formatting instead of
# dumping raw `##`/`-`/`**` Markdown syntax as literal text — see
# markdown_lite's module docstring for why that used to happen.
_DOCX_HEADING_SIZES = {1: 32, 2: 26, 3: 24, 4: 22, 5: 22, 6: 22}


def _docx_block(blk) -> str:
    if blk.kind == "heading":
        size = _DOCX_HEADING_SIZES.get(blk.level, 22)
        return _para_runs([(text, True) for text, _bold in blk.runs], size=size)
    if blk.kind == "bullet":
        return _para_runs([("• ", False)] + blk.runs)
    return _para_runs(blk.runs)


def _render_docx(doc: ExportDoc) -> bytes:
    from app.services.markdown_lite import parse as parse_markdown

    body = [_para(doc.title, bold=True, size=36)]
    if doc.subtitle:
        body.append(_para(doc.subtitle, size=22))
    for section in doc.sections:
        body.append(_para(section.get("title", "Untitled section"), bold=True, size=28))
        content = section.get("content") or "(no content)"
        body.extend(_docx_block(blk) for blk in parse_markdown(content))
    if doc.requirements:
        body.append(_para("Compliance Matrix", bold=True, size=30))
        for r in doc.requirements:
            body.append(
                _para(f"#{r.get('number', '')} [{r.get('section', '')}] ({r.get('status', '')}): {r.get('text', '')}")
            )

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(body) + "</w:body></w:document>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _ROOT_RELS)
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()
