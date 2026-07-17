"""Sprint 5/6 — export pipeline integration test.

Exercises the real async export flow with real components, isolating only the
S3 backend (moto) and — in the failure case — the renderer:

    POST /exports              → validates proposal ownership, inserts a 'pending'
                                 export_jobs row (FK → proposals) + enqueues
    worker run_export_render   → 'generating' → resolve proposal → assemble the
                                 linked RFP's sections + compliance matrix →
                                 render bytes → upload to S3 (moto) → 'ready'
    GET  /exports/{id}         → poll status
    GET  /exports/{id}/download → stream the rendered artifact back from S3

Requirements to run:
  * a reachable Postgres with the init schema + sprint5/sprint6 migrations applied
  * `moto`, `fpdf2`, `openpyxl` installed (all in requirements.txt)

As in test_ingestion_pipeline, the Celery hop is split from the request: the
endpoint only enqueues, so we capture the enqueue and then drive
`run_export_render` ourselves (exactly what the worker process does), keeping the
test deterministic and broker-free.
"""

import io
import uuid
import zipfile

import psycopg2
import pytest
from moto import mock_aws

from app.core.config import settings
from app.core.security import create_access_token
from app.services import export_renderer, export_service


def _conn():
    return psycopg2.connect(settings.database_url)


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def _insert_rfp_with_content(cur, user_id: str) -> str:
    """Seeds an owned RFP + one section + one requirement; returns its rfp_id."""
    rfp_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO rfp_documents (rfp_id, uploaded_by, file_name, s3_storage_key, processing_status) "
        "VALUES (%s, %s, 'rfp.pdf', 'k', 'completed');",
        (rfp_id, user_id),
    )
    cur.execute(
        "INSERT INTO extracted_requirements (rfp_id, section_number, raw_text_content, category, compliance_status) "
        "VALUES (%s, 'C.3.1', 'The contractor SHALL overhaul the pump.', 'Technical', 'compliant');",
        (rfp_id,),
    )
    cur.execute(
        "INSERT INTO proposal_sections (rfp_id, section_title, generated_draft_content, status) "
        "VALUES (%s, 'Technical Approach', 'Our team will execute a full teardown of the pump.', 'draft');",
        (rfp_id,),
    )
    return rfp_id


def _insert_proposal(cur, user_id: str, rfp_id: str | None = None, title: str = "Pump Overhaul Bid") -> str:
    proposal_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO proposals (proposal_id, owned_by, rfp_id, title) VALUES (%s, %s, %s, %s);",
        (proposal_id, user_id, rfp_id, title),
    )
    return proposal_id


def _job_row(job_id: str) -> dict:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, error, s3_key, download_url FROM export_jobs WHERE job_id = %s;",
                (job_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return {"status": row[0], "error": row[1], "s3_key": row[2], "download_url": row[3]}


@pytest.fixture
def seeded_user():
    """Inserts a throwaway user; cleanup cascades to proposals + export_jobs."""
    user_id = str(uuid.uuid4())
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
        "VALUES (%s, %s, 'h', 'Export', 'Tester');",
        (user_id, f"export_{uuid.uuid4().hex[:6]}@example.com"),
    )
    conn.commit()
    yield user_id
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


@pytest.fixture
def other_user():
    """A second real tenant, for cross-tenant isolation checks."""
    user_id = str(uuid.uuid4())
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
        "VALUES (%s, %s, 'h', 'Other', 'Tenant');",
        (user_id, f"other_{uuid.uuid4().hex[:6]}@example.com"),
    )
    conn.commit()
    yield user_id
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


@pytest.fixture
def seeded_proposal(seeded_user):
    """A proposal linked to an owned RFP with one section + one requirement."""
    conn = _conn()
    with conn, conn.cursor() as cur:
        rfp_id = _insert_rfp_with_content(cur, seeded_user)
        proposal_id = _insert_proposal(cur, seeded_user, rfp_id)
    conn.close()
    return {"user_id": seeded_user, "proposal_id": proposal_id, "rfp_id": rfp_id}


