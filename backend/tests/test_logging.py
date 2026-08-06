"""Guards for the logging system.

Every assertion here corresponds to something that was silently broken before
this suite existed, and that would go back to being silently broken without it
— which is the awkward property of logging: nothing fails when it stops
working. The suite exists because "we thought it was logging" is the failure
mode, and it presents identically to "nothing went wrong".
"""

import contextlib
import io
import json
import logging
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import logging as applog
from app.core.middleware import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    install_exception_handlers,
)


@pytest.fixture(autouse=True)
def _clean_context():
    """Context is process-global; a leak between tests would mask a real one."""
    applog.clear_context()
    yield
    applog.clear_context()


@contextlib.contextmanager
def _capture(service: str = "test"):
    """Applies the real configuration and yields what its handler writes.

    Only the *destination* is redirected — the handler, formatter, filters and
    levels are the ones `configure_logging` built, so this exercises the real
    configuration rather than a re-implementation of it. Reading pytest's
    capsys/capfd instead does not work here: the handler holds the `sys.stdout`
    object that existed when dictConfig ran, which under pytest is already a
    capture shim.

    dictConfig replaces the root handlers wholesale, so the originals are put
    back afterwards or caplog stops working for the rest of the session.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    buffer = io.StringIO()
    try:
        applog.configure_logging(service=service, force=True)
        for handler in root.handlers:
            handler.setStream(buffer)
        yield buffer
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


@pytest.fixture
def console_logs():
    with _capture() as buffer:
        yield buffer


@pytest.fixture
def json_logs(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.log_format", "json")
    with _capture(service="worker") as buffer:
        yield buffer


# --- the core regression: INFO reaching a handler at all --------------------


def test_info_is_emitted_after_configuration(console_logs):
    """The whole reason this module exists.

    Before it, the root logger had no handlers and an effective level of
    WARNING, so every `logger.info` in the application — "Ingestion start",
    "Ingestion complete: requirements=%d", the per-section drafting lines, the
    entire llm.telemetry record — was discarded at the call site.
    """
    logging.getLogger("app.services.ingestion").info("Ingestion start: rfp=%s", "r1")

    assert "Ingestion start: rfp=r1" in console_logs.getvalue()


def test_configuration_does_not_disable_existing_loggers(console_logs):
    """The 28 module loggers are created at import, i.e. before configuration.

    `disable_existing_loggers` defaults to True in dictConfig, and leaving it
    that way is the classic way to configure logging and silence the whole
    application in the same commit.
    """
    # This logger object exists from the moment app.core.cache was imported.
    from app.core import cache

    cache.logger.warning("cache unavailable")
    assert "cache unavailable" in console_logs.getvalue()


def test_logs_go_to_stdout_not_stderr():
    """Container log collectors treat stderr as an error stream; routine INFO
    arriving there gets misclassified in every dashboard downstream.

    Asserted against the configured handler rather than captured output,
    because the point is *which stream it was pointed at*.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        applog.configure_logging(service="test", force=True)
        streams = [h.stream for h in root.handlers if isinstance(h, logging.StreamHandler)]
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)

    assert streams
    assert all(s is sys.stdout for s in streams)


# --- structure --------------------------------------------------------------


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.strip().splitlines() if line.startswith("{")]


def test_json_format_carries_context_as_queryable_fields(json_logs):
    """Context must be a *field*, not prose.

    `"Ingestion start: rfp=%s"` can only be grepped. `{"rfp_id": "..."}` can be
    filtered and grouped, which is the difference between finding one failure
    and understanding a class of them.
    """
    applog.bind_context(request_id="req-1", rfp_id="rfp-9", user_id="u-2")
    logging.getLogger("app.services.ingestion").info("Ingestion start")

    (entry,) = _json_lines(json_logs.getvalue())

    assert entry["request_id"] == "req-1"
    assert entry["rfp_id"] == "rfp-9"
    assert entry["user_id"] == "u-2"
    assert entry["service"] == "worker"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "app.services.ingestion"


