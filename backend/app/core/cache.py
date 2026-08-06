"""Redis-backed read cache (Story 4.4).

A tiny, fail-open JSON cache for hot read endpoints. Every operation is wrapped
so that a Redis outage degrades to a cache miss rather than an error — caching
must never break correctness. Keys are always tenant-scoped by the caller.

**The invariant: every writer of a cached entity must evict every key derived
from it — including the writers that have no request context.**

Fail-open is what makes a missed eviction so expensive: there is no error to
notice. The API layer evicts on its own mutations, which is easy to remember
because the eviction sits next to the write. The Celery workers are the trap —
they write straight to the database, so nothing on the request path can evict
for them:

    reqs:{user}:{rfp}         ingestion worker · requirement PATCH/DELETE
    compliance:{user}:{rfp}   (derived from requirements — same writers)
    secs:{user}:{proposal}    drafting agent · section create/update/approve/
                              regenerate/generate

That is not hypothetical. The ingestion worker shipped without its eviction and
served a stale empty requirement list, with a 200, for a full TTL after every
successful run (GAP_ANALYSIS §1.3); the drafting agent then repeated it. Both
are covered by `tests/test_cache_invalidation.py` — extend it when you add a
key or a writer, because nothing else will tell you.
"""

import json
import logging
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None

# Fail-open used to mean fail-silent: every failure below was logged at DEBUG,
# and DEBUG was never emitted. That is exactly how the ingestion worker ran for
# weeks with no CACHE_URL, unable to reach Redis at all, serving stale empty
# requirement lists with a 200 and no error anywhere (GAP_ANALYSIS §1.3).
#
# WARNING is the right level — a dependency is unreachable — but an outage
# would then log on every request. So the first failure is reported
# immediately, and repeats are collapsed to one line per interval carrying the
# suppressed count, which keeps a total misconfiguration loud and a blip cheap.
_DEGRADED_LOG_INTERVAL_SECONDS = 60.0
_last_warned_at = 0.0
_suppressed = 0


def _warn_degraded(operation: str, key: str, exc: Exception) -> None:
    global _last_warned_at, _suppressed

    now = time.monotonic()
    if now - _last_warned_at < _DEGRADED_LOG_INTERVAL_SECONDS:
        _suppressed += 1
        logger.debug("cache %s degraded (%s): %s", operation, key, exc)
        return

    logger.warning(
        "cache unavailable — serving uncached (%s on %s): %s%s",
        operation,
        key,
        exc,
        f" [+{_suppressed} similar suppressed]" if _suppressed else "",
        extra={"cache_operation": operation, "suppressed": _suppressed},
    )
    _last_warned_at = now
    _suppressed = 0


def _redis():
    global _client
    if _client is None:
        import redis

        _client = redis.from_url(settings.cache_url, socket_timeout=0.5)
    return _client


def cache_get(key: str):
    """Returns the decoded cached value, or None on miss / any failure."""
    if not settings.cache_enabled:
        return None
    try:
        raw = _redis().get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 — cache is best-effort
        _warn_degraded("get", key, exc)
        return None


def cache_set(key: str, value, ttl: int | None = None) -> None:
    if not settings.cache_enabled:
        return
    try:
        _redis().set(key, json.dumps(value), ex=ttl or settings.cache_ttl_seconds)
    except Exception as exc:  # noqa: BLE001
        _warn_degraded("set", key, exc)


def cache_delete(*keys: str) -> None:
    if not settings.cache_enabled or not keys:
        return
    try:
        _redis().delete(*keys)
    except Exception as exc:  # noqa: BLE001
        # The most expensive of the three to lose silently: a missed eviction
        # serves stale data with a 200 for a full TTL.
        _warn_degraded("delete", ",".join(keys), exc)


# --- key builders (tenant-scoped) ------------------------------------------

def requirements_key(user_id, rfp_id) -> str:
    return f"reqs:{user_id}:{rfp_id}"


def sections_key(user_id, proposal_id) -> str:
    # Keyed on the proposal, unlike requirements/compliance: sections belong to
    # one proposal, so two proposals on the same RFP must not share this entry.
    return f"secs:{user_id}:{proposal_id}"


def compliance_key(user_id, rfp_id) -> str:
    return f"compliance:{user_id}:{rfp_id}"