@pytest.fixture
def capture_enqueue(monkeypatch):
    """Captures render_export enqueues instead of hitting Redis (worker driven manually)."""
    from app.api.v1 import exports as exports_mod

    enqueued: list[tuple[str, str]] = []
    monkeypatch.setattr(
        exports_mod.celery_app,
        "send_task",
        lambda name, args=None, **kw: enqueued.append((name, args[0])),
    )
    return enqueued


def _is_valid(fmt: str, body: bytes) -> bool:
    if fmt == "pdf":
        return body[:4] == b"%PDF"
    if fmt == "docx":
        return zipfile.is_zipfile(io.BytesIO(body)) and b"word/document.xml" in body
    return zipfile.is_zipfile(io.BytesIO(body))  # xlsx + zip are OOXML/ZIP containers


@mock_aws
def test_export_lifecycle_all_formats(test_client, seeded_proposal, capture_enqueue, monkeypatch):
    monkeypatch.setattr(settings, "use_localstack", False)  # route S3 to moto
    auth = _auth(seeded_proposal["user_id"])
    proposal_id = seeded_proposal["proposal_id"]

    # unauthenticated create is rejected
    assert test_client.post("/exports", json={"proposalId": proposal_id, "format": "pdf"}).status_code == 401

    for fmt in ["pdf", "docx", "xlsx", "zip"]:
        resp = test_client.post("/exports", json={"proposalId": proposal_id, "format": fmt}, headers=auth)
        assert resp.status_code == 202, resp.text
        job = resp.json()
        assert job["status"] == "pending"
        assert job["downloadUrl"] is None
        assert capture_enqueue[-1] == ("render_export", job["id"])

        # download before the worker runs -> 404
        assert test_client.get(f"/exports/{job['id']}/download", headers=auth).status_code == 404

        export_service.run_export_render(job["id"])  # run the worker's job

        polled = test_client.get(f"/exports/{job['id']}", headers=auth).json()
        assert polled["status"] == "ready"
        assert polled["downloadUrl"] == f"/exports/{job['id']}/download"

        dl = test_client.get(f"/exports/{job['id']}/download", headers=auth)
        assert dl.status_code == 200
        assert dl.headers["content-type"].startswith(export_renderer.MIME[fmt])
        assert _is_valid(fmt, dl.content), f"{fmt} artifact is malformed"


@mock_aws
def test_export_includes_real_proposal_content(test_client, seeded_proposal, capture_enqueue, monkeypatch):
    monkeypatch.setattr(settings, "use_localstack", False)
    auth = _auth(seeded_proposal["user_id"])

    job = test_client.post(
        "/exports", json={"proposalId": seeded_proposal["proposal_id"], "format": "zip"}, headers=auth
    ).json()
    export_service.run_export_render(job["id"])

    dl = test_client.get(f"/exports/{job['id']}/download", headers=auth)
    assert dl.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(dl.content))
    proposal_md = archive.read("proposal.md").decode()
    compliance_csv = archive.read("compliance.csv").decode()

    assert "Technical Approach" in proposal_md           # the linked RFP's section
    assert "teardown of the pump" in proposal_md          # its content
    assert "overhaul the pump" in compliance_csv          # the requirement row


@mock_aws
def test_export_of_unlinked_proposal_still_renders(test_client, seeded_user, capture_enqueue, monkeypatch):
    monkeypatch.setattr(settings, "use_localstack", False)
    auth = _auth(seeded_user)
    conn = _conn()
    with conn, conn.cursor() as cur:
        proposal_id = _insert_proposal(cur, seeded_user, rfp_id=None, title="Draft With No RFP")
    conn.close()

    job = test_client.post("/exports", json={"proposalId": proposal_id, "format": "pdf"}, headers=auth).json()
    export_service.run_export_render(job["id"])
    dl = test_client.get(f"/exports/{job['id']}/download", headers=auth)
    assert dl.status_code == 200
    assert dl.content[:4] == b"%PDF"  # a valid PDF even with no linked content


