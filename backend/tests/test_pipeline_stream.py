"""Sprint 6 — pipeline SSE stream integration test.

Verifies GET /proposals/{rfp_id}/pipeline/stream reflects the *real*
rfp_documents.processing_status (not a simulated run). Terminal statuses
(completed/failed) are used so the stream returns immediately instead of polling.

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
    rfp_id = str(uuid.uuid4())
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rfp_documents (rfp_id, uploaded_by, file_name, s3_storage_key, processing_status) "
            "VALUES (%s, %s, 'rfp.pdf', 'k', %s);",
            (rfp_id, user_id, status),
        )
        for i in range(requirements):
            cur.execute(
                "INSERT INTO extracted_requirements (rfp_id, section_number, raw_text_content, category) "
                "VALUES (%s, %s, 'SHALL do a thing.', 'Technical');",
                (rfp_id, f"C.{i}"),
            )
    conn.close()
    return rfp_id


def _events(test_client, url: str) -> list[dict]:
    with test_client.stream("GET", url) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data:")]


def test_stream_reflects_completed_status(test_client, seeded_user):
    rfp_id = _seed_document(seeded_user, "completed", requirements=3)
    token, _ = create_access_token(seeded_user)

    events = _events(test_client, f"/proposals/{rfp_id}/pipeline/stream?token={token}")
    assert events, "expected at least one SSE frame"
    final = events[-1]
    assert final["status"] == "completed"
    assert final["overallProgress"] == 100
    assert all(step["status"] == "completed" for step in final["steps"])
    # the extract step surfaces the real requirement count
    extract = next(s for s in final["steps"] if s["id"] == "extract")
    assert extract["meta"] == "3 requirements"


def test_stream_reflects_failed_status(test_client, seeded_user):
    rfp_id = _seed_document(seeded_user, "failed")
    token, _ = create_access_token(seeded_user)

    final = _events(test_client, f"/proposals/{rfp_id}/pipeline/stream?token={token}")[-1]
    assert final["status"] == "failed"
    assert final["statusMessage"] == "Processing failed."


def test_stream_unknown_document_reports_not_found(test_client):
    final = _events(test_client, f"/proposals/{uuid.uuid4()}/pipeline/stream")[-1]
    assert final["status"] == "failed"
    assert final["statusMessage"] == "Document not found."


def test_stream_is_tenant_scoped_when_token_present(test_client, seeded_user):
    rfp_id = _seed_document(seeded_user, "completed")
    # a different tenant's token → the stream closes without leaking any frame
    other_token, _ = create_access_token(str(uuid.uuid4()))
    events = _events(test_client, f"/proposals/{rfp_id}/pipeline/stream?token={other_token}")
    assert events == []