def test_json_format_records_the_traceback(json_logs):
    """`logger.exception` is useless if the traceback is dropped in transit —
    the stack is the "exactly where" the whole system is for."""
    try:
        raise ValueError("model 'gemini-1.0' is retired")
    except ValueError:
        logging.getLogger("app.test").exception("Ingestion failed")

    (entry,) = _json_lines(json_logs.getvalue())

    assert entry["error"]["type"] == "ValueError"
    assert "retired" in entry["error"]["message"]
    assert "Traceback" in entry["error"]["traceback"]


def test_extra_fields_survive_to_the_output(json_logs):
    """`llm.telemetry` attaches model and latency this way; they are what you
    group by to answer "which model got slow, and when"."""
    logging.getLogger("llm.telemetry").info(
        "llm_call", extra={"llm_model": "gemini-2.5-flash", "latency_ms": 812.4}
    )

    (entry,) = _json_lines(json_logs.getvalue())
    assert entry["llm_model"] == "gemini-2.5-flash"
    assert entry["latency_ms"] == 812.4


def test_an_unserialisable_extra_does_not_lose_the_line(json_logs):
    """A formatter that raises inside a logging call destroys the very record
    that was trying to explain a failure."""
    logging.getLogger("app.test").warning("odd", extra={"obj": object()})

    (entry,) = _json_lines(json_logs.getvalue())
    assert entry["msg"] == "odd"
    assert "object" in entry["obj"]


# --- context mechanics ------------------------------------------------------


def test_binding_none_does_not_erase_an_outer_value():
    """`bind_context(user_id=maybe_none)` must not blank a known tenant."""
    applog.bind_context(user_id="u-1")
    applog.bind_context(user_id=None)
    assert applog.current_context()["user_id"] == "u-1"


def test_reset_restores_the_outer_binding():
    applog.bind_context(rfp_id="outer")
    tokens = applog.bind_context(rfp_id="inner")
    assert applog.current_context()["rfp_id"] == "inner"
    applog.reset_context(tokens)
    assert applog.current_context()["rfp_id"] == "outer"


def test_restore_undoes_bindings_made_after_the_snapshot():
    """What protects an eager Celery task from leaking its ids into the request
    that queued it — the task binds rfp_id deep inside `tasks.py`, where no
    token is available to reset."""
    applog.bind_context(request_id="req-1")
    snapshot = applog.snapshot_context()
    applog.bind_context(rfp_id="rfp-1", task_id="t-1")

    applog.restore_context(snapshot)

    assert applog.current_context() == {"request_id": "req-1"}


# --- the HTTP boundary ------------------------------------------------------


@pytest.fixture
def boundary_app():
    """A minimal app with the real middleware and handlers.

    Deliberately not the production app: this needs a route that genuinely
    explodes, and adding one to `app.main` to satisfy a test would be a route
    that exists only to fail.
    """
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("the database went away")

    @app.get("/fine")
    def fine():
        return {"context": applog.current_context()}

    return app


def test_every_response_carries_a_request_id(boundary_app):
    with TestClient(boundary_app) as client:
        response = client.get("/fine")
    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]


def test_an_unhandled_error_returns_the_id_instead_of_a_bare_500(boundary_app, caplog):
    """`grep status_code=500` over the routes returns zero — every 500 this
    system produces is unhandled. It used to render as Starlette's bare
    "Internal Server Error", so a user's report and the log line that explained
    it could not be joined even in principle."""
    with caplog.at_level(logging.ERROR):
        with TestClient(boundary_app, raise_server_exceptions=False) as client:
            response = client.get("/boom")

    assert response.status_code == 500
    request_id = response.json()["requestId"]
    assert request_id

    # The id in the user's hand is the id in the log, and the log has the cause.
    assert request_id == response.headers[REQUEST_ID_HEADER]
    assert any(
        record.levelno >= logging.ERROR
        and "the database went away" in (record.exc_text or str(record.exc_info))
        for record in caplog.records
    )


