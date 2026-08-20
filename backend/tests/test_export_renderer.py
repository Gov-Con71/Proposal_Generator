"""Export renderer formatting (export_renderer.py).

Verifies the actual rendered bytes, not just that markdown_lite parses
correctly in isolation — the bug this fixes was in the renderers dumping raw
Markdown as literal text, so these tests inspect real PDF/DOCX/XLSX output.
"""

import io
import zipfile

from app.services.export_renderer import ExportDoc, render

_MARKDOWN_CONTENT = (
    "## Understanding of the Requirement\n\n"
    "We understand the need for depot-level pump overhaul services.\n\n"
    "## Technical Approach\n\n"
    "Our approach includes:\n"
    "- Certified technicians perform teardown and inspection\n"
    "- OEM-spec parts sourced from approved vendors\n\n"
    "**Differentiators:** Our team holds an active CMMC Level 2 certification."
)


def _doc(content: str = _MARKDOWN_CONTENT) -> ExportDoc:
    return ExportDoc(
        title="Test Proposal",
        subtitle="Compliance score: 92% · 4 requirements",
        sections=[{"title": "Technical Approach", "content": content}],
        requirements=[{"number": 1, "section": "C.3.1", "status": "addressed", "text": "Overhaul pumps."}],
    )


# --- PDF -------------------------------------------------------------------

def test_pdf_does_not_contain_literal_markdown_syntax():
    import pdfplumber

    pdf_bytes, _ = render("pdf", _doc())
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text()

    assert "##" not in text
    assert "**" not in text
    assert "\n- " not in text
    assert "Certified technicians perform teardown" in text
    assert "Differentiators:" in text


def test_pdf_bold_span_actually_uses_a_bold_font():
    import pdfplumber

    pdf_bytes, _ = render("pdf", _doc())
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        chars = pdf.pages[0].chars

    # "Differentiators:" is a **bold** span in the source — its characters
    # must actually be set in a bold font, not merely present as plain text.
    bold_chars = [c for c in chars if "Bold" in c.get("fontname", "")]
    bold_text = "".join(c["text"] for c in bold_chars)
    assert "Differentiators" in bold_text


def test_pdf_heading_renders_larger_than_body_text():
    import pdfplumber

    pdf_bytes, _ = render("pdf", _doc())
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        chars = pdf.pages[0].chars

    heading_size = next(c["size"] for c in chars if c["text"] == "U")  # "Understanding..."
    body_size = next(c["size"] for c in chars if c["text"] == "W")  # "We understand..."
    assert heading_size > body_size


# --- DOCX --------------------------------------------------------------------

def _docx_xml(content: str = _MARKDOWN_CONTENT) -> str:
    docx_bytes, _ = render("docx", _doc(content))
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        return z.read("word/document.xml").decode()


def test_docx_does_not_contain_literal_markdown_syntax():
    xml = _docx_xml()
    assert "##" not in xml
    assert "**" not in xml


def test_docx_bold_span_is_its_own_bold_run():
    xml = _docx_xml()
    # The bold span must be a separate <w:r> carrying <w:b/>, distinct from the
    # surrounding plain-text run(s) in the same paragraph.
    assert "<w:b/><w:t xml:space=\"preserve\">Differentiators:" in xml or (
        "<w:b/>" in xml and "Differentiators:" in xml
    )
    assert "<w:t xml:space=\"preserve\">Differentiators:</w:t>" in xml


def test_docx_bullet_items_are_present_with_a_marker():
    xml = _docx_xml()
    assert "Certified technicians perform teardown" in xml
    assert "•" in xml


# --- XLSX ----------------------------------------------------------------------

def test_xlsx_does_not_contain_literal_markdown_syntax():
    from openpyxl import load_workbook

    xlsx_bytes, _ = render("xlsx", _doc())
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb["Proposal"]
    content_cell = [row for row in ws.iter_rows(values_only=True)][-1][1]

    assert "##" not in content_cell
    assert "**" not in content_cell
    assert "Certified technicians" in content_cell


# --- ZIP (Markdown is the native format — must be left untouched) --------------

# --- regression: real drafted content that surfaced two bugs -------------------
# (1) a multi-requirement tag "[Req 1, Req 2, Req 3, Req 4]" (repeated "Req"
#     prefix) wasn't stripped by the original single-prefix regex.
# (2) one of the four canonical section headings came back from the model
#     without its "##" marker and silently rendered as plain body text.

_REAL_DRAFTED_CONTENT = (
    "## Understanding of the Requirement\n\n"
    "We understand the critical nature of ensuring that all items are properly "
    "inspected and preserved according to the detailed provisions outlined in "
    "Table G-I. [Req 1, Req 2, Req 3, Req 4]\n\n"
    " Technical Approach\n\n"
    "### Visual Inspections\n\n"
    "Our team will conduct comprehensive visual inspections. Key inspection "
    "points include:\n\n"
    "- **Handling Contamination:** We will inspect items for any signs of "
    "contamination due to handling after cleaning. [Req 1]\n\n"
    "## Differentiators\n\n"
    "- **Comprehensive Inspection Protocols:** Our team is trained to conduct "
    "thorough visual inspections. [Req 1]\n\n"
    "By implementing these protocols, we are committed to delivering items "
    "that meet or exceed requirements. [Req 1, Req 2, Req 3, Req 4]"
)


def test_real_drafted_content_has_no_requirement_tags_or_markdown_syntax_after_export():
    from app.services.export_service import _strip_requirement_tags

    stripped = _strip_requirement_tags(_REAL_DRAFTED_CONTENT)
    assert "[Req" not in stripped

    pdf_bytes, _ = render("pdf", _doc(stripped))
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text()

    assert "[Req" not in text
    assert "##" not in text
    assert "**" not in text


def test_real_drafted_contents_unmarked_canonical_heading_still_renders_as_a_heading():
    from app.services.export_service import _strip_requirement_tags

    stripped = _strip_requirement_tags(_REAL_DRAFTED_CONTENT)
    pdf_bytes, _ = render("pdf", _doc(stripped))
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        chars = pdf.pages[0].chars

    # "Technical Approach" had no "##" in the source. Its "T" must render at
    # heading size/weight, matching "Differentiators" (a real "##" heading),
    # not at body-text size like the "T" that starts "Table G-I" (body prose).
    def char_after(word: str) -> dict:
        idx = next(i for i in range(len(chars) - len(word)) if "".join(c["text"] for c in chars[i:i+len(word)]) == word)
        return chars[idx]

    technical_t = char_after("Technical Approach")
    differentiators_d = char_after("Differentiators")
    body_t = char_after("Table G-I")

    assert technical_t["size"] == differentiators_d["size"]
    assert "Bold" in technical_t["fontname"]
    assert technical_t["size"] > body_t["size"]


def test_zip_export_keeps_raw_markdown_since_that_is_its_native_format():
    zip_bytes, _ = render("zip", _doc())
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        proposal_md = z.read("proposal.md").decode()

    assert "## Understanding of the Requirement" in proposal_md
    assert "**Differentiators:**" in proposal_md
