"""Sentry initialisation, shared by every process (Story 5.4).

This used to live inline in `app/main.py`, which meant the Celery worker never
initialised Sentry at all — `grep sentry` found exactly one file. Ingestion and
drafting, the two longest and most failure-prone paths in the system, run in
the worker and reported their exceptions to nothing. Both processes now call
`init_sentry()` with their own service name.

Still a no-op unless SENTRY_DSN is set, so nothing changes for a developer.
"""

import logging

from app.core import logging as applog
from app.core.config import settings

logger = logging.getLogger(__name__)


def _before_send(event: dict, _hint: dict) -> dict:
    """Tags each event with the bound request context.

    This is what joins the three views of one failure: the Sentry event, the
    log lines, and the `requestId` the client was handed all carry the same id.
    """
    tags = event.setdefault("tags", {})
    for key, value in applog.current_context().items():
        tags.setdefault(key, value)
    return event


def init_sentry(service: str) -> bool:
    """Initialises Sentry for this process. Returns whether it was enabled.

    Never raises: a failure to set up error reporting must not be the thing
    that stops a process from starting.
    """
    if not settings.sentry_dsn:
        logger.info("Sentry disabled (no SENTRY_DSN); errors go to logs only")
        return False

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.1,
            before_send=_before_send,
        )
        # Distinguishes an API 500 from a worker task failure in one project.
        sentry_sdk.set_tag("service", service)
        logger.info("Sentry enabled for service=%s env=%s", service, settings.environment)
        return True
    except Exception:  # noqa: BLE001 — reporting must never break startup
        logger.exception("Sentry initialisation failed; continuing without it")
        return False
