"""Sprint 6 — pipeline SSE stream integration test.

Verifies GET /proposals/{proposal_id}/pipeline/stream reflects the *real*
rfp_documents.processing_status of the linked document (not a simulated run).
Terminal statuses (completed/failed) are used so the stream returns immediately
instead of polling.

Requires a reachable Postgres with the init schema applied.
"""

import json
import uuid

import psycopg2
import pytest

from app.core.config import settings
from app.core.security import create_access_token


def _conn():
    return psycopg2.connect(settings.database_url)


@pytest.fixture
def seeded_user():
    user_id = str(uuid.uuid4())
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
        "VALUES (%s, %s, 'h', 'Pipe', 'Tester');",
        (user_id, f"pipe_{uuid.uuid4().hex[:6]}@example.com"),
    )
    conn.commit()
    yield user_id
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def _seed_document(user_id: str, status: str, requirements: int = 0) -> str:
    """Seeds a document plus the proposal that fronts it. Returns the
    **proposal id** — the stream is addressed by proposal, not by rfp
    (GAP_ANALYSIS §1.2)."""
    rfp_id = str(uuid.uuid4())
    proposal_id = str(uuid.uuid4())
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rfp_documents (rfp_id, uploaded_by, file_name, s3_storage_key, processing_status) "
            "VALUES (%s, %s, 'rfp.pdf', 'k', %s);",
            (rfp_id, user_id, status),
        )
        cur.execute(
            "INSERT INTO proposals (proposal_id, owned_by, rfp_id, title) "
            "VALUES (%s, %s, %s, 'Pipeline Test');",
            (proposal_id, user_id, rfp_id),
        )
        for i in range(requirements):
            cur.execute(
                "INSERT INTO extracted_requirements (rfp_id, section_number, raw_text_content, category) "
                "VALUES (%s, %s, 'SHALL do a thing.', 'Technical');",
                (rfp_id, f"C.{i}"),
            )
    conn.close()
    return proposal_id


def _events(test_client, url: str) -> list[dict]:
    with test_client.stream("GET", url) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data:")]


def test_stream_reflects_completed_status(test_client, seeded_user):
    proposal_id = _seed_document(seeded_user, "completed", requirements=3)
    token, _ = create_access_token(seeded_user)

    events = _events(test_client, f"/proposals/{proposal_id}/pipeline/stream?token={token}")
    assert events, "expected at least one SSE frame"
    final = events[-1]
    assert final["status"] == "completed"
    assert final["overallProgress"] == 100
    assert all(step["status"] == "completed" for step in final["steps"])
    # the extract step surfaces the real requirement count
    extract = next(s for s in final["steps"] if s["id"] == "extract")
    assert extract["meta"] == "3 requirements"


def test_stream_reflects_failed_status(test_client, seeded_user):
    proposal_id = _seed_document(seeded_user, "failed")
    token, _ = create_access_token(seeded_user)

    final = _events(test_client, f"/proposals/{proposal_id}/pipeline/stream?token={token}")[-1]
    assert final["status"] == "failed"
    assert final["statusMessage"] == "Processing failed."


def test_stream_unknown_proposal_is_rejected(test_client, seeded_user):
    """An unknown proposal is refused outright rather than opening a 200 stream
    that carries a failure frame — the resolver runs before any streaming."""
    token, _ = create_access_token(seeded_user)
    resp = test_client.get(f"/proposals/{uuid.uuid4()}/pipeline/stream?token={token}")
    assert resp.status_code == 404


def test_stream_requires_a_token(test_client, seeded_user):
    """An anonymous caller used to receive any tenant's progress by rfp_id alone.
    No token must be a 401, the same as every sibling route."""
    proposal_id = _seed_document(seeded_user, "completed")

    assert test_client.get(f"/proposals/{proposal_id}/pipeline/stream").status_code == 401
    assert test_client.get(
        f"/proposals/{proposal_id}/pipeline/stream?token=garbage"
    ).status_code == 401


def test_stream_hides_another_tenants_proposal(test_client, seeded_user):
    """Another tenant's proposal must be indistinguishable from one that never
    existed, or the stream is an existence oracle."""
    proposal_id = _seed_document(seeded_user, "completed")
    other_token, _ = create_access_token(str(uuid.uuid4()))

    foreign = test_client.get(f"/proposals/{proposal_id}/pipeline/stream?token={other_token}")
    missing = test_client.get(f"/proposals/{uuid.uuid4()}/pipeline/stream?token={other_token}")

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert foreign.json() == missing.json()  # identical: no signal it exists
    # and crucially, never the real status of the seeded document
    assert "completed" not in foreign.text
