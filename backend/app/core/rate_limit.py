"""Redis-backed rate limiting for authentication (GAP_ANALYSIS.md §2.3).

Fixed-window counters over the Redis instance the cache already uses — no new
dependency, and shared across API replicas (an in-process limiter would reset on
deploy and be trivially evaded by hitting another replica).

Two deliberate choices:

* **Only failures are counted.** A user who types the right password is never
  throttled, and an attacker cannot lock a victim out of their own account by
  burning the budget with deliberate failures.
* **Fails open.** If Redis is unreachable the request is allowed, matching
  `core/cache.py`. A Redis blip must not lock every user out of the product.
  The trade-off is explicit: availability over throttling, logged at WARNING.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _redis():
    global _client
    if _client is None:
        import redis

        _client = redis.from_url(settings.cache_url, socket_timeout=0.5)
    return _client


def _key(bucket: str, identifier: str) -> str:
    return f"rl:{bucket}:{identifier}"


def check(bucket: str, identifier: str, limit: int) -> int:
    """Returns seconds to wait if `identifier` is over `limit`, else 0.

    Read-only: call before doing the work, and only `record_failure` after it
    actually fails, so successes cost nothing.
    """
    if not settings.rate_limit_enabled:
        return 0
    try:
        r = _redis()
        key = _key(bucket, identifier)
        count = r.get(key)
        if count is None or int(count) < limit:
            return 0
        ttl = r.ttl(key)
        return max(ttl, 1)  # never advertise a 0s retry
    except Exception as exc:  # noqa: BLE001 — fail open, see module docstring
        logger.warning("rate limit check skipped (redis unavailable): %s", exc)
        return 0


def record_failure(bucket: str, identifier: str, window_seconds: int) -> None:
    """Counts one failed attempt, starting the window on the first one."""
    if not settings.rate_limit_enabled:
        return
    try:
        r = _redis()
        key = _key(bucket, identifier)
        count = r.incr(key)
        if count == 1:
            # Only set the TTL on the first hit: re-expiring on every attempt
            # would let a steady stream of guesses hold the window open forever
            # without it ever elapsing.
            r.expire(key, window_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rate limit record skipped (redis unavailable): %s", exc)


def reset(bucket: str, identifier: str) -> None:
    """Clears a counter — called on success so a legitimate login wipes the
    failures that preceded it."""
    if not settings.rate_limit_enabled:
        return
    try:
        _redis().delete(_key(bucket, identifier))
    except Exception as exc:  # noqa: BLE001
        logger.warning("rate limit reset skipped (redis unavailable): %s", exc)


def client_ip(request) -> str:
    """Best-effort client address.

    Uses Starlette's `request.client.host`, which is correct only when uvicorn
    runs with --proxy-headers behind a trusted proxy. Deployed without it every
    caller appears as the load balancer and shares one bucket — which is why the
    per-account limit below is the primary control and this is secondary.
    """
    return request.client.host if request.client else "unknown"
