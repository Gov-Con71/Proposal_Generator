"""Provider-agnostic LLM interface (the port).

Feature code depends only on this abstraction — never on a vendor SDK — so the
platform can migrate between AI providers by adding an adapter and flipping the
`LLM_PROVIDER` setting. See `app/services/llm/__init__.py` for the factory and
`gemini.py` for the reference adapter.

The three shapes below are every way the app talks to an LLM today:
  * generate_text       — free-form prose (the draft writer)
  * generate_structured — JSON constrained to a Pydantic schema (extractor,
                          outline planner, compliance critic)
  * embed               — text → fixed-dimension vectors (the RAG store)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Interface every AI adapter implements. Keep it vendor-neutral."""

    @abstractmethod
    def generate_text(self, prompt: str, *, system: Optional[str] = None) -> str:
        """Free-form text generation. Returns the model's text (never None)."""

    @abstractmethod
    def generate_structured(
        self, prompt: str, schema: Type[T], *, system: Optional[str] = None
    ) -> T:
        """Generation constrained to `schema`.

        Returns a validated instance of `schema`, or raises if the provider
        cannot produce a parseable result.
        """

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, one `embedding_dim`-length vector per input."""

    @property
    @abstractmethod
    def embedding_dim(self) -> int:
        """Vector dimension of `embed` output; must match the DB schema (vector(N))."""
