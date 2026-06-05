import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DocumentParseError(Exception):
    """Raised when MarkItDown cannot produce usable text from a document."""


async def parse_to_markdown(file_path: str) -> str:
    """Converts a document file to a clean Markdown string via MarkItDown.

    Handles PDF, DOCX, and any format MarkItDown supports.  Raises
    DocumentParseError for corrupted, unsupported, or image-only files that
    yield no extractable text.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

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
    return text
