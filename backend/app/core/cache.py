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

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


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
        logger.debug("cache_get miss (%s): %s", key, exc)
        return None


def cache_set(key: str, value, ttl: int | None = None) -> None:
    if not settings.cache_enabled:
        return
    try:
        _redis().set(key, json.dumps(value), ex=ttl or settings.cache_ttl_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache_set skip (%s): %s", key, exc)


def cache_delete(*keys: str) -> None:
    if not settings.cache_enabled or not keys:
        return
    try:
        _redis().delete(*keys)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache_delete skip (%s): %s", keys, exc)


# --- key builders (tenant-scoped) ------------------------------------------

def requirements_key(user_id, rfp_id) -> str:
    return f"reqs:{user_id}:{rfp_id}"


def sections_key(user_id, proposal_id) -> str:
    # Keyed on the proposal, unlike requirements/compliance: sections belong to
    # one proposal, so two proposals on the same RFP must not share this entry.
    return f"secs:{user_id}:{proposal_id}"


def compliance_key(user_id, rfp_id) -> str:
    return f"compliance:{user_id}:{rfp_id}"
