"""Sprint 3.6 — workspace CRUD + RAG integration test.

Real Postgres + pgvector; only the external embedding/LLM calls are stubbed.
Requires the init schema + rag_schema applied and a pgvector-enabled database.
"""

import uuid

import psycopg2
import pytest

from app.core.config import settings
from app.core.security import create_access_token


def _conn():
    return psycopg2.connect(settings.database_url)


@pytest.fixture
def proposal_with_requirements():
    """Seeds a user + rfp_document + a proposal linked to it + two requirements.

    The proposal matters: `/proposals/{id}/…` is addressed by proposal_id and
    resolves to the rfp internally, so a document with no proposal is
    unreachable through the API (GAP_ANALYSIS §1.2).
    """
    user_id = str(uuid.uuid4())
    rfp_id = str(uuid.uuid4())
    proposal_id = str(uuid.uuid4())
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
        "VALUES (%s, %s, 'h', 'RAG', 'Tester');",
        (user_id, f"rag_{uuid.uuid4().hex[:6]}@example.com"),
    )
    cur.execute(
        "INSERT INTO rfp_documents (rfp_id, uploaded_by, file_name, s3_storage_key, processing_status) "
        "VALUES (%s, %s, 'rfp.pdf', 'k', 'completed');",
        (rfp_id, user_id),
    )
    cur.execute(
        "INSERT INTO proposals (proposal_id, owned_by, rfp_id, title) "
        "VALUES (%s, %s, %s, 'RAG Test Proposal');",
        (proposal_id, user_id, rfp_id),
    )
    cur.executemany(
        "INSERT INTO extracted_requirements (rfp_id, section_number, raw_text_content, category) "
        "VALUES (%s, %s, %s, %s);",
        [
            (rfp_id, "C.3.1", "The contractor SHALL overhaul the pump.", "Technical"),
            (rfp_id, "H.2", "MFA is REQUIRED for privileged access.", "Security"),
        ],
    )
    conn.commit()
    cur.close()
    conn.close()
    yield {"user_id": user_id, "rfp_id": rfp_id, "proposal_id": proposal_id}
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))  # cascades
    conn.commit()
    cur.close()
    conn.close()


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def test_requirements_read_and_patch(test_client, proposal_with_requirements):
    proposal_id = proposal_with_requirements["proposal_id"]
    auth = _auth(proposal_with_requirements["user_id"])

    # unauthenticated -> 401
    assert test_client.get(f"/proposals/{proposal_id}/requirements").status_code == 401

    r = test_client.get(f"/proposals/{proposal_id}/requirements", headers=auth)
    assert r.status_code == 200
    reqs = r.json()
    assert len(reqs) == 2
    assert reqs[0]["category"] in {"technical", "security"}

    # PATCH compliance status persists
    rid = reqs[0]["id"]
    patched = test_client.patch(
        f"/requirements/{rid}", json={"complianceStatus": "addressed"}, headers=auth
    )
    assert patched.status_code == 200
    assert patched.json()["complianceStatus"] == "addressed"

    # cross-tenant read -> 404
    other = _auth(str(uuid.uuid4()))
    assert test_client.get(f"/proposals/{proposal_id}/requirements", headers=other).status_code == 404


