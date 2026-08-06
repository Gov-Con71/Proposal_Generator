"""Request correlation, the access log, and the unhandled-exception boundary.

Three gaps this closes, all of which made a production failure unexplainable:

1. **Nothing correlated a failure across the hop.** A single user action spans
   API -> Redis broker -> Celery worker -> LLM adapter -> DB. Before this, no
   identifier crossed any of those boundaries, so "my upload failed at 14:32"
   could not be turned into a causal chain.

2. **There was no access log.** No middleware existed beyond CORS, so "which
   route is erroring", "how slow", and "for which tenant" were unanswerable.

3. **There was no exception boundary.** `grep status_code=500` over the routes
   returns zero — every 500 this system produces is an *unhandled* exception.
   Starlette rendered it as a bare "Internal Server Error" with no identifier
   the user could quote back, so a support report and a log line could not be
   joined even in principle.

Deliberately a pure ASGI middleware rather than `BaseHTTPMiddleware`: the
pipeline progress endpoint is a long-lived `text/event-stream`, and
BaseHTTPMiddleware's response wrapping interferes with streaming responses.
This one only observes the message flow.
"""

import logging
import re
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import logging as applog
from app.core.config import settings

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"

# Where the id lives on the ASGI scope, for handlers that run outside this
# middleware's context binding. See RequestContextMiddleware.__call__.
SCOPE_REQUEST_ID = "app_request_id"

# An inbound request id is attacker-controlled text heading straight for a log
# aggregator. Constrain it to something that cannot forge a field boundary or
# inject a newline, and cap the length; anything else earns a fresh id.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

# Health checks run every few seconds forever. Logging them at INFO buries the
# traffic you actually care about; failures still surface, because the handler
# below logs any non-2xx regardless of path.
_QUIET_PATHS = frozenset({"/health", "/ready", "/metrics"})


def _client_request_id(headers: list[tuple[bytes, bytes]]) -> str | None:
    for key, value in headers:
        if key.lower() == b"x-request-id":
            candidate = value.decode("latin-1", "replace")
            return candidate if _SAFE_REQUEST_ID.match(candidate) else None
    return None


