"""Text embeddings (Story 3.1).

Thin, stable facade over the configured LLM provider (`app.services.llm`).
Retrieval, history ingestion, and tests depend on these names; the actual AI
platform is chosen behind `get_llm()`, so swapping providers touches only the
adapter — not this module.
"""

import logging

from app.services.llm import get_llm

logger = logging.getLogger(__name__)

# Kept for callers/schema reference; the active provider must match this width
# (historical_chunks.embedding is vector(768)).
EMBED_DIM = 768


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embeds a batch of texts, returning one 768-dim vector per input."""
    if not texts:
        return []
    return get_llm().embed(texts)


def embed_query(text: str) -> list[float]:
    """Embeds a single query string."""
    return embed_texts([text])[0]
