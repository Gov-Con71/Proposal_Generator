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


def _ticket(test_client, proposal_id: str, user_id: str) -> str:
    """Mints a stream ticket the way the client does: an authenticated POST.

    The stream no longer accepts an access token in its query string — that put
    a full-privilege credential into access logs and browser history
    (GAP_ANALYSIS §2.2). It takes a single-use ticket scoped to this proposal.
    """
    token, _ = create_access_token(user_id)
    res = test_client.post(
        f"/proposals/{proposal_id}/pipeline/ticket",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    return res.json()["ticket"]


def _stream_url(test_client, proposal_id: str, user_id: str) -> str:
    return (
        f"/proposals/{proposal_id}/pipeline/stream"
        f"?ticket={_ticket(test_client, proposal_id, user_id)}"
    )


def _raw_lines(test_client, url: str) -> list[str]:
    with test_client.stream("GET", url) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        return list(resp.iter_lines())


def _events(test_client, url: str) -> list[dict]:
    return [
        json.loads(line[6:]) for line in _raw_lines(test_client, url) if line.startswith("data:")
    ]


def test_stream_reflects_completed_status(test_client, seeded_user):
    proposal_id = _seed_document(seeded_user, "completed", requirements=3)

    events = _events(test_client, _stream_url(test_client, proposal_id, seeded_user))
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

    final = _events(test_client, _stream_url(test_client, proposal_id, seeded_user))[-1]
    assert final["status"] == "failed"
    assert final["statusMessage"] == "Processing failed."


def test_stream_that_outlives_its_budget_says_so(test_client, seeded_user, monkeypatch):
    """A document still working when the poll budget runs out must get an
    explicit closing frame. Returning silently closed the response with no
    explanation, and the client could not tell a slow ingestion from a dead
    server — the failure this stream exists to report accurately."""
    from app.api.v1 import pipeline as pipeline_api

    monkeypatch.setattr(pipeline_api, "_MAX_POLLS", 3)
    monkeypatch.setattr(pipeline_api, "_POLL_SECONDS", 0.01)

    proposal_id = _seed_document(seeded_user, "extracting")

    lines = _raw_lines(test_client, _stream_url(test_client, proposal_id, seeded_user))
    events = [json.loads(line[6:]) for line in lines if line.startswith("data:")]

    final = events[-1]
    assert final["status"] == "running"  # the ingestion is still going; only we gave up
    assert "taking longer than usual" in final["statusMessage"]
    # polls after the first produce no state change, so they must still put
    # bytes on the wire or an idle proxy drops the connection mid-extraction
    assert any(line.startswith(":") for line in lines), "expected a heartbeat comment"


def test_stream_unknown_proposal_is_rejected(test_client, seeded_user):
    """An unknown proposal is refused outright rather than opening a 200 stream
    that carries a failure frame — the resolver runs before any streaming."""
    token, _ = create_access_token(seeded_user)
    # Ownership is resolved when the ticket is minted, on the authenticated
    # request — so an unknown proposal never gets as far as a stream URL.
    resp = test_client.post(
        f"/proposals/{uuid.uuid4()}/pipeline/ticket",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_stream_requires_a_valid_ticket(test_client, seeded_user):
    """An anonymous caller used to receive any tenant's progress by rfp_id alone.
    No ticket must be a 401, the same as every sibling route."""
    proposal_id = _seed_document(seeded_user, "completed")

    assert test_client.get(f"/proposals/{proposal_id}/pipeline/stream").status_code == 401
    assert test_client.get(
        f"/proposals/{proposal_id}/pipeline/stream?ticket=garbage"
    ).status_code == 401


def test_a_ticket_works_once(test_client, seeded_user):
    """Single use is what makes a URL-borne credential tolerable: the copy left
    in an access log or browser history is already spent."""
    proposal_id = _seed_document(seeded_user, "completed")
    url = _stream_url(test_client, proposal_id, seeded_user)

    assert _events(test_client, url), "first use streams"
    assert test_client.get(url).status_code == 401, "replay must be refused"


def test_a_ticket_is_scoped_to_its_proposal(test_client, seeded_user):
    """A ticket travels in a URL, so it must not be a general capability: one
    lifted from a log must not open the same tenant's *other* proposals."""
    mine = _seed_document(seeded_user, "completed")
    other = _seed_document(seeded_user, "completed")
    ticket = _ticket(test_client, mine, seeded_user)

    assert test_client.get(
        f"/proposals/{other}/pipeline/stream?ticket={ticket}"
    ).status_code == 401


def test_stream_hides_another_tenants_proposal(test_client, seeded_user):
    """Another tenant's proposal must be indistinguishable from one that never
    existed, or the stream is an existence oracle."""
    proposal_id = _seed_document(seeded_user, "completed")

    # A *real* second tenant, not a token for a user that never existed: an
    # unknown subject is a 401 before ownership is even considered, which would
    # test the wrong boundary.
    other_id = str(uuid.uuid4())
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
            "VALUES (%s, %s, 'h', 'Other', 'Tenant');",
            (other_id, f"pipe_{uuid.uuid4().hex[:6]}@example.com"),
        )
    conn.close()
    other = {"Authorization": f"Bearer {create_access_token(other_id)[0]}"}

    # The check happens at ticket issue, which is where ownership is known.
    foreign = test_client.post(f"/proposals/{proposal_id}/pipeline/ticket", headers=other)
    missing = test_client.post(f"/proposals/{uuid.uuid4()}/pipeline/ticket", headers=other)

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    # Identical: no signal it exists. Compared field by field rather than whole
    # bodies, because every error response now also carries its own `requestId`
    # — which differs between any two requests by construction and says nothing
    # about the resource. Comparing the whole body would only assert that
    # correlation ids are not random.
    assert foreign.json()["detail"] == missing.json()["detail"]
    assert foreign.json().keys() == missing.json().keys()
    # and crucially, never the real status of the seeded document
    assert "completed" not in foreign.text

    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE user_id = %s;", (other_id,))
    conn.close()