def _subject_for_logging(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Best-effort tenant id from the bearer token, for log context only.

    Signature-verified but not checked against the database — this must never
    become a second, weaker authentication path. `deps.get_current_user` remains
    the only thing that decides whether a request is allowed to proceed; all
    this does is let a log line say who a request belonged to.

    It is read here rather than bound inside the auth dependency because most
    routes are sync `def`, which FastAPI runs in a worker thread: a contextvar
    set there would not propagate back out to the middleware that logs the
    response.
    """
    for key, value in headers:
        if key.lower() != b"authorization":
            continue
        raw = value.decode("latin-1", "replace")
        scheme, _, token = raw.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            from app.core.security import decode_token

            return decode_token(token.strip())
        except Exception:  # noqa: BLE001 — an unusable token is simply no context
            return None
    return None


class RequestContextMiddleware:
    """Binds a request id (and tenant) for the life of the request, and logs it.

    The id is echoed on the response as `X-Request-ID` so a user reporting a
    failure holds the exact key that finds it in the logs.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers") or []
        request_id = _client_request_id(headers) or applog.new_request_id()
        tokens = applog.bind_context(
            request_id=request_id, user_id=_subject_for_logging(headers)
        )
        # Also on the scope, not only in the contextvar. Starlette's
        # ServerErrorMiddleware — which invokes the `Exception` handler — sits
        # *outside* all user middleware, so it runs after the `finally` below
        # has already unbound the context. The handler read an empty request id
        # and returned it to the client, which is precisely the case the id
        # exists for. The scope survives the whole exchange either way.
        scope[SCOPE_REQUEST_ID] = request_id

        status_code = 500
        started = time.perf_counter()

        header_name = REQUEST_ID_HEADER.lower().encode()

        async def send_wrapper(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                # Skip if a handler already set it — the unhandled-exception
                # handler does, because its response is built outside this
                # middleware and never reaches this wrapper at all.
                if not any(k.lower() == header_name for k, _ in message["headers"]):
                    message["headers"].append((header_name, request_id.encode()))
            await send(message)

        try:
            # Not logged here. An unhandled exception passes through this
            # middleware on its way *out* to ServerErrorMiddleware, which is
            # where the `Exception` handler below runs — so logging it in both
            # places writes the same traceback twice for one failure. The
            # handler is the one that keeps it, because it also has the Request.
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            path = scope.get("path", "")
            # Quiet paths stay quiet only while they are healthy.
            if path not in _QUIET_PATHS or status_code >= 400:
                level = (
                    logging.ERROR
                    if status_code >= 500
                    else logging.WARNING
                    if status_code >= 400
                    else logging.INFO
                )
                logger.log(
                    level,
                    "%s %s -> %d in %.1fms",
                    scope.get("method", "-"),
                    path,
                    status_code,
                    duration_ms,
                    extra={
                        "http_method": scope.get("method"),
                        "http_path": path,
                        "http_status": status_code,
                        "duration_ms": round(duration_ms, 1),
                        **_header_extras(headers),
                    },
                )
            applog.reset_context(tokens)


def _header_extras(headers: list[tuple[bytes, bytes]]) -> dict:
    if not settings.log_request_headers:
        return {}
    # Never the Authorization or Cookie headers — logging a credential is how a
    # log aggregator becomes a breach.
    denied = {b"authorization", b"cookie", b"set-cookie", b"proxy-authorization"}
    return {
        "headers": {
            k.decode("latin-1", "replace"): v.decode("latin-1", "replace")
            for k, v in headers
            if k.lower() not in denied
        }
    }


# --- exception handlers -----------------------------------------------------


def _request_id_of(request: Request) -> str:
    """The id for this request, preferring the scope over the contextvar.

    The two agree everywhere except on the unhandled-exception path, where the
    context has already been unbound by the time the handler runs — and that is
    the one path where an empty id would matter most.
    """
    return request.scope.get(SCOPE_REQUEST_ID) or applog.current_context().get(
        "request_id", ""
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Registers handlers that log every error path with its request id.

    The response bodies keep FastAPI's shape (`detail`) so no client contract
    changes; they gain one field, `requestId`, which is the whole point: it
    turns a user-visible failure into a log query.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException):
        request_id = _request_id_of(request)
        # 4xx is the application working as designed — a wrong password, a
        # missing row — so it is logged at WARNING without a traceback. A 5xx
        # raised deliberately still means a dependency failed, and gets one.
        if exc.status_code >= 500:
            logger.error(
                "handled %d on %s %s: %s",
                exc.status_code,
                request.method,
                request.url.path,
                exc.detail,
                exc_info=exc,
            )
        else:
            logger.warning(
                "%d on %s %s: %s",
                exc.status_code,
                request.method,
                request.url.path,
                exc.detail,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "requestId": request_id},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        request_id = _request_id_of(request)
        logger.warning(
            "422 on %s %s: %d validation error(s)",
            request.method,
            request.url.path,
            len(exc.errors()),
            extra={"validation_errors": exc.errors()},
        )
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "requestId": request_id},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        request_id = _request_id_of(request)
        logger.exception(
            "unhandled %s on %s %s",
            type(exc).__name__,
            request.method,
            request.url.path,
        )
        # The message stays generic — an exception string can carry a
        # connection URL or a row's contents — but the id is specific, and it
        # is the id that makes the report actionable.
        #
        # The header is set here rather than left to the middleware: this
        # response is built by ServerErrorMiddleware, outside it, so its
        # send_wrapper never sees it. Without this the one response a user is
        # most likely to be reading from a network tab is the only one with no
        # correlation id on it.
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error.",
                "requestId": request_id,
            },
            headers={REQUEST_ID_HEADER: request_id} if request_id else None,
        )
