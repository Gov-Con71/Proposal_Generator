"""Table-aware PDF parsing (document_parser.py).

Exercises the pdfplumber-based table extraction path added to preserve
pricing/eval-matrix tables that MarkItDown's layout-blind text extraction
would otherwise flatten. Generates real PDFs with fpdf2 (already a test/runtime
dependency) rather than fixture binaries, so the tests describe exactly what
input produces what output.
"""

import asyncio
import os

import pytest

import app.services.document_parser as dp


def _make_pdf_with_table(path, *, heading: str, prose: str, rows: list[list[str]]) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, heading, new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 8, prose, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    col_width = 190 / len(rows[0])
    for row in rows:
        for cell in row:
            pdf.cell(col_width, 8, cell, border=1)
        pdf.ln(8)
    pdf.output(str(path))


def _make_text_only_pdf(path, *, heading: str, prose: str) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, heading, new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 8, prose, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


# --- _rows_to_markdown_table -------------------------------------------------

def test_rows_to_markdown_table_renders_header_and_body():
    rows = [["Item", "Qty", "Unit Price"], ["Widget A", "10", "$5.00"]]
    table = dp._rows_to_markdown_table(rows)
    lines = table.splitlines()
    assert lines[0] == "| Item | Qty | Unit Price |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| Widget A | 10 | $5.00 |"


def test_rows_to_markdown_table_pads_ragged_rows():
    rows = [["A", "B", "C"], ["only one"]]
    table = dp._rows_to_markdown_table(rows)
    assert table.splitlines()[2] == "| only one |  |  |"


def test_rows_to_markdown_table_escapes_pipes_and_newlines():
    rows = [["Header"], ["a|b\nc"]]
    table = dp._rows_to_markdown_table(rows)
    assert "a\\|b c" in table


def test_rows_to_markdown_table_empty_input():
    assert dp._rows_to_markdown_table([]) == ""


# --- parse_to_markdown: table-aware PDF path ---------------------------------

def test_pdf_with_table_extracts_body_text_and_markdown_table(tmp_path):
    pdf_path = tmp_path / "rfp_with_pricing.pdf"
    _make_pdf_with_table(
        pdf_path,
        heading="Section C.1 Pricing",
        prose="The contractor shall price each line item as follows.",
        rows=[["Item", "Qty", "Unit Price"], ["Widget A", "10", "$5.00"], ["Widget B", "20", "$3.50"]],
    )

    text = asyncio.run(dp.parse_to_markdown(str(pdf_path)))

    assert "Section C.1 Pricing" in text
    assert "The contractor shall price each line item as follows." in text
    assert "| Item | Qty | Unit Price |" in text
    assert "| Widget A | 10 | $5.00 |" in text


def test_pdf_table_cells_are_not_duplicated_into_body_text(tmp_path):
    """Table content must appear once, as a table — not once flat and once structured."""
    pdf_path = tmp_path / "rfp_with_pricing.pdf"
    _make_pdf_with_table(
        pdf_path,
        heading="Section C.1 Pricing",
        prose="See the schedule below.",
        rows=[["Item", "Qty"], ["UniqueWidgetName", "42"]],
    )

    text = asyncio.run(dp.parse_to_markdown(str(pdf_path)))

    # The cell text appears exactly once (inside the rendered table), not a
    # second time flattened into the surrounding body-text extraction.
    assert text.count("UniqueWidgetName") == 1


def test_pdf_without_a_table_falls_back_to_plain_text_extraction(tmp_path):
    pdf_path = tmp_path / "rfp_no_table.pdf"
    _make_text_only_pdf(
        pdf_path, heading="Section C.2 Scope", prose="The contractor shall deliver services as described."
    )

    text = asyncio.run(dp.parse_to_markdown(str(pdf_path)))

    assert "Section C.2 Scope" in text
    assert "The contractor shall deliver services as described." in text
    assert "|" not in text  # no table markup fabricated for a table-free page


