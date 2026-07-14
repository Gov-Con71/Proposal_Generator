"""Google Gemini adapter (google-genai) — the default LLM provider.

The single place in the codebase that touches the vendor SDK. It also owns
telemetry, so token/latency accounting is consistent across every call and call
sites stay provider-agnostic. The SDK is imported lazily (only when a call is
actually made) to keep the API import chain and unit tests SDK-free.
"""

import logging
import os
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from app.core import telemetry
from app.services.llm.base import LLMProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GeminiProvider(LLMProvider):
    def __init__(self, *, model: str, embed_model: str, embed_dim: int) -> None:
        self._model = model
        self._embed_model = embed_model
        self._embed_dim = embed_dim
        self._client_obj = None

    def _client(self):
        # Built on first use, then reused; keeps `google.genai` out of import time.
        if self._client_obj is None:
            from google import genai

            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not set; cannot call the LLM.")
            self._client_obj = genai.Client(api_key=api_key)
        return self._client_obj

    def generate_text(self, prompt: str, *, system: Optional[str] = None) -> str:
        from google.genai import types

        start = telemetry.now()
        try:
            response = self._client().models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system),
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
            response = self._client().models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
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
        start = telemetry.now()
        try:
            result = self._client().models.embed_content(
                model=self._embed_model, contents=texts
            )
        except Exception:
            telemetry.record_error(self._embed_model, start)
            raise
        telemetry.record_response(self._embed_model, result, start)
        logger.info("embed: %d text(s) via %s", len(texts), self._embed_model)
        return [list(e.values) for e in result.embeddings]

    @property
    def embedding_dim(self) -> int:
        return self._embed_dim
