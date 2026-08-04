"""Google Gemini adapter (google-genai) — the default LLM provider.

The single place in the codebase that touches the vendor SDK. It also owns
telemetry, so token/latency accounting is consistent across every call and call
sites stay provider-agnostic. The SDK is imported lazily (only when a call is
actually made) to keep the API import chain and unit tests SDK-free.
"""

import logging
import math
import os
import re
import time
from typing import Callable, Optional, Type, TypeVar

from pydantic import BaseModel

from app.core import telemetry
from app.services.llm.base import LLMProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# HTTP statuses worth retrying: 429 (rate limit) and 503 (transient unavailable).
_RETRYABLE_CODES = {429, 503}
# Never sleep longer than this between attempts, even if the API asks for more.
_RETRY_CAP_SECONDS = 60.0
# Pulls a delay hint out of the error, e.g. "'retryDelay': '34s'" or
# "Please retry in 34.28s" — both shapes appear in Gemini 429 payloads.
_RETRY_DELAY_RE = re.compile(
    r"(?:retrydelay['\":\s]*'?|retry in )(\d+(?:\.\d+)?)s", re.IGNORECASE
)


def _is_retryable(exc: Exception) -> bool:
    if getattr(exc, "code", None) in _RETRYABLE_CODES:
        return True
    text = str(exc)
    return "RESOURCE_EXHAUSTED" in text or "UNAVAILABLE" in text


def _unit(vector: list[float]) -> list[float]:
    """Scales a vector to unit length.

    Gemini only pre-normalises embeddings at the full 3072 dimensions; truncated
    outputs come back unnormalised (a 768-dim vector measures ~0.59). Retrieval
    uses cosine (`<=>`), which is magnitude-invariant and so unaffected either
    way — but storing unit vectors matches the vendor's guidance and keeps a
    future switch to inner-product (`<#>`) from silently skewing scores.
    """
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude == 0:
        return vector
    return [component / magnitude for component in vector]


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        embed_model: str,
        embed_dim: int,
        request_timeout_ms: int | None = None,
        max_retries: int = 5,
        retry_base_seconds: float = 2.0,
    ) -> None:
        self._model = model
        self._embed_model = embed_model
        self._embed_dim = embed_dim
        self._request_timeout_ms = request_timeout_ms
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._client_obj = None

    def _retry_delay(self, exc: Exception, attempt: int) -> float:
        """Seconds to wait before the next attempt: the API's own hint if present
        (plus a small cushion for the quota-window edge), else exponential backoff."""
        match = _RETRY_DELAY_RE.search(str(exc))
        if match:
            return min(float(match.group(1)) + 1.0, _RETRY_CAP_SECONDS)
        return min(self._retry_base_seconds * (2 ** attempt), _RETRY_CAP_SECONDS)

    def _with_retry(self, call: Callable[[], T], *, what: str) -> T:
        """Runs `call`, retrying transient 429/503 responses so a brief quota
        overrun doesn't fail the request (and leave e.g. an empty draft section)."""
        attempt = 0
        while True:
            try:
                return call()
            except Exception as exc:
                if attempt >= self._max_retries or not _is_retryable(exc):
                    raise
                delay = self._retry_delay(exc, attempt)
                attempt += 1
                logger.warning(
                    "Gemini %s throttled/unavailable (%s); retry %d/%d in %.1fs",
                    what,
                    getattr(exc, "code", "?"),
                    attempt,
                    self._max_retries,
                    delay,
                )
                time.sleep(delay)

    def _client(self):
        # Built on first use, then reused; keeps `google.genai` out of import time.
        if self._client_obj is None:
            from google import genai
            from google.genai import types

            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not set; cannot call the LLM.")
            # Client-level timeout applies to every call (generation + embeddings),
            # so no single request can hang a worker thread indefinitely.
            http_options = (
                types.HttpOptions(timeout=self._request_timeout_ms)
                if self._request_timeout_ms
                else None
            )
            self._client_obj = genai.Client(api_key=api_key, http_options=http_options)
        return self._client_obj

    def generate_text(self, prompt: str, *, system: Optional[str] = None) -> str:
        from google.genai import types

        start = telemetry.now()
        try:
            response = self._with_retry(
                lambda: self._client().models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(system_instruction=system),
                ),
                what="generate_text",
            )
        except Exception:
            telemetry.record_error(self._model, start)
            raise
        telemetry.record_response(self._model, response, start)
        return response.text or ""

    def generate_structured(
        self, prompt: str, schema: Type[T], *, system: Optional[str] = None
    ) -> T:
        from google.genai import types

        start = telemetry.now()
        try:
            response = self._with_retry(
                lambda: self._client().models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=schema,
                    ),
                ),
                what="generate_structured",
            )
        except Exception:
            telemetry.record_error(self._model, start)
            raise
        telemetry.record_response(self._model, response, start)
        # google-genai parses the JSON straight into the Pydantic schema.
        parsed = response.parsed
        if parsed is None:
            raise RuntimeError(
                f"{self._model} returned no parseable {schema.__name__}."
            )
        return parsed

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        from google.genai import types

        start = telemetry.now()
        try:
            # output_dimensionality must be sent explicitly: gemini-embedding-001
            # defaults to 3072, which would not fit historical_chunks.embedding
            # (vector(768)) and fails the insert.
            result = self._with_retry(
                lambda: self._client().models.embed_content(
                    model=self._embed_model,
                    contents=texts,
                    config=types.EmbedContentConfig(output_dimensionality=self._embed_dim),
                ),
                what="embed",
            )
        except Exception:
            telemetry.record_error(self._embed_model, start)
            raise
        telemetry.record_response(self._embed_model, result, start)
        logger.info("embed: %d text(s) via %s", len(texts), self._embed_model)
        return [_unit(list(e.values)) for e in result.embeddings]

    @property
    def embedding_dim(self) -> int:
        return self._embed_dim

    def available_models(self) -> Optional[list[str]]:
        """Model names the configured key can actually call.

        Returns None rather than raising when the API cannot be reached: the
        startup check must distinguish "this model does not exist" (a
        configuration error worth failing on) from "we could not ask right now"
        (a network blip that must not stop the process from booting).

        Names come back namespaced (`models/gemini-2.5-flash`); the bare form is
        included too so a caller can match whichever the settings use.
        """
        try:
            names: list[str] = []
            for model in self._client().models.list():
                name = getattr(model, "name", None)
                if not name:
                    continue
                names.append(name)
                if name.startswith("models/"):
                    names.append(name.split("/", 1)[1])
            return names or None
        except Exception as exc:  # noqa: BLE001 — "could not ask" is not "invalid"
            logger.warning("Could not list Gemini models: %s", exc)
            return None
