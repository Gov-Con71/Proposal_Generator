"""Operational endpoints (Stories 5.3 / 5.5).

    GET /health   → liveness (process is up)
    GET /ready    → readiness (DB + Redis reachable) — for load-balancer checks
    GET /metrics  → aggregated LLM cost/latency/error telemetry
"""

from fastapi import APIRouter, Response, status

from app.core import telemetry
from app.core.config import settings
from app.core.db import get_connection

router = APIRouter(tags=["Monitoring"])


@router.get("/health", summary="Liveness probe")
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


@router.get("/ready", summary="Readiness probe (checks dependencies)")
def ready(response: Response) -> dict:
    checks = {"database": False, "redis": False}

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        conn.close()
        checks["database"] = True
    except Exception:
        pass

    try:
        import redis

        redis.from_url(settings.cache_url, socket_timeout=0.5).ping()
        checks["redis"] = True
    except Exception:
        pass

    ok = all(checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ok else "degraded", "checks": checks}


@router.get("/metrics", summary="LLM cost + latency telemetry")
def metrics() -> dict:
    return telemetry.metrics_snapshot()
