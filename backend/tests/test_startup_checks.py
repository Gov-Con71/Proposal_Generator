"""Boot-time check guards (GAP_ANALYSIS §1.1 and §1.3).

Both dependencies covered here fail *quietly* by design, which is exactly why
they need a test: a regression would not announce itself either.
"""

import logging

import pytest

from app.core import startup_checks
from app.core.config import settings


def test_unreachable_cache_is_reported_not_swallowed(monkeypatch, caplog):
    """A cache misconfiguration once produced no error anywhere at all.

    Fail-open is the right behaviour and is not being changed — but "running
    uncached" must be a thing an operator can see in the logs, not something
    inferred from a workspace that looks stale.
    """
    def _boom():
        raise ConnectionError("nope")

    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr(startup_checks, "_redis_target", lambda: "redis://cache")
    monkeypatch.setattr("app.core.cache._redis", _boom)

    with caplog.at_level(logging.WARNING):
        assert startup_checks.check_cache() is False
    assert "UNREACHABLE" in caplog.text


def test_a_reachable_cache_is_reported_too(monkeypatch, caplog):
    class _Ok:
        def ping(self):
            return True

    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr("app.core.cache._redis", lambda: _Ok())

    with caplog.at_level(logging.INFO):
        assert startup_checks.check_cache() is True
    assert "cache OK" in caplog.text


class _Provider:
    def __init__(self, models):
        self._models = models

    def available_models(self):
        return self._models


def test_a_retired_model_name_is_caught(monkeypatch):
    """The §1.1 incident: a retired model surfaced as a 429 from a Celery task,
    on a key with plenty of quota. Asking the provider at boot names the setting."""
    monkeypatch.setattr(settings, "llm_model", "gemini-1.0-retired")
    monkeypatch.setattr(settings, "embedding_model", "gemini-embedding-001")
    monkeypatch.setattr(
        "app.services.llm.get_llm",
        lambda: _Provider(["gemini-2.5-flash", "gemini-embedding-001"]),
    )

    problems = startup_checks.check_models()
    assert len(problems) == 1
    assert "LLM_MODEL" in problems[0] and "gemini-1.0-retired" in problems[0]


def test_valid_models_produce_no_problems(monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "embedding_model", "gemini-embedding-001")
    monkeypatch.setattr(
        "app.services.llm.get_llm",
        lambda: _Provider(["gemini-2.5-flash", "gemini-embedding-001"]),
    )
    assert startup_checks.check_models() == []


def test_an_unreachable_provider_is_not_treated_as_invalid(monkeypatch):
    """"We could not ask" must never read as "this model does not exist" — a
    network blip at boot must not refuse to start the process."""
    monkeypatch.setattr("app.services.llm.get_llm", lambda: _Provider(None))
    assert startup_checks.check_models() == []

    def _raise():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.services.llm.get_llm", _raise)
    assert startup_checks.check_models() == []


def test_strict_mode_refuses_to_start(monkeypatch):
    """In production a container that boots and cannot generate is worse than
    one that refuses to: the first fails for a user, the second fails the deploy."""
    monkeypatch.setattr(startup_checks, "check_cache", lambda: True)
    monkeypatch.setattr(startup_checks, "check_models", lambda: ["LLM_MODEL=x is bad"])
    monkeypatch.setattr(
        type(settings), "startup_checks_strict", property(lambda self: True)
    )
    with pytest.raises(startup_checks.StartupCheckError):
        startup_checks.run_startup_checks()


def test_non_strict_mode_logs_and_continues(monkeypatch, caplog):
    """A developer with no API key still gets a working API."""
    monkeypatch.setattr(startup_checks, "check_cache", lambda: True)
    monkeypatch.setattr(startup_checks, "check_models", lambda: ["LLM_MODEL=x is bad"])
    monkeypatch.setattr(
        type(settings), "startup_checks_strict", property(lambda self: False)
    )
    with caplog.at_level(logging.ERROR):
        startup_checks.run_startup_checks()
    assert "LLM_MODEL=x is bad" in caplog.text


def test_strictness_defaults_to_on_in_production(monkeypatch):
    monkeypatch.setattr(settings, "startup_checks_strict_setting", None)
    monkeypatch.setattr(settings, "environment", "production")
    assert settings.startup_checks_strict is True

    monkeypatch.setattr(settings, "environment", "development")
    assert settings.startup_checks_strict is False

    # An explicit setting always wins over the environment default.
    monkeypatch.setattr(settings, "startup_checks_strict_setting", True)
    assert settings.startup_checks_strict is True
