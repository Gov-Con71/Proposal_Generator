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