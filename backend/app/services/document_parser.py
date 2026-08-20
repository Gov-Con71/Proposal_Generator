import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DocumentParseError(Exception):
    """Raised when no parsing strategy can produce usable text from a document."""


# ---------------------------------------------------------------------------
# Table-aware PDF parsing (pdfplumber), with per-page OCR fallback
#
# MarkItDown's PDF text extraction is layout-blind: cells of a pricing grid or
# evaluation matrix collapse into a flat run of words with no row/column
# structure, which is exactly the content an RFP's compliance-critical tables
# tend to carry. pdfplumber (already a dependency) is used for PDFs instead:
# per page, detected tables are rendered as Markdown tables, and everything
# else on the page is extracted as body text with the table regions excluded
# (so table cell text isn't duplicated into the surrounding prose).
#
# Neither pdfplumber nor MarkItDown can read a page that has no text layer at
# all — a scanned exhibit, a signed cover letter dropped in as an image, an
# entire RFP that's just a scan. A government RFP is frequently a mix: a few
# scanned attachments inside an otherwise native-text document, not uniformly
# one or the other. So OCR here is a *per-page* fallback, not a whole-document
# one: each page is rasterized (PyMuPDF, already a dependency) and run through
# Tesseract only if pdfplumber found next to nothing on that specific page —
# a document that's 40 native pages and 2 scanned exhibits pays the OCR cost
# for exactly those 2 pages, not all 42. MarkItDown remains the whole-document
# fallback if pdfplumber can't open the file at all (e.g. certain malformed/
# encrypted PDFs); OCR is not repeated at that tier.
# ---------------------------------------------------------------------------

# Below this many characters, a page's extracted text is treated as
# effectively empty — not literally zero (a stray header/footer artifact can
# survive extraction from an otherwise fully scanned page) but too sparse to
# be the page's real content, so OCR is worth trying for that page.
_MIN_CHARS_PER_PAGE = 20


# ---------------------------------------------------------------------------
# Content-based PDF detection
#
# The PDF-specific tier above used to be gated on the upload's filename
# extension alone. A file's actual bytes are what determine whether it's a
# PDF, not what a user (or an upstream system) happened to name it — a
# mislabeled or extensionless upload was already recovered correctly by
# MarkItDown's own content sniffing, but silently skipped the table-aware/OCR
# tier entirely, since that tier never even attempted a PDF genuinely worth
# extracting tables/scans from. Sniffing the real signature routes by what the
# file actually is.
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF-"
# Some PDF producers prepend a small amount of leading junk (whitespace, a
# BOM) before the header; the spec itself only guarantees it appears within
# the file's first 1024 bytes, so that's the read window checked.
_PDF_MAGIC_WINDOW = 1024


def _looks_like_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            header = f.read(_PDF_MAGIC_WINDOW)
    except OSError:
        return False
    return _PDF_MAGIC in header


# ---------------------------------------------------------------------------
# Parse-quality gate
#
# A page whose text came back non-empty isn't necessarily usable: a low-
# quality scan can produce OCR output that's confidently wrong (misread
# digits, glyph soup) rather than empty, which would otherwise sail through
# every check above as a "successful" extraction. `_text_quality_ok` is a
# cheap, conservative signal — a high ratio of characters that are neither
# alphanumeric, whitespace, nor common prose punctuation is the fingerprint of
# OCR misreads or a font-encoding mismatch (mojibake), not of legitimate RFP
# text (which is punctuation-heavy but not symbol-heavy). Used to (a) decide
# whether a page's OCR output is trustworthy enough to prefer over pdfplumber's
# sparse original, and (b) flag (never block — the heuristic is deliberately
# conservative to avoid rejecting real, just unusual, text) the final parsed
# document for a human to double-check.
# ---------------------------------------------------------------------------

_MAX_NOISE_RATIO = 0.35
_MIN_QUALITY_CHECK_CHARS = 10
_ALLOWED_PUNCTUATION = set(" \n\t.,;:!?()[]{}\"'-/%$&@#*+=<>|\\_~^`")


