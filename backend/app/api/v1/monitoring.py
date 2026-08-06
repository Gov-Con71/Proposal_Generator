"""Operational endpoints (Stories 5.3 / 5.5).

    GET /health   → liveness (process is up)
    GET /ready    → readiness (DB + Redis reachable) — for load-balancer checks
    GET /metrics  → aggregated LLM cost/latency/error telemetry
"""

import logging

from fastapi import APIRouter, Response, status

from app.core import telemetry
from app.core.config import settings
from app.core.db import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Monitoring"])


@router.get("/health", summary="Liveness probe")
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


def _check_database() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
    finally:
        conn.close()


def _check_redis() -> None:
    import redis

    redis.from_url(settings.cache_url, socket_timeout=0.5).ping()


@router.get("/ready", summary="Readiness probe (checks dependencies)")
def ready(response: Response) -> dict:
    """Reports dependency health — and, when a dependency is down, *why*.

    Both checks previously ended in `except Exception: pass`, so the one
    endpoint whose entire job is explaining the process's health destroyed the
    explanation on its way out. It answered `{"database": false}` and left you
    to guess between a wrong password, a DNS failure, and a dead host.

    The reason is logged in full and returned in summary form. The returned
    string is the exception *type* only: this route is unauthenticated, and an
    exception message from psycopg or redis routinely contains the connection
    string, host, and user.
    """
    checks: dict[str, bool] = {}
    reasons: dict[str, str] = {}

    for name, probe in (("database", _check_database), ("redis", _check_redis)):
        try:
            probe()
            checks[name] = True
        except Exception as exc:  # noqa: BLE001 — every failure means "not ready"
            checks[name] = False
            reasons[name] = type(exc).__name__
            logger.error(
                "readiness check failed: %s (%s)", name, exc, extra={"dependency": name}
            )

    ok = all(checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    body: dict = {"status": "ready" if ok else "degraded", "checks": checks}
    if reasons:
        body["reasons"] = reasons
    return body


@router.get("/metrics", summary="LLM cost + latency telemetry")
def metrics() -> dict:
    return telemetry.metrics_snapshot()
