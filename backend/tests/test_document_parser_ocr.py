"""OCR fallback for scanned/image-only PDF pages (document_parser.py).

Generates real image-only PDF pages (a PIL-rendered text image embedded via
fpdf2, no PDF text layer at all) rather than fixture binaries, so pdfplumber's
own text extraction genuinely finds nothing and the OCR path is exercised for
real — not mocked. Requires the `tesseract-ocr` system binary (installed in
Dockerfile.backend's runtime stage); these tests only run where it's present.
"""

import asyncio
import shutil

import pytest

import app.services.document_parser as dp

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract-ocr binary not installed"
)


def _text_image_pdf(path, *, lines: list[str], width=1000, height=300):
    """A one-page PDF that is purely an embedded image of `lines` — no PDF text
    layer at all, so pdfplumber/MarkItDown extract nothing from it natively."""
    from fpdf import FPDF
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=48)
    y = 20
    for line in lines:
        draw.text((20, y), line, fill="black", font=font)
        y += 60
    img_path = path.parent / f"{path.stem}_source.png"
    img.save(img_path)

    pdf = FPDF(unit="pt", format=(width, height))
    pdf.add_page()
    pdf.image(str(img_path), x=0, y=0, w=width, h=height)
    pdf.output(str(path))


def _native_text_pdf(path, *, heading: str, prose: str):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, heading, new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 8, prose, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def test_fully_scanned_pdf_is_read_via_ocr(tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _text_image_pdf(pdf_path, lines=["REQUIREMENTS DOCUMENT", "SOLICITATION NUMBER ABCDE"])

    text = asyncio.run(dp.parse_to_markdown(str(pdf_path)))

    assert "REQUIREMENTS DOCUMENT" in text.upper()
    assert "SOLICITATION NUMBER" in text.upper()


def test_ocr_only_used_for_pages_missing_a_text_layer(tmp_path, caplog):
    """A hybrid PDF (one native-text page, one scanned page) should extract the
    native page normally and OCR only the scanned one — not the whole document."""
    import fitz

    native_path = tmp_path / "native_only.pdf"
    scanned_path = tmp_path / "scanned_only.pdf"
    _native_text_pdf(native_path, heading="C.1 Scope of Work", prose="The contractor shall perform the work.")
    _text_image_pdf(scanned_path, lines=["SIGNED COVER LETTER EXHIBIT"])

    merged_path = tmp_path / "hybrid.pdf"
    merged = fitz.open()
    with fitz.open(str(native_path)) as native_doc:
        merged.insert_pdf(native_doc)
    with fitz.open(str(scanned_path)) as scanned_doc:
        merged.insert_pdf(scanned_doc)
    merged.save(str(merged_path))
    merged.close()

    with caplog.at_level("INFO", logger="app.services.document_parser"):
        text = asyncio.run(dp.parse_to_markdown(str(merged_path)))

    assert "C.1 Scope of Work" in text
    assert "The contractor shall perform the work." in text
    assert "SIGNED COVER LETTER EXHIBIT" in text.upper()
    # The OCR-used log line names the scanned page (2), confirming the native
    # page (1) was not sent through OCR at all.
    messages = [r.getMessage() for r in caplog.records]
    assert any("page 2" in m and "used OCR" in m for m in messages)
    assert not any("page 1 " in m and "used OCR" in m for m in messages)


def test_ocr_of_a_blank_page_yields_no_text_but_does_not_crash(tmp_path):
    from fpdf import FPDF

    blank_path = tmp_path / "blank.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.output(str(blank_path))

    with pytest.raises(dp.DocumentParseError):
        asyncio.run(dp.parse_to_markdown(str(blank_path)))


def test_garbled_ocr_output_is_rejected_in_favor_of_the_sparse_original(tmp_path, monkeypatch, caplog):
    """A low-quality scan can make OCR confidently wrong (glyph soup) rather
    than empty. The quality gate must not let that overwrite pdfplumber's
    (sparse but not actively wrong) original just because it's longer."""
    pdf_path = tmp_path / "scanned.pdf"
    _text_image_pdf(pdf_path, lines=["REQUIREMENTS DOCUMENT"])

    monkeypatch.setattr(dp, "_ocr_page", lambda *a, **kw: "░▒▓█▄▀■□▲▼◆●○♠♣♥♦Ω≈ç√∫˜µ≤≥÷¡™£¢∞¶•ªº–≠")

    with caplog.at_level("WARNING", logger="app.services.document_parser"):
        # Both tiers now fail to find anything trustworthy: pdfplumber's
        # original is empty (image-only page) and the OCR stand-in is garbage,
        # so this should raise rather than silently accept the garbled text.
        with pytest.raises(dp.DocumentParseError):
            asyncio.run(dp.parse_to_markdown(str(pdf_path)))

    messages = [r.getMessage() for r in caplog.records]
    assert any("OCR output looks garbled" in m for m in messages)
