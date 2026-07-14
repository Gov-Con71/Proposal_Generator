"""LLM cost + latency telemetry (Story 5.3).

Records per-model call counts, token usage, latency, and errors. Counters live
in the shared Redis (so the API and Celery worker aggregate into one place),
and every call also emits a structured log line for CloudWatch/Sentry scraping.
Fail-open: telemetry never breaks the request path.
"""

import logging
import time

from app.core.config import settings

logger = logging.getLogger("llm.telemetry")

# Rough public list prices (USD per 1M tokens) for cost estimation. Adjust as
# pricing changes — this is for a ballpark spend dashboard, not billing.
_PRICES = {
    "gemini-2.0-flash": {"in": 0.10, "out": 0.40},
    "text-embedding-004": {"in": 0.0, "out": 0.0},
}

_H_CALLS = "llm:calls"
_H_ERRORS = "llm:errors"
_H_TOKENS_IN = "llm:tokens_in"
_H_TOKENS_OUT = "llm:tokens_out"
_H_LATENCY = "llm:latency_ms"


def now() -> float:
    return time.perf_counter()


def _redis():
    import redis

    return redis.from_url(settings.cache_url, socket_timeout=0.5)


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _record(model: str, in_tokens: int, out_tokens: int, latency_ms: float, ok: bool) -> None:
    logger.info(
        "llm_call model=%s in_tokens=%d out_tokens=%d latency_ms=%.1f ok=%s",
        model, in_tokens, out_tokens, latency_ms, ok,
    )
    if not settings.telemetry_enabled:
        return
    try:
        pipe = _redis().pipeline()
        pipe.hincrby(_H_CALLS, model, 1)
        if not ok:
            pipe.hincrby(_H_ERRORS, model, 1)
        pipe.hincrby(_H_TOKENS_IN, model, int(in_tokens))
        pipe.hincrby(_H_TOKENS_OUT, model, int(out_tokens))
        pipe.hincrbyfloat(_H_LATENCY, model, latency_ms)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001 — telemetry is best-effort
        logger.debug("telemetry record skipped: %s", exc)


def record_response(model: str, response, start: float) -> None:
    """Records a successful call, pulling token counts from usage_metadata."""
    um = getattr(response, "usage_metadata", None)
    in_tokens = getattr(um, "prompt_token_count", 0) or 0
    out_tokens = getattr(um, "candidates_token_count", 0) or 0
    _record(model, in_tokens, out_tokens, _elapsed_ms(start), ok=True)


def record_error(model: str, start: float) -> None:
    _record(model, 0, 0, _elapsed_ms(start), ok=False)


def _cost(model: str, in_tokens: int, out_tokens: int) -> float:
    price = _PRICES.get(model, {"in": 0.0, "out": 0.0})
    return round(in_tokens / 1e6 * price["in"] + out_tokens / 1e6 * price["out"], 4)


def metrics_snapshot() -> dict:
    """Returns aggregated per-model telemetry for the /metrics endpoint."""
    try:
        r = _redis()

        def _h(key):
            return {k.decode(): v.decode() for k, v in r.hgetall(key).items()}

        calls, errors = _h(_H_CALLS), _h(_H_ERRORS)
        tin, tout, lat = _h(_H_TOKENS_IN), _h(_H_TOKENS_OUT), _h(_H_LATENCY)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": str(exc)}

    models = {}
    totals = {"calls": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    for model in set(calls) | set(tin):
        n = int(calls.get(model, 0))
        in_tok, out_tok = int(tin.get(model, 0)), int(tout.get(model, 0))
        err = int(errors.get(model, 0))
        latency_sum = float(lat.get(model, 0.0))
        cost = _cost(model, in_tok, out_tok)
        models[model] = {
            "calls": n,
            "errors": err,
            "tokens_in": in_tok,
            "tokens_out": out_tok,
            "avg_latency_ms": round(latency_sum / n, 1) if n else 0.0,
            "est_cost_usd": cost,
        }
        totals["calls"] += n
        totals["errors"] += err
        totals["tokens_in"] += in_tok
        totals["tokens_out"] += out_tok
        totals["cost_usd"] = round(totals["cost_usd"] + cost, 4)

    return {"available": True, "totals": totals, "by_model": models}