def test_history_ingest_and_retrieval(monkeypatch, test_client, proposal_with_requirements):
    """Stubs embeddings (deterministic 768-dim) but runs real pgvector search."""
    from app.services import embeddings, history_service, retrieval

    def fake_embed_texts(texts):
        return [[0.001 * (i + 1)] * embeddings.EMBED_DIM for i, _ in enumerate(texts)]

    monkeypatch.setattr(history_service, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(retrieval, "embed_query", lambda t: [0.001] * embeddings.EMBED_DIM)

    user_id = proposal_with_requirements["user_id"]
    auth = _auth(user_id)

    ingest = test_client.post(
        "/history",
        json={"sourceName": "USCG Pump 2024", "content": "We overhauled centrifugal pumps for the USCG. " * 60},
        headers=auth,
    )
    assert ingest.status_code == 201
    assert ingest.json()["chunks"] >= 1

    sources = test_client.get("/history", headers=auth)
    assert sources.status_code == 200
    assert sources.json()[0]["sourceName"] == "USCG Pump 2024"

    hits = retrieval.search_similar(user_id, "pump overhaul experience", top_k=3)
    assert len(hits) >= 1
    assert hits[0]["source_name"] == "USCG Pump 2024"


def test_generate_section_uses_draft_writer(monkeypatch, test_client, proposal_with_requirements):
    """Stubs the RAG draft writer; verifies section create + persist."""
    from app.api.v1 import workspace as wsapi

    monkeypatch.setattr(
        wsapi.draft_writer,
        "generate_draft",
        lambda uid, text, top_k=5: {"content": "Our proven approach…", "citations": []},
    )

    proposal_id = proposal_with_requirements["proposal_id"]
    auth = _auth(proposal_with_requirements["user_id"])
    req_id = test_client.get(f"/proposals/{proposal_id}/requirements", headers=auth).json()[0]["id"]

    gen = test_client.post(
        f"/proposals/{proposal_id}/sections/generate",
        json={"requirementId": req_id},
        headers=auth,
    )
    assert gen.status_code == 201
    assert gen.json()["content"] == "Our proven approach…"

    sections = test_client.get(f"/proposals/{proposal_id}/sections", headers=auth)
    assert sections.status_code == 200
    assert len(sections.json()) == 1


def test_two_proposals_on_one_rfp_keep_separate_sections(
    monkeypatch, test_client, proposal_with_requirements
):
    """Sections must not leak between proposals answering the same RFP.

    They were keyed on rfp_id, so a second bid on the same solicitation saw —
    and could edit — the first one's drafts, with nothing in the UI to suggest
    the content was shared. Silent by nature: every response is a well-formed
    200 and the sections look like they belong. Only a test that builds the
    second proposal catches it.
    """
    from app.api.v1 import workspace as wsapi

    monkeypatch.setattr(
        wsapi.draft_writer,
        "generate_draft",
        lambda uid, text, top_k=5: {"content": "First bid's approach.", "citations": []},
    )

    user_id = proposal_with_requirements["user_id"]
    rfp_id = proposal_with_requirements["rfp_id"]
    first = proposal_with_requirements["proposal_id"]
    auth = _auth(user_id)

    # A second proposal answering the *same* RFP — a re-bid, or a variant.
    second = str(uuid.uuid4())
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO proposals (proposal_id, owned_by, rfp_id, title) "
            "VALUES (%s, %s, %s, 'Second Bid, Same RFP');",
            (second, user_id, rfp_id),
        )
    conn.close()

    req_id = test_client.get(f"/proposals/{first}/requirements", headers=auth).json()[0]["id"]
    created = test_client.post(
        f"/proposals/{first}/sections/generate", json={"requirementId": req_id}, headers=auth
    )
    assert created.status_code == 201
    assert created.json()["proposalId"] == first

    # Both proposals share the RFP's requirements...
    assert len(test_client.get(f"/proposals/{second}/requirements", headers=auth).json()) == 2
    # ...but the draft belongs to the first one alone.
    assert test_client.get(f"/proposals/{first}/sections", headers=auth).json() != []
    assert test_client.get(f"/proposals/{second}/sections", headers=auth).json() == []


def test_queueing_a_draft_marks_only_that_proposal(
    monkeypatch, test_client, proposal_with_requirements
):
    """POST /proposals/{id}/draft reports on the proposal, not the document.

    The route sets 'drafting' itself rather than leaving it to the worker: a
    client that polls immediately after the 202 would otherwise read whatever
    the previous run left behind and conclude the draft was already done.
    """
    from app.api.v1 import workspace as wsapi

    queued: list[tuple] = []
    monkeypatch.setattr(
        wsapi.celery_app, "send_task", lambda name, args=None, **kw: queued.append((name, args))
    )

    user_id = proposal_with_requirements["user_id"]
    rfp_id = proposal_with_requirements["rfp_id"]
    first = proposal_with_requirements["proposal_id"]
    auth = _auth(user_id)

    second = str(uuid.uuid4())
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO proposals (proposal_id, owned_by, rfp_id, title) "
            "VALUES (%s, %s, %s, 'Competing Bid');",
            (second, user_id, rfp_id),
        )
    conn.close()

    resp = test_client.post(f"/proposals/{first}/draft", headers=auth)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["draftingStatus"] == "drafting"
    assert body["proposalId"] == first
    assert queued == [("draft_proposal", [first])]

    assert test_client.get(f"/proposals/{first}", headers=auth).json()["draftingStatus"] == "drafting"
    # The competing bid is untouched, and so is the document behind both.
    assert test_client.get(f"/proposals/{second}", headers=auth).json()["draftingStatus"] == "idle"
    doc = test_client.get(f"/documents/{rfp_id}", headers=auth).json()
    assert doc["processingStatus"] == "completed"


def test_drafting_a_proposal_with_no_requirements_is_a_409(
    monkeypatch, test_client, proposal_with_requirements
):
    """Drafting is grounded in the extracted matrix, so an un-ingested RFP is a
    conflict rather than a queued job that would fail minutes later."""
    from app.api.v1 import workspace as wsapi

    monkeypatch.setattr(wsapi.celery_app, "send_task", lambda *a, **kw: None)

    user_id = proposal_with_requirements["user_id"]
    rfp_id = proposal_with_requirements["rfp_id"]
    proposal_id = proposal_with_requirements["proposal_id"]
    auth = _auth(user_id)

    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM extracted_requirements WHERE rfp_id = %s;", (rfp_id,))
    conn.close()

    resp = test_client.post(f"/proposals/{proposal_id}/draft", headers=auth)
    assert resp.status_code == 409
    # And nothing was left claiming to be in progress.
    assert test_client.get(f"/proposals/{proposal_id}", headers=auth).json()["draftingStatus"] == "idle"
