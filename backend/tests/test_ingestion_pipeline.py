"""Sprint 2.6 — end-to-end ingestion pipeline integration test.

Exercises the real flow with real components, isolating only the external LLM:

    POST /documents/upload  → streams file into S3 (moto) + inserts rfp_documents row
    worker run_ingestion    → S3 download → real Markdown parse → (stubbed) extract
                              → inserts extracted_requirements rows → status 'completed'

Requirements to run:
  * a reachable Postgres (same as test_proposals.py) with the init schema applied
  * `moto` and `markitdown` installed (in requirements.txt)

The Celery hop is split from the request on purpose: the endpoint only enqueues,
so we capture the enqueue and then drive `run_ingestion_sync` ourselves (exactly
what the worker process does), keeping the test deterministic and broker-free.
"""

import uuid

import psycopg2
import pytest
from moto import mock_aws

from app.core.config import settings
from app.core.security import create_access_token
from app.services import ingestion
from app.services.compliance_extractor import ComplianceMatrix, ExtractedRequirement


@pytest.fixture
def seeded_user():
    """Inserts a throwaway user (FK target for uploads) and cleans it up after."""
    user_id = str(uuid.uuid4())
    email = f"ingest_{uuid.uuid4().hex[:6]}@example.com"
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
        "VALUES (%s, %s, 'hash', 'Ingest', 'Tester');",
        (user_id, email),
    )
    conn.commit()
    yield user_id
    # Cascades to rfp_documents + extracted_requirements
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def _count_requirements(rfp_id: str) -> int:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM extracted_requirements WHERE rfp_id = %s;", (rfp_id,))
    (count,) = cur.fetchone()
    cur.close()
    conn.close()
    return count


@mock_aws
def test_upload_to_requirements_end_to_end(test_client, seeded_user, monkeypatch):
    # Use the moto-intercepted default boto3 client rather than LocalStack.
    monkeypatch.setattr(settings, "use_localstack", False)

    # Isolate the external LLM: return a fixed compliance matrix.
    async def fake_extract(_markdown: str) -> ComplianceMatrix:
        return ComplianceMatrix(
            requirements=[
                ExtractedRequirement(
                    section_number="C.3.1",
                    raw_text_content="The contractor SHALL deliver widgets.",
                    category="Technical",
                ),
                ExtractedRequirement(
                    section_number="H.2",
                    raw_text_content="MFA is REQUIRED for all privileged access.",
                    category="Security",
                ),
            ]
        )

    monkeypatch.setattr(ingestion, "run_extraction", fake_extract)

    # Capture the enqueue instead of hitting Redis; we drive the worker below.
    from app.api.v1 import documents as documents_mod

    enqueued: list[str] = []
    monkeypatch.setattr(
        documents_mod.celery_app,
        "send_task",
        lambda name, args=None, **kw: enqueued.append(args[0]),
    )

    # Tenancy comes from the JWT, not the request body (Story 4.2).
    token, _ = create_access_token(seeded_user)
    auth = {"Authorization": f"Bearer {token}"}

    # unauthenticated uploads are rejected
    assert test_client.post(
        "/documents/upload",
        files={"file": ("rfp.txt", b"x", "text/plain")},
    ).status_code == 401

    # --- Story 2.2: upload streams to S3 and creates the pending row ---
    payload = b"Section C.3.1 The contractor SHALL deliver widgets.\nSection H.2 MFA REQUIRED."
    resp = test_client.post(
        "/documents/upload",
        files={"file": ("rfp.txt", payload, "text/plain")},
        headers=auth,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    rfp_id = body["rfpId"]
    assert body["sizeBytes"] == len(payload)
    assert body["processingStatus"] == "pending"
    assert body["s3Key"].startswith(f"uploads/{seeded_user}/")
    assert enqueued == [rfp_id]

    # --- Story 2.5: run the worker's job (own thread/loop, as in production) ---
    count = ingestion.run_ingestion_sync(rfp_id)
    assert count == 2

    # --- rows landed + status advanced ---
    assert _count_requirements(rfp_id) == 2
    status_resp = test_client.get(f"/documents/{rfp_id}", headers=auth)
    assert status_resp.status_code == 200
    assert status_resp.json()["processingStatus"] == "completed"
    assert status_resp.json()["requirementsCount"] == 2