def test_the_error_body_does_not_leak_the_exception_message(boundary_app):
    """An exception string routinely carries a connection URL or row contents.
    The id is specific so the message does not have to be."""
    with TestClient(boundary_app, raise_server_exceptions=False) as client:
        body = client.get("/boom").json()
    assert "database went away" not in json.dumps(body)


def test_a_client_supplied_request_id_is_honoured(boundary_app):
    """Lets a caller correlate across a system boundary it already traces."""
    supplied = uuid.uuid4().hex
    with TestClient(boundary_app) as client:
        response = client.get("/fine", headers={REQUEST_ID_HEADER: supplied})
    assert response.headers[REQUEST_ID_HEADER] == supplied
    assert response.json()["context"]["request_id"] == supplied


@pytest.mark.parametrize(
    "hostile",
    [
        "short",                       # below the minimum length
        "a" * 200,                     # unbounded growth in every log line
        "abc\ndef ghi jkl",            # forges a second log line
        'x" injected="yes',            # forges a field in a JSON aggregator
        "id with spaces here",
    ],
)
def test_a_hostile_request_id_is_rejected(boundary_app, hostile):
    """An inbound header is attacker-controlled text heading for a log
    aggregator. Anything that could forge a line or a field earns a fresh id."""
    with TestClient(boundary_app) as client:
        returned = client.get("/fine", headers={REQUEST_ID_HEADER: hostile}).headers[
            REQUEST_ID_HEADER
        ]
    assert returned != hostile
    assert "\n" not in returned and '"' not in returned and " " not in returned


def test_context_does_not_survive_between_requests(boundary_app):
    """A leaked request id attributes one user's failure to another's request —
    worse than no correlation, because it is confidently wrong."""
    with TestClient(boundary_app) as client:
        first = client.get("/fine", headers={REQUEST_ID_HEADER: "a" * 20}).json()
        second = client.get("/fine").json()

    assert first["context"]["request_id"] == "a" * 20
    assert second["context"]["request_id"] != "a" * 20


def test_the_access_log_records_status_and_duration(boundary_app, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        with TestClient(boundary_app) as client:
            client.get("/fine")

    (record,) = [r for r in caplog.records if r.name == "app.request"]
    assert record.http_status == 200
    assert record.http_path == "/fine"
    assert record.duration_ms >= 0


# --- fail-open paths that used to fail silently -----------------------------


def test_an_unreachable_cache_is_reported_at_warning(monkeypatch, caplog):
    """GAP_ANALYSIS §1.3: the ingestion worker ran with no CACHE_URL, could not
    reach Redis at all, and served stale empty requirement lists with a 200.
    Nothing said so, because the only record was a DEBUG line and DEBUG was
    never emitted."""
    from app.core import cache

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "_last_warned_at", 0.0)
    monkeypatch.setattr(cache, "_redis", lambda: (_ for _ in ()).throw(ConnectionError("no route")))

    with caplog.at_level(logging.WARNING, logger="app.core.cache"):
        assert cache.cache_get("reqs:u:r") is None

    assert "cache unavailable" in caplog.text


def test_repeated_cache_failures_do_not_flood_the_log(monkeypatch, caplog):
    """A Redis outage must stay visible without writing a warning per request."""
    from app.core import cache

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "_last_warned_at", 0.0)
    monkeypatch.setattr(cache, "_suppressed", 0)
    monkeypatch.setattr(cache, "_redis", lambda: (_ for _ in ()).throw(ConnectionError("no route")))

    with caplog.at_level(logging.WARNING, logger="app.core.cache"):
        for _ in range(50):
            cache.cache_get("reqs:u:r")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_the_readiness_probe_says_why_a_dependency_is_down(monkeypatch, caplog):
    """It used to `except Exception: pass` — the one endpoint whose job is
    explaining the process's health discarded the explanation on the way out,
    leaving a bad password and a dead host indistinguishable."""
    from app.api.v1 import monitoring

    monkeypatch.setattr(
        monitoring, "_check_redis", lambda: (_ for _ in ()).throw(ConnectionError("no route"))
    )

    class _Response:
        status_code = 200

    with caplog.at_level(logging.ERROR, logger="app.api.v1.monitoring"):
        body = monitoring.ready(_Response())

    assert body["status"] == "degraded"
    assert body["reasons"]["redis"] == "ConnectionError"
    assert "no route" in caplog.text  # the full reason reaches the operator


