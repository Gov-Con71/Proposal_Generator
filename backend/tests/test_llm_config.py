"""Regression guards for the LLM configuration that silently kills ingestion.

Both faults below present identically to a user: the document stops at 'failed'
and the process page shows an error that says nothing about the cause.

  1. Retired model names. `gemini-2.0-flash` and `text-embedding-004` are gone
     from the API (both 404). config.py's defaults were corrected, but a .env
     file OUTRANKS those defaults — and `backend/.env` is gitignored, so it
     never receives a fix made to committed code. `backend/.env.example` still
     shipped the retired pair, so every fresh copy reinstated the bug.

  2. An API key pydantic could see but the adapters could not. The adapters read
     `os.getenv("GEMINI_API_KEY")`, which only sees *real* environment
     variables; pydantic's `env_file` populates Settings without exporting to
     os.environ. Under compose the key is a real env var, so this worked there
     and failed only when running the backend on the host (DEPLOYMENT.md §4).

No database or network needed — these assert the wiring, not the provider.
`startup_checks.check_models()` validates names against the live provider at
boot; these run in CI, where there is no provider to ask.
"""

import os
from unittest import mock

import pytest

from app.core.config import Settings, settings
from app.services.llm import get_llm, reset_llm

# Names the Gemini API no longer serves. Pinning any of these breaks extraction,
# embedding, and drafting at once.
RETIRED_MODELS = {
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "text-embedding-004",
    "embedding-001",
}


def test_configured_chat_model_is_not_retired():
    assert settings.llm_model not in RETIRED_MODELS, (
        f"LLM_MODEL is pinned to the retired model '{settings.llm_model}'. "
        "The API 404s it and every ingestion fails at the extract step. "
        "Check backend/.env — it overrides the default in config.py."
    )


def test_configured_embedding_model_is_not_retired():
    assert settings.embedding_model not in RETIRED_MODELS, (
        f"EMBEDDING_MODEL is pinned to the retired model '{settings.embedding_model}'. "
        "The API 404s it, so the RAG store can never be written. "
        "Check backend/.env — it overrides the default in config.py."
    )


def test_env_example_does_not_ship_retired_models():
    """The template is what every new environment is copied from, so a stale
    pin here silently recreates the outage on each fresh setup."""
    import re
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    text = example.read_text(encoding="utf-8")

    for var in ("LLM_MODEL", "EMBEDDING_MODEL"):
        match = re.search(rf"^{var}=(.*)$", text, re.M)
        assert match, f"{var} is missing from backend/.env.example"
        value = match.group(1).split("#")[0].strip()
        assert value not in RETIRED_MODELS, (
            f"backend/.env.example pins the retired model '{value}' for {var}. "
            "Every fresh copy of this template recreates the outage."
        )


def test_api_keys_are_declared_as_settings():
    """The keys must be real Settings fields, not just environment reads.

    Without a declared field the value is unreachable whenever it lives only in
    a .env file, which is precisely the documented host-run setup.
    """
    assert hasattr(settings, "gemini_api_key")
    assert hasattr(settings, "featherless_api_key")


def test_api_key_resolves_from_env_file_not_only_os_environ(tmp_path, monkeypatch):
    """A key present *only* in a .env file must still reach Settings.

    This is the exact condition that produced "GEMINI_API_KEY is not set" while
    the key sat in backend/.env the whole time.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=key-from-dotenv-only\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    loaded = Settings(_env_file=str(env_file))

    assert loaded.gemini_api_key == "key-from-dotenv-only"


def test_factory_injects_the_key_into_the_gemini_adapter():
    """The adapter must receive the settings-resolved key.

    It keeps an os.getenv fallback, so a test that only checked "a call
    succeeds" would pass even with the injection removed. Assert the key
    actually travelled by clearing the environment first.
    """
    reset_llm()
    try:
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            settings, "gemini_api_key", "injected-test-key"
        ), mock.patch.object(settings, "llm_provider", "gemini"):
            provider = get_llm()
            assert provider._api_key == "injected-test-key"
    finally:
        reset_llm()


def test_unknown_provider_is_rejected_loudly():
    reset_llm()
    try:
        with mock.patch.object(settings, "llm_provider", "not-a-provider"):
            with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
                get_llm()
    finally:
        reset_llm()