def _text_quality_ok(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < _MIN_QUALITY_CHECK_CHARS:
        return False
    noise = sum(1 for c in stripped if not c.isalnum() and c not in _ALLOWED_PUNCTUATION)
    return (noise / len(stripped)) <= _MAX_NOISE_RATIO


def _warn_if_low_quality(text: str, name: str) -> None:
    if not _text_quality_ok(text):
        logger.warning(
            "parse_to_markdown: extracted text for '%s' looks low-quality (high "
            "symbol/noise ratio) — parsing may have partially failed; verify the "
            "compliance matrix against the source document.",
            name,
        )


def _rows_to_markdown_table(rows: list[list[str | None]]) -> str:
    """Renders a pdfplumber table's extracted rows as a GitHub-flavored Markdown table."""
    if not rows:
        return ""
    width = max(len(row) for row in rows)

    def _clean(cell: str | None) -> str:
        return (cell or "").strip().replace("\n", " ").replace("|", "\\|")

    padded = [[_clean(c) for c in row] + [""] * (width - len(row)) for row in rows]
    header, *body = padded
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _extract_page_markdown(page) -> str:
    """Body text + Markdown-rendered tables for one pdfplumber page, in that order.

    Table cell text is excluded from the body-text extraction (rather than left
    in) so a table's content appears exactly once, as a table, not once flat and
    once structured.
    """
    tables = page.find_tables()
    if not tables:
        return page.extract_text() or ""

    bboxes = [t.bbox for t in tables]

    def _inside_a_table(obj: dict) -> bool:
        if obj.get("object_type") != "char":
            return False
        x_mid = (obj["x0"] + obj["x1"]) / 2
        y_mid = (obj["top"] + obj["bottom"]) / 2
        return any(
            x0 <= x_mid <= x1 and top <= y_mid <= bottom for x0, top, x1, bottom in bboxes
        )

    body_text = (page.filter(lambda o: not _inside_a_table(o)).extract_text() or "").strip()
    table_blocks = [_rows_to_markdown_table(t.extract() or []) for t in tables]
    table_blocks = [b for b in table_blocks if b]

    blocks = ([body_text] if body_text else []) + table_blocks
    return "\n\n".join(blocks)


def _ocr_page(fitz_page, *, dpi: int = 200) -> str:
    """Rasterizes one PyMuPDF page and runs Tesseract OCR over it.

    Failures (missing tesseract binary, a page image OCR chokes on) are
    swallowed and return "" — the caller already has pdfplumber's (sparse)
    text for this page to fall back on, so an OCR failure loses nothing it
    didn't already not have.
    """
    import fitz
    import pytesseract
    from PIL import Image

    try:
        zoom = dpi / 72  # PDF units are 72/inch; scale the raster to the target DPI.
        pix = fitz_page.get_pixmap(
            matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False
        )
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(image)
    except Exception as exc:
        logger.warning("_ocr_page: OCR failed for page %d — %s", fitz_page.number + 1, exc)
        return ""


def _parse_pdf_with_tables(path: Path) -> str:
    import fitz
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf, fitz.open(str(path)) as fitz_doc:
        pages = []
        for i, page in enumerate(pdf.pages):
            content = _extract_page_markdown(page)
            if len(content.strip()) < _MIN_CHARS_PER_PAGE and i < fitz_doc.page_count:
                ocr_text = _ocr_page(fitz_doc[i]).strip()
                if len(ocr_text) > len(content.strip()) and _text_quality_ok(ocr_text):
                    logger.info(
                        "_parse_pdf_with_tables: page %d had no usable text layer — "
                        "used OCR instead (%d chars).",
                        i + 1,
                        len(ocr_text),
                    )
                    content = ocr_text
                elif ocr_text and not _text_quality_ok(ocr_text):
                    logger.warning(
                        "_parse_pdf_with_tables: page %d OCR output looks garbled "
                        "(high noise ratio) — keeping the sparse original instead "
                        "of trusting likely-wrong OCR text.",
                        i + 1,
                    )
            pages.append(content)
    return "\n\n".join(p for p in pages if p.strip())


async def parse_to_markdown(file_path: str) -> str:
    """Converts a document file to a clean Markdown string.

    Whether a file is a PDF is decided by sniffing its actual bytes
    (`_looks_like_pdf`), not by trusting the upload's filename extension. A PDF
    goes through the table-aware pdfplumber path first — which itself OCRs any
    individual page with no usable text layer, so scanned pages mixed into an
    otherwise native-text PDF are still covered — falling back to MarkItDown
    only if pdfplumber can't open the file at all, or extraction (OCR included)
    still comes up empty. Every other format (DOCX, etc.) uses MarkItDown
    directly, as before, which does its own content-based format sniffing.
    Raises DocumentParseError for corrupted, unsupported, or image-only files
    that yield no extractable text via any available path.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    # Content, not the filename extension, decides whether the PDF tier
    # applies — see `_looks_like_pdf`. A mismatched/missing extension still
    # gets routed correctly, and by what it actually is.
    if _looks_like_pdf(path):
        try:
            text = await asyncio.to_thread(_parse_pdf_with_tables, path)
        except Exception as exc:
            logger.warning(
                "parse_to_markdown: table-aware PDF parse failed for '%s' — %s; "
                "falling back to MarkItDown.",
                path.name,
                exc,
            )
            text = None
        if text and text.strip():
            logger.info(
                "parse_to_markdown: extracted %d chars (table-aware) from '%s'",
                len(text),
                path.name,
            )
            _warn_if_low_quality(text, path.name)
            return text
        logger.warning(
            "parse_to_markdown: table-aware parse (including per-page OCR) produced "
            "no text for '%s' — falling back to MarkItDown.",
            path.name,
        )

    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        # MarkItDown.convert is synchronous — run it off the event loop thread
        result = await asyncio.to_thread(md.convert, str(path))
        text: str = result.text_content or ""
    except FileNotFoundError:
        raise
    except Exception as exc:
        logger.error("parse_to_markdown: MarkItDown conversion failed for '%s' — %s", path.name, exc)
        raise DocumentParseError(f"Conversion failed for '{path.name}': {exc}") from exc

    if not text.strip():
        # Image-heavy or empty documents produce no text content
        logger.warning(
            "parse_to_markdown: no extractable text in '%s' (image-heavy or unsupported content)",
            path.name,
        )
        raise DocumentParseError(
            f"No extractable text in '{path.name}' — document may be image-only or corrupted."
        )

    logger.info(
        "parse_to_markdown: successfully extracted %d chars from '%s'",
        len(text),
        path.name,
    )
    _warn_if_low_quality(text, path.name)
    return text
