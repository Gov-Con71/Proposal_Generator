"""Unit tests for the LLM provider abstraction (app.services.llm).

These verify the decoupling itself — provider selection, the interface contract,
and caching — without touching any vendor SDK or network (constructing the
adapter is SDK-free; only an actual call would import google-genai).
"""

import pytest

from app.core.config import settings
from app.services.llm import LLMProvider, get_llm, reset_llm


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    reset_llm()
    yield
    reset_llm()


def test_default_provider_is_gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    from app.services.llm.gemini import GeminiProvider

    provider = get_llm()
    assert isinstance(provider, GeminiProvider)
    assert isinstance(provider, LLMProvider)
    # Must match the DB schema (historical_chunks.embedding is vector(768)).
    assert provider.embedding_dim == 768


def test_provider_selection_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "GEMINI")
    from app.services.llm.gemini import GeminiProvider

    assert isinstance(get_llm(), GeminiProvider)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "bogus")
    reset_llm()
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_llm()


def test_provider_is_cached_until_reset(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    first = get_llm()
    assert get_llm() is first  # cached
    reset_llm()
    assert get_llm() is not first  # rebuilt after reset


def test_a_custom_provider_satisfies_the_interface():
    """Demonstrates a second platform can be dropped in behind the same port."""

    class FakeProvider(LLMProvider):
        def generate_text(self, prompt, *, system=None):
            return "text"

        def generate_structured(self, prompt, schema, *, system=None):
            return schema()

        def embed(self, texts):
            return [[0.0] * self.embedding_dim for _ in texts]

        @property
        def embedding_dim(self):
            return 768

    fake = FakeProvider()
    assert fake.generate_text("x") == "text"
    assert fake.embed(["a", "b"]) == [[0.0] * 768, [0.0] * 768]