def test_corrupt_pdf_falls_back_to_markitdown_then_raises(tmp_path):
    """A file with a .pdf suffix but no valid PDF structure (content sniffing
    correctly says "not a PDF", so the pdfplumber tier isn't even attempted)
    falls straight to MarkItDown, which also fails on random binary garbage
    (not text-like garbage, which MarkItDown would happily read as plaintext),
    and the result must surface as DocumentParseError, not an unhandled exception."""
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(os.urandom(2000))

    with pytest.raises(dp.DocumentParseError):
        asyncio.run(dp.parse_to_markdown(str(bad_pdf)))


def test_nonexistent_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        asyncio.run(dp.parse_to_markdown("/nonexistent/path/document.pdf"))


def test_non_pdf_format_still_uses_markitdown(tmp_path):
    """Non-PDF formats are unaffected by the new PDF path (still MarkItDown)."""
    txt_path = tmp_path / "rfp.txt"
    txt_path.write_text("Section H.2 MFA is REQUIRED for all privileged access.")

    text = asyncio.run(dp.parse_to_markdown(str(txt_path)))

    assert "MFA is REQUIRED" in text


# --- _looks_like_pdf: content, not filename extension -------------------------

def test_looks_like_pdf_true_for_a_real_pdf(tmp_path):
    pdf_path = tmp_path / "rfp.pdf"
    _make_text_only_pdf(pdf_path, heading="C.1", prose="text")
    assert dp._looks_like_pdf(pdf_path) is True


def test_looks_like_pdf_false_for_plaintext_named_dot_pdf(tmp_path):
    fake_pdf = tmp_path / "not_really.pdf"
    fake_pdf.write_text("Section H.2 MFA is REQUIRED.")
    assert dp._looks_like_pdf(fake_pdf) is False


def test_looks_like_pdf_true_regardless_of_extension(tmp_path):
    """A real PDF saved with no/wrong extension is still detected by content —
    the point of sniffing bytes instead of trusting the filename."""
    real_pdf_wrong_ext = tmp_path / "rfp.docx"
    _make_text_only_pdf(real_pdf_wrong_ext, heading="C.1", prose="text")
    assert dp._looks_like_pdf(real_pdf_wrong_ext) is True


def test_mislabeled_plaintext_pdf_is_parsed_via_markitdown_not_pdfplumber(tmp_path, caplog):
    """A plaintext file uploaded with a .pdf extension must be routed by its
    real content: content sniffing skips the pdfplumber tier entirely (no
    wasted/misleading "table-aware PDF parse failed" attempt) and MarkItDown's
    own content-based sniffing recovers the real text."""
    fake_pdf = tmp_path / "mislabeled.pdf"
    fake_pdf.write_text("Section H.2 MFA is REQUIRED for all privileged access.")

    with caplog.at_level("WARNING", logger="app.services.document_parser"):
        text = asyncio.run(dp.parse_to_markdown(str(fake_pdf)))

    assert "MFA is REQUIRED" in text
    assert not any("table-aware PDF parse failed" in r.getMessage() for r in caplog.records)


# --- _text_quality_ok: garbled/OCR-misread text detection ---------------------

def test_text_quality_ok_for_clean_prose():
    assert dp._text_quality_ok(
        "Section C.1 Scope of Work. The contractor shall deliver services as "
        "described in this solicitation, in accordance with FAR 52.212-4."
    )


def test_text_quality_not_ok_for_symbol_soup():
    # Genuine OCR-misread glyph soup, not common RFP punctuation ($, %, § etc.
    # are deliberately allowed — see test below) — box-drawing/math/currency
    # symbols outside any legitimate prose character set.
    assert not dp._text_quality_ok("░▒▓█▄▀■□▲▼◆●○♠♣♥♦Ω≈ç√∫˜µ≤≥÷¡™£¢∞¶•ªº–≠")


def test_text_quality_not_ok_for_text_below_the_minimum_length():
    assert not dp._text_quality_ok("Hi.")


def test_text_quality_ok_tolerates_normal_punctuation_density():
    """Legitimate RFP text is punctuation-heavy (clause numbers, $, %, dates) —
    the gate must not flag that as noise."""
    assert dp._text_quality_ok(
        "Per FAR 52.219-14(b)(1), at least 50% of the cost of contract "
        "performance ($1,250,000.00) incurred for personnel shall be expended "
        "for employees of the concern (14 CFR 121.5; see also 15 U.S.C. § 632)."
    )
