"""Unit tests for the generic OpenAI-compatible adapter and the Featherless
preset built on top of it — no network, no live host.
"""

import pytest

from app.services.llm.featherless import FeatherlessProvider
from app.services.llm.openai_compatible import OpenAICompatibleProvider


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    def get(self, path):
        return self._response


def _provider(**kwargs) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="https://example.com/v1",
        model="m",
        embed_model="e",
        embed_dim=768,
        api_key="k",
        **kwargs,
    )


def test_available_models_parses_ids_from_the_listing_endpoint():
    provider = _provider()
    provider._client_obj = _FakeClient(
        _FakeResponse(200, {"data": [{"id": "model-a"}, {"id": "model-b"}]})
    )
    assert provider.available_models() == ["model-a", "model-b"]


def test_available_models_returns_none_when_the_host_cannot_be_reached():
    """Same contract as GeminiProvider: "could not ask" must not read as
    "this model does not exist", or a network blip would refuse to boot."""
    provider = _provider()

    def _boom():
        raise RuntimeError("connection refused")

    provider._client = _boom
    assert provider.available_models() is None


def test_available_models_returns_none_when_the_host_has_no_listing_endpoint():
    provider = _provider()
    provider._client_obj = _FakeClient(_FakeResponse(404, {}))
    assert provider.available_models() is None


def test_missing_api_key_names_the_env_var_it_checked():
    provider = OpenAICompatibleProvider(
        base_url="https://example.com/v1",
        model="m",
        embed_model="e",
        embed_dim=768,
        api_key_env="SOME_VENDOR_API_KEY",
    )
    with pytest.raises(RuntimeError, match="SOME_VENDOR_API_KEY"):
        provider._client()


def test_featherless_is_a_preset_of_the_generic_adapter(monkeypatch):
    """Featherless's own base URL and env var must still be exactly what they
    were before this became a generic-adapter preset."""
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    monkeypatch.setenv("FEATHERLESS_API_KEY", "fk-from-env")

    provider = FeatherlessProvider(model="m", embed_model="e", embed_dim=768)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._base_url == "https://api.featherless.ai/v1"
    assert provider._api_key == "fk-from-env"


def test_featherless_prefers_an_injected_key_over_the_environment(monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "fk-from-env")

    provider = FeatherlessProvider(
        model="m", embed_model="e", embed_dim=768, api_key="injected-key"
    )

    assert provider._api_key == "injected-key"
