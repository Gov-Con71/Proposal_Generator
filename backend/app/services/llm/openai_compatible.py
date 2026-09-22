"""Generic OpenAI-compatible adapter — any `/v1/chat/completions`-shaped host.

Most self-hosted and third-party inference APIs (Featherless, OpenRouter,
Together, a local vLLM/Ollama/LM Studio instance, ...) speak the same
OpenAI-compatible REST shape. This adapter targets that shape directly,
parameterized by `base_url` and an API key, so pointing the platform at a new
host is a config change (`LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`,
`LLM_API_KEY`, `LLM_MODEL`) — never a new adapter module.

`app.services.llm.featherless.FeatherlessProvider` is a thin preset of this
class (fixed `base_url`, reads `FEATHERLESS_API_KEY`) — Featherless's shape
*is* this generic shape, just with a hardcoded host, kept for the existing
`.env` convention.

Two differences from the Gemini adapter shape the code:

  * No native structured-output mode. `generate_structured` injects the Pydantic
    JSON Schema into the prompt, then parses + validates the reply and retries
    once — so it works with any instruct model, at the cost of the model's own
    JSON reliability (the callers' guardrails backstop malformed output).
  * Embeddings come from `/v1/embeddings` with an explicit `dimensions` so the
    vectors match `historical_chunks.embedding` (vector(768)).

Uses httpx (already a dependency) rather than the openai SDK to avoid a new
vendor dependency. The SDK is import-light, so this stays out of import time.
"""

import json
import logging
import os
import time
from types import SimpleNamespace
from typing import Callable, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core import telemetry
from app.services.llm.base import LLMProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RETRYABLE_CODES = {429, 503}
_RETRY_CAP_SECONDS = 60.0

_JSON_INSTRUCTION = (
    "Respond with a SINGLE valid JSON object and nothing else — no prose, no "
    "explanation, no markdown code fences. The JSON must conform exactly to this "
    "JSON Schema:\n{schema}"
)


def _usage_shim(data: dict):
    """Adapts OpenAI-style `usage` to the shape telemetry.record_response reads."""
    u = data.get("usage") or {}
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=u.get("prompt_tokens", 0) or 0,
            candidates_token_count=u.get("completion_tokens", 0) or 0,
        )
    )


