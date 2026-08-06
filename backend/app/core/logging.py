"""Logging configuration and request-scoped context.

Until this module existed, the application configured logging nowhere. Every
module was already doing the right thing — `logging.getLogger(__name__)`, lazy
`%s` args, `logger.exception` on the failure paths — and none of it was
reaching anyone:

    root level: WARNING (NOTSET -> WARNING effective)
    root handlers: []

With no handler on the root logger, `logger.info(...)` was discarded outright
and WARNING+ escaped through `logging.lastResort`, a bare stderr handler
formatting `%(message)s`: no timestamp, no level, no logger name. So the
best-instrumented paths in the system were the invisible ones — "Ingestion
start", "Ingestion complete: requirements=%d", every drafting progress line,
and the whole `llm.telemetry` record of model/tokens/latency.

Worse, it was invisible *asymmetrically*. Celery hijacks the root logger by
default, so `--loglevel=info` gave the worker handlers; uvicorn only configures
its own `uvicorn*` loggers and leaves root alone, so the API had none. The same
function logged differently depending on which process ran it.

This module fixes that in one place. It is deliberately stdlib `logging` rather
than structlog or loguru: 28 modules are already stdlib-correct, so a
`dictConfig` makes all of them work with no edits to any call site.

Two things every log line carries, via `_ContextFilter`:

  * **service** — "api" or "worker", so a shared log stream stays separable.
  * **request context** — request id, user, rfp, proposal, task. Held in
    `contextvars`, so call sites inherit it without threading an argument
    through. `run_ingestion` does not have to know what a request id is for its
    log lines to carry one.

Formats: human-readable in development, JSON in production (switched on
LOG_FORMAT, which defaults from ENVIRONMENT). JSON is what makes the context
queryable — a field you can filter on rather than prose you can only grep.
"""

import contextvars
import datetime as _dt
import json
import logging
import logging.config
import os
import uuid
from typing import Any

from app.core.config import settings

# --- request-scoped context -------------------------------------------------

# One var per field rather than a single dict: contextvars copy on task/thread
# boundaries, and per-field vars let a nested bind override one key without
# rebuilding — and without a child's write leaking into its parent's dict.
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id", default=None
)
_rfp_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "rfp_id", default=None
)
_proposal_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "proposal_id", default=None
)
_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "task_id", default=None
)

_VARS = {
    "request_id": _request_id,
    "user_id": _user_id,
    "rfp_id": _rfp_id,
    "proposal_id": _proposal_id,
    "task_id": _task_id,
}


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_context(**fields: Any) -> dict[str, contextvars.Token]:
    """Binds context fields for the current context; returns reset tokens.

    Unknown keys are ignored rather than raising: a caller adding context must
    never be able to break the path it is trying to describe. `None` values are
    skipped so `bind_context(user_id=maybe_none)` leaves an outer binding alone
    instead of blanking it.
    """
    tokens: dict[str, contextvars.Token] = {}
    for key, value in fields.items():
        var = _VARS.get(key)
        if var is None or value is None:
            continue
        tokens[key] = var.set(str(value))
    return tokens


def reset_context(tokens: dict[str, contextvars.Token]) -> None:
    """Restores what `bind_context` replaced.

    Resetting by token rather than clearing outright is what makes nesting safe:
    a worker task that binds rfp_id inside a request that already bound one
    hands the outer value back on exit.
    """
    for key, token in tokens.items():
        var = _VARS.get(key)
        if var is not None:
            var.reset(token)


def clear_context() -> None:
    """Drops all context. For process-level reuse (a worker between tasks)."""
    for var in _VARS.values():
        var.set(None)


def snapshot_context() -> dict[str, str | None]:
    """Captures every field, including the unset ones."""
    return {name: var.get() for name, var in _VARS.items()}


def restore_context(snapshot: dict[str, str | None]) -> None:
    """Puts the context back exactly as `snapshot_context` found it.

    Unlike `reset_context`, this undoes *any* binding made in between, not just
    the one that produced a token. That is what a Celery task needs: it binds
    its own identifiers deep inside the call (`rfp_id` in `tasks.py`), and with
    `CELERY_TASK_ALWAYS_EAGER=true` the task runs inline in the HTTP request
    that queued it — so without a wholesale restore, a document's id would leak
    out of the task and onto the rest of that request's log lines.
    """
    for name, value in snapshot.items():
        var = _VARS.get(name)
        if var is not None:
            var.set(value)


def current_context() -> dict[str, str]:
    """The bound fields, omitting unset ones."""
    return {name: value for name, var in _VARS.items() if (value := var.get()) is not None}