@mock_aws
def test_export_rejects_unknown_or_foreign_proposal(
    test_client, seeded_proposal, other_user, capture_enqueue, monkeypatch
):
    monkeypatch.setattr(settings, "use_localstack", False)
    auth = _auth(seeded_proposal["user_id"])

    # A well-formed id that doesn't exist -> 404.
    assert test_client.post("/exports", json={"proposalId": str(uuid.uuid4()), "format": "pdf"}, headers=auth).status_code == 404

    # A malformed id is invalid input, not a missing resource -> 422 from request
    # validation, consistent with every other route that takes a UUID.
    assert test_client.post("/exports", json={"proposalId": "not-a-uuid", "format": "pdf"}, headers=auth).status_code == 422

    # A real second tenant gets 404, not 403 — existence must not leak.
    other = _auth(other_user)
    assert test_client.post(
        "/exports", json={"proposalId": seeded_proposal["proposal_id"], "format": "pdf"}, headers=other
    ).status_code == 404


@mock_aws
def test_export_rejects_token_for_deleted_user(test_client, seeded_proposal, monkeypatch):
    """A well-formed token whose subject no longer exists is unauthenticated —
    it must not reach the tenant check (Sprint 7: roles load from the DB)."""
    monkeypatch.setattr(settings, "use_localstack", False)
    ghost = _auth(str(uuid.uuid4()))  # never inserted
    assert test_client.post(
        "/exports", json={"proposalId": seeded_proposal["proposal_id"], "format": "pdf"}, headers=ghost
    ).status_code == 401


def _boom(*_args, **_kwargs):
    raise RuntimeError("render exploded")


@mock_aws
def test_export_render_failure_marks_job_failed(test_client, seeded_proposal, capture_enqueue, monkeypatch):
    monkeypatch.setattr(settings, "use_localstack", False)
    auth = _auth(seeded_proposal["user_id"])
    job = test_client.post(
        "/exports", json={"proposalId": seeded_proposal["proposal_id"], "format": "pdf"}, headers=auth
    ).json()

    monkeypatch.setattr(export_service.export_renderer, "render", _boom)
    with pytest.raises(RuntimeError):
        export_service.run_export_render(job["id"])

    row = _job_row(job["id"])
    assert row["status"] == "failed"
    assert row["error"] == "render exploded"
    assert row["s3_key"] is None
    assert row["download_url"] is None

    polled = test_client.get(f"/exports/{job['id']}", headers=auth).json()
    assert polled["status"] == "failed"
    assert polled["downloadUrl"] is None
    assert test_client.get(f"/exports/{job['id']}/download", headers=auth).status_code == 404


@mock_aws
def test_export_tenant_isolation(test_client, seeded_proposal, capture_enqueue, monkeypatch):
    monkeypatch.setattr(settings, "use_localstack", False)
    auth = _auth(seeded_proposal["user_id"])
    job = test_client.post(
        "/exports", json={"proposalId": seeded_proposal["proposal_id"], "format": "pdf"}, headers=auth
    ).json()
    export_service.run_export_render(job["id"])

    # a different tenant cannot see or download the job
    other = _auth(str(uuid.uuid4()))
    assert test_client.get(f"/exports/{job['id']}", headers=other).status_code == 404
    assert test_client.get(f"/exports/{job['id']}/download", headers=other).status_code == 404

    # a malformed (non-UUID) id is a clean 404, not a 500
    assert test_client.get("/exports/not-a-uuid", headers=auth).status_code == 404
    assert test_client.get(f"/exports/{uuid.uuid4()}", headers=auth).status_code == 404
