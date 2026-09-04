"""LLM provider factory — the one entry point feature code uses.

    from app.services.llm import get_llm
    text = get_llm().generate_text(prompt, system=...)

Select the provider with the `LLM_PROVIDER` setting (default: "gemini"). To add
a provider that needs genuinely new code (a native vendor SDK, bespoke auth):
implement `LLMProvider` in a new adapter module (mirroring `gemini.py`) and
register its factory in `_PROVIDER_FACTORIES` below — no call site changes. To
point at a *different* OpenAI-compatible host (OpenRouter, Together, a
self-hosted vLLM/Ollama instance, ...) no new code is needed at all: set
`LLM_PROVIDER=openai_compatible` with `LLM_BASE_URL`/`LLM_API_KEY` — see
`openai_compatible.py`.

Importing this package is SDK-free: only `base` is imported eagerly; the chosen
adapter (and its vendor SDK) loads lazily inside `_build_provider()`.
"""

from functools import lru_cache
from typing import Callable, Literal

from app.services.llm.base import LLMProvider

__all__ = ["LLMProvider", "get_llm", "reset_llm"]

# The embedding dimension is pinned to the DB schema (historical_chunks.embedding
# is vector(768)); a provider must produce vectors of this width.
_EMBEDDING_DIM = 768

Tier = Literal["default", "light"]


def _build_gemini(model: str) -> LLMProvider:
    from app.core.config import settings
    from app.services.llm.gemini import GeminiProvider

    return GeminiProvider(
        model=model,
        embed_model=settings.embedding_model,
        embed_dim=_EMBEDDING_DIM,
        # Injected from settings so the key resolves from .env too, not just
        # from real environment variables.
        api_key=settings.gemini_api_key,
        request_timeout_ms=settings.llm_request_timeout_seconds * 1000,
        max_retries=settings.llm_max_retries,
        retry_base_seconds=settings.llm_retry_base_seconds,
    )


def _build_featherless(model: str) -> LLMProvider:
    from app.core.config import settings
    from app.services.llm.featherless import FeatherlessProvider

    return FeatherlessProvider(
        model=model,
        embed_model=settings.embedding_model,
        embed_dim=_EMBEDDING_DIM,
        api_key=settings.featherless_api_key,
        request_timeout_ms=settings.llm_request_timeout_seconds * 1000,
        max_retries=settings.llm_max_retries,
        retry_base_seconds=settings.llm_retry_base_seconds,
    )


def _build_openai_compatible(model: str) -> LLMProvider:
    from app.core.config import settings
    from app.services.llm.openai_compatible import OpenAICompatibleProvider

    if not settings.llm_base_url:
        raise ValueError(
            "LLM_PROVIDER=openai_compatible requires LLM_BASE_URL to be set "
            "(e.g. https://openrouter.ai/api/v1, or a self-hosted vLLM/Ollama "
            "endpoint's /v1)."
        )
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        model=model,
        embed_model=settings.embedding_model,
        embed_dim=_EMBEDDING_DIM,
        api_key=settings.llm_api_key,
        request_timeout_ms=settings.llm_request_timeout_seconds * 1000,
        max_retries=settings.llm_max_retries,
        retry_base_seconds=settings.llm_retry_base_seconds,
    )


# Registry, not an if/elif chain: adding a provider that needs bespoke code is
# a one-line addition here, not an edit to a growing branch. Every factory
# still imports its adapter (and vendor SDK) lazily, so this module stays
# SDK-free until a provider is actually selected.
_PROVIDER_FACTORIES: dict[str, Callable[[str], LLMProvider]] = {
    "gemini": _build_gemini,
    "featherless": _build_featherless,
    "openai_compatible": _build_openai_compatible,
}


def _build_provider(tier: Tier) -> LLMProvider:
    from app.core.config import settings

    # "light" falls back to the main model/provider when unset, so tiering is
    # opt-in: a deployment that never sets LLM_MODEL_LIGHT/LLM_PROVIDER_LIGHT
    # behaves exactly as it did before either existed.
    model = (
        settings.llm_model_light
        if tier == "light" and settings.llm_model_light
        else settings.llm_model
    )
    provider_name = (
        settings.llm_provider_light
        if tier == "light" and settings.llm_provider_light
        else settings.llm_provider
    ) or "gemini"

    name = provider_name.lower()
    factory = _PROVIDER_FACTORIES.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider_name}'. Implement an LLMProvider "
            "adapter and register it in app/services/llm/__init__.py, or use "
            "'openai_compatible' with LLM_BASE_URL for any OpenAI-compatible host."
        )
    return factory(model)


@lru_cache(maxsize=2)
def get_llm(tier: Tier = "default") -> LLMProvider:
    """Returns the configured provider for `tier` (built once per tier, then reused).

    `tier="light"` is for mechanical calls that don't need the main model's
    quality (HyDE query generation, compliance-matrix structuring) — see
    LLM_MODEL_LIGHT in app.core.config. It may also run on an entirely
    different *provider* via LLM_PROVIDER_LIGHT (e.g. a free/local backend for
    light work while the default tier stays on a paid vendor) — both default to
    the main tier's setting when unset, so tiering remains opt-in either way.
    Anything user-facing (the actual section draft) should stay on the default
    tier.
    """
    return _build_provider(tier)


def reset_llm() -> None:
    """Drop the cached providers — for tests or a config reload."""
    get_llm.cache_clear()
