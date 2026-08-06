"""Celery application wiring (Story 2.5).

Broker + result backend come from settings (Redis by default). Set
`CELERY_TASK_ALWAYS_EAGER=true` to run tasks inline without a broker — used by
the integration test and handy for local debugging.

This module also carries the worker's half of the observability setup, because
the worker is where the failures that matter actually happen:

  * **Logging** — Celery hijacks the root logger by default, which gave the
    worker a different format from the API for the same code. `setup_logging`
    below takes that over, so `run_ingestion` logs identically in both.
  * **Sentry** — was never initialised in this process at all.
  * **Correlation** — the request id that started the work is attached as a
    message header when a task is published and re-bound when it is executed,
    so one id spans API -> broker -> worker -> LLM adapter.
"""

import logging

from celery import Celery
from celery.signals import (
    before_task_publish,
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    worker_process_init,
)

from app.core import logging as applog
from app.core.config import settings

logger = logging.getLogger(__name__)

# The header the request id travels in. Celery propagates custom headers to the
# worker automatically, and it survives a retry — so the second attempt at an
# ingestion is still traceable to the upload that triggered it.
REQUEST_ID_HEADER = "x_request_id"

celery_app = Celery(
    "proposal_ingestion",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # We configure the root logger ourselves in `_setup_logging` below; leaving
    # the hijack on would let Celery reformat it back afterwards.
    worker_hijack_root_logger=False,
)


@setup_logging.connect
def _setup_logging(**_kwargs) -> None:
    """Gives the worker the same configuration the API uses.

    Connecting to `setup_logging` (rather than merely calling configure_logging
    at import) is what stops Celery installing its own handlers on top: the
    signal having a receiver is Celery's signal to keep its hands off.
    """
    applog.configure_logging(service="worker", force=True)


@worker_process_init.connect
def _init_worker_process(**_kwargs) -> None:
    """Per-process setup. Prefork forks *after* the parent imports, so anything
    holding a socket — Sentry's transport thread included — has to be created
    here rather than at module import."""
    from app.core.error_reporting import init_sentry

    applog.configure_logging(service="worker", force=True)
    init_sentry(service="worker")


@before_task_publish.connect
def _publish_request_id(headers=None, **_kwargs) -> None:
    """Stamps the caller's request id onto an outgoing task message.

    `before_task_publish` hands over the headers dict by reference before it is
    serialised onto the broker, which makes it the one place the id can be
    attached without changing every `.delay()` call site.
    """
    request_id = applog.current_context().get("request_id")
    if request_id and headers is not None:
        headers.setdefault(REQUEST_ID_HEADER, request_id)


# Pre-task context snapshots, keyed by task id. Restoring rather than clearing
# is what makes `CELERY_TASK_ALWAYS_EAGER=true` safe: eager tasks run inline in
# the caller's context, so clearing outright would wipe the request id of the
# HTTP request that queued the work and blank the rest of its log lines.
_task_snapshots: dict[str, dict] = {}


@task_prerun.connect
def _bind_task_context(task_id=None, task=None, **_kwargs) -> None:
    """Re-binds the originating request id, plus the Celery task id.

    A task published normally carries the request id of the API call that
    queued it. One that does not — an eager run, a task kicked off by a beat
    schedule — gets a fresh id, so a run is never left uncorrelated.
    """
    _task_snapshots[str(task_id)] = applog.snapshot_context()
    request = getattr(task, "request", None)
    request_id = getattr(request, REQUEST_ID_HEADER, None) if request else None
    applog.bind_context(
        request_id=request_id or applog.new_request_id(), task_id=task_id
    )
    logger.info(
        "task start: %s",
        getattr(task, "name", "?"),
        extra={"celery_task": getattr(task, "name", None)},
    )


@task_postrun.connect
def _clear_task_context(task_id=None, task=None, **_kwargs) -> None:
    logger.info("task end: %s", getattr(task, "name", "?"))
    snapshot = _task_snapshots.pop(str(task_id), None)
    if snapshot is not None:
        applog.restore_context(snapshot)
    else:
        applog.clear_context()


@task_failure.connect
def _log_task_failure(task_id=None, exception=None, sender=None, **_kwargs) -> None:
    """A last-resort record of a task that died.

    The tasks already log their own failures with context; this catches the
    ones that fail somewhere the task body never sees — serialisation, a
    revoked message, an error inside a retry — which previously vanished
    entirely.
    """
    logger.error(
        "task failed: %s (%s)",
        getattr(sender, "name", "?"),
        type(exception).__name__ if exception else "unknown",
        exc_info=exception,
        extra={"celery_task": getattr(sender, "name", None), "task_id": task_id},
    )
