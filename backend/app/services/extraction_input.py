"""Input-size guard for the LLM extractors.

Both extractors send a whole document to the model in one call. A very large RFP
can exceed the model's effective attention and silently drop tail requirements —
so we cap the input at a configured budget and, when it is exceeded, truncate
with a loud warning rather than letting the loss happen invisibly.

This is a safety net, not a substitute for chunked / map-reduce extraction, which
is the real fix for genuinely large documents.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def guard_extraction_input(text: str, *, label: str) -> str:
    """Returns `text` bounded to `settings.max_extraction_chars`.

    Under the budget this is a no-op. Over it, the text is truncated and a warning
    is logged so oversized documents are visible in the logs (and their tail loss
    is deterministic rather than left to the model).
    """
    limit = settings.max_extraction_chars
    if len(text) <= limit:
        return text
    logger.warning(
        "%s: input is %d chars, over the %d budget — truncating; the document tail "
        "will not be extracted. Consider chunked extraction for documents this size.",
        label,
        len(text),
        limit,
    )
    return text[:limit]