class _ContextFilter(logging.Filter):
    """Copies the bound context onto every record, plus a static service name.

    A filter rather than a LoggerAdapter so it applies to records from code we
    do not own — uvicorn, celery, sqlalchemy — not just our own call sites.
    """

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service
        record.context = current_context()
        return True


# --- formatters -------------------------------------------------------------

# LogRecord's own attributes. Anything else on a record came from `extra=` and
# belongs in the output — that is how a call site attaches a structured field
# without inventing a new logger.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {
    "asctime",
    "message",
    "taskName",
    "service",
    "context",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for an aggregator to index.

    Context is flattened to top level (`request_id`, not `context.request_id`)
    because that is what makes a query readable in every log tool that has to
    consume it.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": getattr(record, "service", "unknown"),
        }
        payload.update(getattr(record, "context", {}))

        # Source location, for the "where exactly" this whole system is for.
        payload["src"] = f"{record.module}:{record.funcName}:{record.lineno}"

        if record.exc_info:
            exc_type = record.exc_info[0]
            payload["error"] = {
                "type": exc_type.__name__ if exc_type else "Unknown",
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }
        elif record.exc_text:
            payload["error"] = {"traceback": record.exc_text}

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = _coerce(value)

        # default=str so an unserialisable extra degrades to its repr rather
        # than raising inside the logging call and losing the line entirely.
        return json.dumps(payload, default=str, ensure_ascii=False)


def _coerce(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)


class ConsoleFormatter(logging.Formatter):
    """Human-readable, for a developer reading a terminal.

    Same information as the JSON form, arranged for eyes: the context rides in
    a compact bracketed suffix so the message stays at a predictable column.
    """

    _FMT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self._FMT, datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = getattr(record, "context", {})
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _RESERVED
        }
        bits = [f"{k}={v}" for k, v in {**context, **extras}.items()]
        return f"{base} [{' '.join(bits)}]" if bits else base


# --- configuration ----------------------------------------------------------

_configured = False


def _resolve_format() -> str:
    fmt = (settings.log_format or "").strip().lower()
    if fmt in ("json", "console"):
        return fmt
    return "json" if settings.environment.lower() == "production" else "console"


def configure_logging(service: str | None = None, *, force: bool = False) -> None:
    """Installs the process-wide logging configuration. Idempotent.

    Call this as early as possible — at import of `app.main` for the API, and
    from Celery's `setup_logging` signal for the worker. Both run *after* the
    server framework has installed its own configuration, which is what lets
    ours take precedence.

    `service` defaults to $SERVICE_NAME, then "api". The worker passes "worker"
    explicitly, so a combined log stream stays separable by field rather than
    by guessing from the logger name.
    """
    global _configured
    if _configured and not force:
        return

    service = service or os.getenv("SERVICE_NAME") or "api"
    level = (settings.log_level or "INFO").upper()
    formatter = "json" if _resolve_format() == "json" else "console"

    logging.config.dictConfig(
        {
            "version": 1,
            # False so the 28 module-level loggers created at import time keep
            # working. Disabling them is the classic way to configure logging
            # and silence the entire application at the same time.
            "disable_existing_loggers": False,
            "filters": {
                "context": {
                    "()": "app.core.logging._ContextFilter",
                    "service": service,
                }
            },
            "formatters": {
                "json": {"()": "app.core.logging.JsonFormatter"},
                "console": {"()": "app.core.logging.ConsoleFormatter"},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": formatter,
                    "filters": ["context"],
                }
            },
            # Everything lands on the root handler, so third-party loggers are
            # formatted and correlated exactly like ours.
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                # Declared with no handlers of their own so uvicorn's default
                # config — already applied by the time we run — is overridden
                # and its records flow through ours instead of being printed
                # twice in two different formats.
                "uvicorn": {"handlers": [], "propagate": True, "level": level},
                "uvicorn.error": {"handlers": [], "propagate": True, "level": level},
                # Silenced, not dropped: RequestContextMiddleware emits a
                # richer completion line (status, duration, tenant, request id)
                # for the same event. Warnings still come through.
                "uvicorn.access": {"handlers": [], "propagate": True, "level": "WARNING"},
                # Chatty at INFO and rarely what you are debugging; raise
                # deliberately via LOG_LEVEL=DEBUG when you are.
                "botocore": {"level": "WARNING", "propagate": True},
                "boto3": {"level": "WARNING", "propagate": True},
                "s3transfer": {"level": "WARNING", "propagate": True},
                "urllib3": {"level": "WARNING", "propagate": True},
                "httpx": {"level": "WARNING", "propagate": True},
            },
        }
    )
    _configured = True
