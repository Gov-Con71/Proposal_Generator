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
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50},
    "gemini-embedding-001": {"in": 0.15, "out": 0.0},
    # Retained so historical spend for retired models still resolves.
    "gemini-2.0-flash": {"in": 0.10, "out": 0.40},
    "text-embedding-004": {"in": 0.0, "out": 0.0},
}

_H_CALLS = "llm:calls"
_H_ERRORS = "llm:errors"
_H_TOKENS_IN = "llm:tokens_in"
_H_TOKENS_OUT = "llm:tokens_out"
_H_TOKENS_CACHED = "llm:tokens_cached"
_H_LATENCY = "llm:latency_ms"

# A cached input token bills at roughly a quarter of a standard input token on
# providers with prompt/context caching (Gemini's published context-caching
# rate) — same "ballpark, not billing" caveat as _PRICES above.
_CACHE_DISCOUNT = 0.25


def now() -> float:
    return time.perf_counter()


def _redis():
    import redis

    return redis.from_url(settings.cache_url, socket_timeout=0.5)


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _record(
    model: str, in_tokens: int, out_tokens: int, latency_ms: float, ok: bool, cached_tokens: int = 0
) -> None:
    # Also emitted as structured fields, not just interpolated prose: this is
    # the line you aggregate to answer "which model is slow" or "when did the
    # error rate change", and prose can only be grepped, not grouped.
    logger.info(
        "llm_call model=%s in_tokens=%d out_tokens=%d cached_tokens=%d latency_ms=%.1f ok=%s",
        model, in_tokens, out_tokens, cached_tokens, latency_ms, ok,
        extra={
            "llm_model": model,
            "tokens_in": in_tokens,
            "tokens_out": out_tokens,
            "tokens_cached": cached_tokens,
            "latency_ms": round(latency_ms, 1),
            "ok": ok,
        },
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
        if cached_tokens:
            pipe.hincrby(_H_TOKENS_CACHED, model, int(cached_tokens))
        pipe.hincrbyfloat(_H_LATENCY, model, latency_ms)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001 — telemetry is best-effort
        # WARNING, not DEBUG: this failing means /metrics is quietly lying
        # about spend and error rates, which is worse than it being absent.
        logger.warning("telemetry record skipped (%s): %s", type(exc).__name__, exc)


def record_response(model: str, response, start: float) -> None:
    """Records a successful call, pulling token counts from usage_metadata.

    `cached_content_token_count` (Gemini) / the OpenAI-style
    `usage.prompt_tokens_details.cached_tokens` shim (Featherless) is how many
    of `in_tokens` were served from the provider's prompt/context cache rather
    than billed at full price — see `format_*_block` in `draft_writer.py` for
    what makes a prefix cacheable in the first place. Absent on a provider/
    response that doesn't report it, which reads as 0 (no visible caching),
    not an error.
    """
    um = getattr(response, "usage_metadata", None)
    in_tokens = getattr(um, "prompt_token_count", 0) or 0
    out_tokens = getattr(um, "candidates_token_count", 0) or 0
    cached_tokens = getattr(um, "cached_content_token_count", 0) or 0
    _record(model, in_tokens, out_tokens, _elapsed_ms(start), ok=True, cached_tokens=cached_tokens)


def record_error(model: str, start: float) -> None:
    _record(model, 0, 0, _elapsed_ms(start), ok=False)


def _cost(model: str, in_tokens: int, out_tokens: int, cached_tokens: int = 0) -> float:
    price = _PRICES.get(model, {"in": 0.0, "out": 0.0})
    cached_tokens = min(cached_tokens, in_tokens)
    standard_in = in_tokens - cached_tokens
    cost = (
        standard_in / 1e6 * price["in"]
        + cached_tokens / 1e6 * price["in"] * _CACHE_DISCOUNT
        + out_tokens / 1e6 * price["out"]
    )
    return round(cost, 4)


def metrics_snapshot() -> dict:
    """Returns aggregated per-model telemetry for the /metrics endpoint."""
    try:
        r = _redis()

        def _h(key):
            return {k.decode(): v.decode() for k, v in r.hgetall(key).items()}

        calls, errors = _h(_H_CALLS), _h(_H_ERRORS)
        tin, tout, tcached = _h(_H_TOKENS_IN), _h(_H_TOKENS_OUT), _h(_H_TOKENS_CACHED)
        lat = _h(_H_LATENCY)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": str(exc)}

    models = {}
    totals = {
        "calls": 0, "errors": 0, "tokens_in": 0, "tokens_out": 0, "tokens_cached": 0, "cost_usd": 0.0
    }
    for model in set(calls) | set(tin):
        n = int(calls.get(model, 0))
        in_tok, out_tok = int(tin.get(model, 0)), int(tout.get(model, 0))
        cached_tok = int(tcached.get(model, 0))
        err = int(errors.get(model, 0))
        latency_sum = float(lat.get(model, 0.0))
        cost = _cost(model, in_tok, out_tok, cached_tok)
        models[model] = {
            "calls": n,
            "errors": err,
            "tokens_in": in_tok,
            "tokens_out": out_tok,
            "tokens_cached": cached_tok,
            "avg_latency_ms": round(latency_sum / n, 1) if n else 0.0,
            "est_cost_usd": cost,
        }
        totals["calls"] += n
        totals["errors"] += err
        totals["tokens_in"] += in_tok
        totals["tokens_out"] += out_tok
        totals["tokens_cached"] += cached_tok
        totals["cost_usd"] = round(totals["cost_usd"] + cost, 4)

    return {"available": True, "totals": totals, "by_model": models}
