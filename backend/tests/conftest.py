import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture(scope="module")
def test_client():
    """Provides isolated instantiation wrapper for endpoint queries."""
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def _clear_rate_limit_counters():
    """Drops auth rate-limit counters around every test.

    The limiter stays enabled for the suite so the real request path is
    exercised, but its window is minutes long and every test shares one client
    IP — without this, failed-login counts would accumulate across tests and
    across consecutive runs, and the suite would start 429ing at random.
    """
    def _flush():
        try:
            from app.core.rate_limit import _redis

            client = _redis()
            keys = client.keys("rl:*")
            if keys:
                client.delete(*keys)
        except Exception:  # noqa: BLE001 — no Redis: the limiter fails open anyway
            pass

    _flush()
    yield
    _flush()


@pytest.fixture(autouse=True)
def _clear_hyde_cache():
    """Drops cached HyDE narratives (`hyde:*`) around every test.

    `_hyde_documents` (draft_writer) caches by content hash of (section_title,
    requirement_text) — several tests reuse the same title/text pair with
    different mocked LLM responses, and without this a later test can get a
    cache hit seeded by an earlier one instead of exercising its own mock.
    Same rationale as `_clear_rate_limit_counters` above, different Redis DB
    (CACHE_URL vs the rate limiter's).
    """
    def _flush():
        try:
            from app.core.cache import _redis

            client = _redis()
            keys = client.keys("hyde:*")
            if keys:
                client.delete(*keys)
        except Exception:  # noqa: BLE001 — no Redis: cache fails open anyway
            pass

    _flush()
    yield
    _flush()


@pytest.fixture
def other_tenant():
    """A second, real user id — for tenant-isolation assertions.

    Isolation tests used to mint a token for a random UUID that had no row in
    `users`. That stopped working when deactivation checks moved onto every
    authenticated request (GAP_ANALYSIS §4.4): an unknown subject is now a 401
    before ownership is ever considered, so those tests were asserting against
    the authentication boundary while believing they were testing the tenancy
    one. A real user is what actually exercises "authenticated, but not yours".
    """
    import uuid as _uuid

    import psycopg2

    from app.core.config import settings

    user_id = str(_uuid.uuid4())
    conn = psycopg2.connect(settings.database_url)
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
            "VALUES (%s, %s, 'h', 'Other', 'Tenant');",
            (user_id, f"other_{_uuid.uuid4().hex[:8]}@example.com"),
        )
    conn.close()
    yield user_id
    conn = psycopg2.connect(settings.database_url)
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
    conn.close()
