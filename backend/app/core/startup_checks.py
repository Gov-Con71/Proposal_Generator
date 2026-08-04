"""Boot-time checks that make a silently degraded process say so.

Two incidents motivate this file, and they share a shape: a dependency was
misconfigured, the process started perfectly, and the symptom appeared much
later somewhere that did not point back at the cause.

* **The cache is fail-open by design** (`core/cache.py`). A total
  misconfiguration produced no error at all — the app just stopped caching, and
  the only visible effect was a stale-looking workspace (GAP_ANALYSIS §1.3). A
  cache that is meant to degrade must at least announce that it is degraded.
* **A retired model name took the whole product down and presented as a quota
  problem** (§1.1). The first symptom surfaced minutes later inside a Celery
  task, as a 429-shaped error, on a key that had plenty of quota.

So: check the things that fail quietly, at the one moment someone is watching.

**Strictness.** In production a bad model name should stop the deploy, because
a process that boots and cannot generate is worse than one that refuses to
start — the first fails at 3am for a user, the second fails in the pipeline.
Everywhere else the checks only log, so a developer without an API key can
still run the API. `STARTUP_CHECKS_STRICT` overrides either way.

Nothing here is on a request path; it runs once, at startup.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class StartupCheckError(RuntimeError):
    """A check failed and strict mode is on."""


def check_cache() -> bool:
    """Pings the cache. Returns True if reachable.

    Logged either way, at a level that matches the consequence: WARNING when
    unreachable, because the app is now running uncached and that is a real
    (if survivable) state someone should know about.
    """
    if not settings.cache_enabled:
        logger.info("startup: cache DISABLED by configuration (CACHE_ENABLED=false)")
        return False
    try:
        from app.core.cache import _redis

        _redis().ping()
        logger.info("startup: cache OK (%s)", _redis_target())
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "startup: cache UNREACHABLE (%s): %s — the app will run uncached. "
            "Reads stay correct; they just re-query every time, and rate "
            "limiting fails open. This is the state that produced no error at "
            "all last time (GAP_ANALYSIS §1.3).",
            _redis_target(),
            exc,
        )
        return False


def _redis_target() -> str:
    """The cache URL with any password removed, safe to log."""
    url = settings.cache_url
    if "@" in url:
        scheme, _, rest = url.partition("://")
        return f"{scheme}://***@{rest.rpartition('@')[2]}"
    return url


def check_models() -> list[str]:
    """Validates the configured model names against the provider.

    Returns a list of problems (empty when fine). A provider that cannot
    enumerate its models, or cannot be reached, yields no problems — "unknown"
    must not read as "invalid", or a network blip would refuse to boot.
    """
    problems: list[str] = []
    try:
        from app.services.llm import get_llm

        available = get_llm().available_models()
    except Exception as exc:  # noqa: BLE001
        logger.warning("startup: could not query the LLM provider: %s", exc)
        return problems

    if available is None:
        logger.info(
            "startup: LLM provider '%s' cannot enumerate models — model names unverified",
            settings.llm_provider,
        )
        return problems

    known = set(available)
    for label, configured in (
        ("LLM_MODEL", settings.llm_model),
        ("EMBEDDING_MODEL", settings.embedding_model),
    ):
        if configured and configured not in known:
            problems.append(
                f"{label}={configured!r} is not available to this API key. "
                f"This is the failure that reads as a quota error (§1.1)."
            )
    if not problems:
        logger.info(
            "startup: models OK (%s, %s)", settings.llm_model, settings.embedding_model
        )
    return problems


def run_startup_checks() -> None:
    """Runs every check, logging results and raising in strict mode."""
    check_cache()  # advisory only: uncached is degraded, not broken
    problems = check_models()

    for problem in problems:
        logger.error("startup: %s", problem)

    if problems and settings.startup_checks_strict:
        raise StartupCheckError(
            "; ".join(problems)
            + " — refusing to start. Set STARTUP_CHECKS_STRICT=false to boot anyway."
        )
