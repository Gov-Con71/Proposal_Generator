"""Text embeddings via the google-genai SDK (Story 3.1).

Uses text-embedding-004 (768-dim) — the same SDK family as the compliance
extractor and draft writer. Import-safe: the SDK is only imported on first use.
"""

import logging
import os

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-004"
EMBED_DIM = 768


def _client():
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set; cannot embed text.")
    return genai.Client(api_key=api_key)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embeds a batch of texts, returning one 768-dim vector per input."""
    if not texts:
        return []
    from app.core import telemetry

    start = telemetry.now()
    try:
        result = _client().models.embed_content(model=_EMBED_MODEL, contents=texts)
    except Exception:
        telemetry.record_error(_EMBED_MODEL, start)
        raise
    telemetry.record_response(_EMBED_MODEL, result, start)
    logger.info("embed_texts: embedded %d chunk(s) with %s", len(texts), _EMBED_MODEL)
    return [list(e.values) for e in result.embeddings]


def embed_query(text: str) -> list[float]:
    """Embeds a single query string."""
    return embed_texts([text])[0]