def _extract_json(text: str) -> str:
    """Best-effort extraction of a JSON object from a model reply (strips code
    fences / surrounding prose by slicing the outermost braces)."""
    t = text.strip()
    if t.startswith("```"):
        # ```json\n{...}\n``` → keep the fenced body
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t.lstrip("`")
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
        t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        return t[start : end + 1]
    return t


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        embed_model: str,
        embed_dim: int,
        api_key: Optional[str] = None,
        # Read when `api_key` is not supplied directly — lets a subclass (e.g.
        # FeatherlessProvider) default to its own vendor-named env var while
        # the generic `openai_compatible` provider defaults to none (settings
        # always injects LLM_API_KEY explicitly, same convention as every
        # other adapter — see llm/__init__.py's _build_provider).
        api_key_env: Optional[str] = None,
        request_timeout_ms: Optional[int] = None,
        max_retries: int = 5,
        retry_base_seconds: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._embed_model = embed_model
        self._embed_dim = embed_dim
        self._api_key_env = api_key_env
        self._api_key = api_key or (os.getenv(api_key_env) if api_key_env else None)
        self._timeout = (request_timeout_ms / 1000.0) if request_timeout_ms else 120.0
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._client_obj: Optional[httpx.Client] = None

    def _missing_key_error(self) -> RuntimeError:
        hint = f" (checked {self._api_key_env})" if self._api_key_env else ""
        return RuntimeError(
            f"No API key configured for {self._base_url}{hint}; cannot call the LLM."
        )

    def _client(self) -> httpx.Client:
        # Built on first use, then reused.
        if self._client_obj is None:
            if not self._api_key:
                raise self._missing_key_error()
            self._client_obj = httpx.Client(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        return self._client_obj

    def _post(self, path: str, payload: dict, *, what: str) -> dict:
        """POSTs `payload`, retrying transient 429/503 responses (honouring
        Retry-After when present), and returns the parsed JSON body."""
        attempt = 0
        while True:
            resp = self._client().post(path, json=payload)
            if resp.status_code in _RETRYABLE_CODES and attempt < self._max_retries:
                delay = min(self._retry_base_seconds * (2 ** attempt), _RETRY_CAP_SECONDS)
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = min(float(retry_after), _RETRY_CAP_SECONDS)
                    except ValueError:
                        pass
                attempt += 1
                logger.warning(
                    "%s %s throttled/unavailable (%s); retry %d/%d in %.1fs",
                    self._base_url, what, resp.status_code, attempt, self._max_retries, delay,
                )
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()

    def _chat(self, prompt: str, *, system: Optional[str], what: str) -> tuple[str, dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        data = self._post(
            "/chat/completions", {"model": self._model, "messages": messages}, what=what
        )
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return text, data

    def generate_text(self, prompt: str, *, system: Optional[str] = None) -> str:
        start = telemetry.now()
        try:
            text, data = self._chat(prompt, system=system, what="generate_text")
        except Exception:
            telemetry.record_error(self._model, start)
            raise
        telemetry.record_response(self._model, _usage_shim(data), start)
        return text

    def generate_structured(
        self, prompt: str, schema: Type[T], *, system: Optional[str] = None
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema())
        base_system = (f"{system}\n\n" if system else "") + _JSON_INSTRUCTION.format(schema=schema_json)

        start = telemetry.now()
        last_error: Optional[Exception] = None
        try:
            for attempt in range(2):
                user = prompt if attempt == 0 else (
                    prompt + "\n\nYour previous reply was not valid JSON for the schema. "
                    "Return ONLY the JSON object, matching the schema exactly."
                )
                text, data = self._chat(user, system=base_system, what="generate_structured")
                try:
                    parsed = schema.model_validate_json(_extract_json(text))
                    telemetry.record_response(self._model, _usage_shim(data), start)
                    return parsed
                except (ValidationError, ValueError) as exc:
                    last_error = exc
                    logger.warning(
                        "%s generate_structured: invalid JSON for %s (attempt %d/2): %.120s",
                        self._base_url, schema.__name__, attempt + 1, str(exc),
                    )
        except Exception:
            telemetry.record_error(self._model, start)
            raise
        telemetry.record_error(self._model, start)
        raise RuntimeError(
            f"{self._base_url} did not return schema-valid JSON for {schema.__name__}: {last_error}"
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        start = telemetry.now()
        # `dimensions` pins the output width to the DB schema (vector(768)); the
        # chosen embedding model must support variable dimensions (e.g. Qwen3).
        payload = {"model": self._embed_model, "input": texts, "dimensions": self._embed_dim}
        try:
            data = self._post("/embeddings", payload, what="embed")
        except Exception:
            telemetry.record_error(self._embed_model, start)
            raise
        telemetry.record_response(self._embed_model, _usage_shim(data), start)
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        logger.info("embed: %d text(s) via %s", len(texts), self._embed_model)
        return [item["embedding"] for item in items]

    @property
    def embedding_dim(self) -> int:
        return self._embed_dim

    def available_models(self) -> Optional[list[str]]:
        """Model ids this host actually serves, or None if it cannot say.

        `GET /models` is the standard OpenAI-compatible listing endpoint. Not
        every OpenAI-compatible host implements it (some self-hosted servers
        skip it), so any failure here means "unknown", same as Gemini's
        contract (`llm/gemini.py:available_models`) — a startup check must
        never read "could not ask" as "this model does not exist".
        """
        try:
            data = self._post_get_models()
            ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
            return ids or None
        except Exception as exc:  # noqa: BLE001 — "could not ask" is not "invalid"
            logger.warning("Could not list models from %s: %s", self._base_url, exc)
            return None

    def _post_get_models(self) -> dict:
        # Not retried like _post: this only runs once, at startup, off the
        # request path — a transient failure here should just report "unknown"
        # (see available_models), not spend the same retry budget as a real call.
        resp = self._client().get("/models")
        resp.raise_for_status()
        return resp.json()
