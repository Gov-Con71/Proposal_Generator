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
from app.services.solicitation_extractor import (
    Administrative,
    Citation,
    Deadlines,
    SolicitationSummary,
    SubmissionMethod,
    SubmissionRequirements,
    TechnicalCore,
)


def _null_summary() -> SolicitationSummary:
    """A minimal all-null summary for stubbing the supplementary extraction."""
    c = lambda: Citation(value=None, source_quote=None)
    return SolicitationSummary(
        administrative=Administrative(
            solicitation_number=c(), agency_or_organization=c(),
            title_of_opportunity=c(), naics_code=c(), set_aside_type=c(),
        ),
        deadlines=Deadlines(
            questions_due_date=c(), proposal_due_date=c(), period_of_performance=c()
        ),
        submission_requirements=SubmissionRequirements(
            submission_method=SubmissionMethod(value=None, description=None, source_quote=None),
            page_limits=[], required_volumes_or_sections=[],
        ),
        technical_core=TechnicalCore(primary_objective=c(), key_deliverables=[]),
        evaluation_factors=[], instructions_to_offerors=[],
    )


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


def _fetch_summary(rfp_id: str):
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute("SELECT solicitation_summary FROM rfp_documents WHERE rfp_id = %s;", (rfp_id,))
    (summary,) = cur.fetchone()
    cur.close()
    conn.close()
    return summary  # psycopg2 decodes JSONB to dict (or None)


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

    # Isolate the supplementary solicitation-summary LLM call too (deterministic,
    # no live provider); the pipeline should persist whatever it returns.
    async def fake_solicitation(_markdown: str) -> SolicitationSummary:
        return _null_summary()

    monkeypatch.setattr(ingestion, "run_solicitation_extraction", fake_solicitation)

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

    # --- Sprint 8: the solicitation summary was extracted and stored as JSONB ---
    summary = _fetch_summary(rfp_id)
    assert summary is not None
    assert set(summary) == {
        "administrative",
        "deadlines",
        "submission_requirements",
        "technical_core",
        "evaluation_factors",
        "instructions_to_offerors",
    }

    # --- Sprint 8: the summary is readable via the API in its snake_case schema ---
    sum_resp = test_client.get(f"/documents/{rfp_id}/summary", headers=auth)
    assert sum_resp.status_code == 200, sum_resp.text
    body = sum_resp.json()
    assert set(body) == {
        "administrative",
        "deadlines",
        "submission_requirements",
        "technical_core",
        "evaluation_factors",
        "instructions_to_offerors",
    }
    # snake_case citation shape is preserved verbatim (not camelCased)
    assert body["administrative"]["solicitation_number"] == {"value": None, "source_quote": None}
    # unknown / cross-tenant document is a 404, not a leak
    assert test_client.get(f"/documents/{uuid.uuid4()}/summary", headers=auth).status_code == 404

    # --- Re-analyze replaces the matrix instead of duplicating it (bug #1) ---
    count_again = ingestion.run_ingestion_sync(rfp_id)
    assert count_again == 2
    assert _count_requirements(rfp_id) == 2  # still 2 total, not 4
