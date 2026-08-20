"""LLM provider factory — the one entry point feature code uses.

    from app.services.llm import get_llm
    text = get_llm().generate_text(prompt, system=...)

Select the provider with the `LLM_PROVIDER` setting (default: "gemini"). To add
a new platform: implement `LLMProvider` in a new adapter module (mirroring
`gemini.py`) and register it in `_build_provider()` below — no call site changes.

Importing this package is SDK-free: only `base` is imported eagerly; the chosen
adapter (and its vendor SDK) loads lazily inside `_build_provider()`.
"""

from functools import lru_cache
from typing import Literal

from app.services.llm.base import LLMProvider

__all__ = ["LLMProvider", "get_llm", "reset_llm"]

# The embedding dimension is pinned to the DB schema (historical_chunks.embedding
# is vector(768)); a provider must produce vectors of this width.
_EMBEDDING_DIM = 768

Tier = Literal["default", "light"]


def _build_provider(tier: Tier) -> LLMProvider:
    from app.core.config import settings

    # "light" falls back to the main model when LLM_MODEL_LIGHT is unset, so
    # tiering is opt-in: a deployment that never sets it behaves exactly as it
    # did before this existed, including sharing the same cached instance in
    # effect (same model, same client config).
    model = (
        settings.llm_model_light
        if tier == "light" and settings.llm_model_light
        else settings.llm_model
    )

    name = (settings.llm_provider or "gemini").lower()
    if name == "gemini":
        from app.services.llm.gemini import GeminiProvider

        return GeminiProvider(
            model=model,
            embed_model=settings.embedding_model,
            embed_dim=_EMBEDDING_DIM,
            request_timeout_ms=settings.llm_request_timeout_seconds * 1000,
            max_retries=settings.llm_max_retries,
            retry_base_seconds=settings.llm_retry_base_seconds,
        )
    if name == "featherless":
        from app.services.llm.featherless import FeatherlessProvider

        return FeatherlessProvider(
            model=model,
            embed_model=settings.embedding_model,
            embed_dim=_EMBEDDING_DIM,
            request_timeout_ms=settings.llm_request_timeout_seconds * 1000,
            max_retries=settings.llm_max_retries,
            retry_base_seconds=settings.llm_retry_base_seconds,
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Implement an LLMProvider "
        "adapter and register it in app/services/llm/__init__.py."
    )


@lru_cache(maxsize=2)
def get_llm(tier: Tier = "default") -> LLMProvider:
    """Returns the configured provider for `tier` (built once per tier, then reused).

    `tier="light"` is for mechanical calls that don't need the main model's
    quality (HyDE query generation, compliance-matrix structuring) — see
    LLM_MODEL_LIGHT in app.core.config. Anything user-facing (the actual
    section draft) should stay on the default tier.
    """
    return _build_provider(tier)


def reset_llm() -> None:
    """Drop the cached providers — for tests or a config reload."""
    get_llm.cache_clear()
