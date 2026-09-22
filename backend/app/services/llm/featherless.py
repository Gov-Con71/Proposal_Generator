"""Featherless AI adapter — a preset of the generic OpenAI-compatible adapter.

Featherless serves open-weight models over an OpenAI-compatible REST API
(https://api.featherless.ai/v1) on a flat subscription — no per-day request cap.
Select it with `LLM_PROVIDER=featherless` and set `FEATHERLESS_API_KEY`,
`LLM_MODEL` (a chat model id, e.g. Qwen/Qwen2.5-72B-Instruct), and
`EMBEDDING_MODEL` (e.g. Qwen/Qwen3-Embedding-8B).

This is nothing but `OpenAICompatibleProvider` with Featherless's base URL and
API key env var pre-filled — see `app.services.llm.openai_compatible` for the
actual client (retry/backoff, structured-output-via-prompt-injection, embeddings).
Kept as its own class (not just a constructor call) so existing imports
(`from app.services.llm.featherless import FeatherlessProvider`) and `.env`
files that predate the generic `openai_compatible` provider keep working
unchanged. Pointing at a *different* OpenAI-compatible host (OpenRouter,
Together, a self-hosted vLLM/Ollama instance, ...) needs no new adapter at
all — set `LLM_PROVIDER=openai_compatible` with `LLM_BASE_URL`/`LLM_API_KEY`
instead of adding a preset here.
"""

from typing import Optional

from app.services.llm.openai_compatible import OpenAICompatibleProvider

_BASE_URL = "https://api.featherless.ai/v1"


class FeatherlessProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        model: str,
        embed_model: str,
        embed_dim: int,
        api_key: Optional[str] = None,
        request_timeout_ms: Optional[int] = None,
        max_retries: int = 5,
        retry_base_seconds: float = 2.0,
    ) -> None:
        super().__init__(
            base_url=_BASE_URL,
            model=model,
            embed_model=embed_model,
            embed_dim=embed_dim,
            api_key=api_key,
            api_key_env="FEATHERLESS_API_KEY",
            request_timeout_ms=request_timeout_ms,
            max_retries=max_retries,
            retry_base_seconds=retry_base_seconds,
        )