def test_the_readiness_probe_does_not_leak_connection_details(monkeypatch):
    """`/ready` is unauthenticated, and a redis/psycopg exception message
    routinely contains the host, user and password."""
    from app.api.v1 import monitoring

    secret = "redis://admin:hunter2@10.0.0.5:6379"
    monkeypatch.setattr(
        monitoring, "_check_redis", lambda: (_ for _ in ()).throw(ConnectionError(secret))
    )

    class _Response:
        status_code = 200

    body = monitoring.ready(_Response())
    assert "hunter2" not in json.dumps(body)


# --- the hop into the worker ------------------------------------------------


def test_the_request_id_is_attached_to_an_outgoing_task():
    """Ingestion and drafting run in another process, minutes later. Without
    this the API's log of an upload and the worker's log of its failure are two
    unrelated events."""
    from app.worker import celery_app as wiring

    applog.bind_context(request_id="req-abc")
    headers: dict = {}
    wiring._publish_request_id(headers=headers)

    assert headers[wiring.REQUEST_ID_HEADER] == "req-abc"


def test_a_task_rebinds_the_publishing_request_id():
    from app.worker import celery_app as wiring

    class _Request:
        pass

    class _Task:
        name = "ingest_document"
        request = _Request()

    task = _Task()
    setattr(task.request, wiring.REQUEST_ID_HEADER, "req-abc")

    wiring._bind_task_context(task_id="celery-1", task=task)
    try:
        context = applog.current_context()
        assert context["request_id"] == "req-abc"
        assert context["task_id"] == "celery-1"
    finally:
        wiring._clear_task_context(task_id="celery-1", task=task)


def test_a_task_without_an_inherited_id_still_gets_one():
    """A run must never be uncorrelated — an eager task or a scheduled one has
    no publisher to inherit from."""
    from app.worker import celery_app as wiring

    class _Task:
        name = "ingest_document"
        request = object()

    task = _Task()
    wiring._bind_task_context(task_id="celery-2", task=task)
    try:
        assert applog.current_context()["request_id"]
    finally:
        wiring._clear_task_context(task_id="celery-2", task=task)


def test_an_eager_task_does_not_clobber_the_calling_requests_context():
    """`CELERY_TASK_ALWAYS_EAGER=true` runs the task inline in the HTTP request
    that queued it. Clearing context on postrun — the obvious implementation —
    would blank the request id for the rest of that request's log lines, and
    leak the task's rfp_id into them on the way."""
    from app.worker import celery_app as wiring

    class _Task:
        name = "ingest_document"
        request = object()

    applog.bind_context(request_id="req-outer")
    task = _Task()

    wiring._bind_task_context(task_id="celery-3", task=task)
    applog.bind_context(rfp_id="rfp-inner")  # as app/worker/tasks.py does
    wiring._clear_task_context(task_id="celery-3", task=task)

    assert applog.current_context() == {"request_id": "req-outer"}


def test_a_failing_request_is_logged_at_error(boundary_app, caplog):
    """So an alert can key on level alone, without parsing the message."""
    with caplog.at_level(logging.INFO, logger="app.request"):
        with TestClient(boundary_app, raise_server_exceptions=False) as client:
            client.get("/boom")

    completion = [r for r in caplog.records if r.name == "app.request" and hasattr(r, "http_status")]
    assert completion and completion[-1].levelno == logging.ERROR
