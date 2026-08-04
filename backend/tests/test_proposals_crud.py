"""Sprint 6 — proposals CRUD integration test.

Real Postgres; exercises the DB-backed proposal endpoints that replaced the
Story 1.3 mock router:

    GET    /proposals            → the tenant's proposals
    POST   /proposals            → create (optionally linked to an owned RFP)
    GET    /proposals/{id}        → detail, with compliance derived from the RFP
    PATCH  /proposals/{id}        → partial update
    DELETE /proposals/{id}        → remove

Requirements to run:
  * a reachable Postgres with the init schema + sprint6_proposals.sql applied

Every route is tenant-scoped by proposals.owned_by; linking a proposal to an RFP
is validated against rfp_documents ownership so a tenant can never attach — or
read compliance counts from — another tenant's RFP.
"""

import uuid

import psycopg2
import pytest

from app.core.config import settings
from app.core.security import create_access_token


def _conn():
    return psycopg2.connect(settings.database_url)


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def _insert_user(cur) -> str:
    user_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
        "VALUES (%s, %s, 'h', 'Proposal', 'Tester');",
        (user_id, f"proposals_{uuid.uuid4().hex[:6]}@example.com"),
    )
    return user_id


@pytest.fixture
def seeded_user():
    conn = _conn()
    cur = conn.cursor()
    user_id = _insert_user(cur)
    conn.commit()
    yield user_id
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))  # cascades proposals
    conn.commit()
    cur.close()
    conn.close()


@pytest.fixture
def rfp_with_mixed_compliance(seeded_user):
    """An owned RFP with 3 requirements (compliant / exception / pending)."""
    rfp_id = str(uuid.uuid4())
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rfp_documents (rfp_id, uploaded_by, file_name, s3_storage_key, processing_status) "
            "VALUES (%s, %s, 'rfp.pdf', 'k', 'completed');",
            (rfp_id, seeded_user),
        )
        cur.executemany(
            "INSERT INTO extracted_requirements (rfp_id, section_number, raw_text_content, category, compliance_status) "
            "VALUES (%s, %s, %s, %s, %s);",
            [
                (rfp_id, "C.1", "SHALL overhaul the pump.", "Technical", "compliant"),
                (rfp_id, "C.2", "SHALL provide test reports.", "Testing", "exception"),
                (rfp_id, "C.3", "SHALL mark all parts.", "Marking", "pending"),
            ],
        )
    conn.close()
    return {"user_id": seeded_user, "rfp_id": rfp_id}


def test_create_list_get_roundtrip(test_client, seeded_user):
    auth = _auth(seeded_user)

    # unauthenticated create -> 401
    assert test_client.post("/proposals", json={"title": "x"}).status_code == 401

    created = test_client.post(
        "/proposals",
        json={
            "title": "Centrifugal Pump Overhaul",
            "agency": "US Coast Guard",
            "solicitationNumber": "NSN-4320",
            "draftingLevel": "technical",
            "pageLimit": 30,
        },
        headers=auth,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    pid = body["id"]
    assert body["title"] == "Centrifugal Pump Overhaul"
    assert body["status"] == "draft"          # server default
    assert body["pageLimit"] == 30
    assert body["documentId"] == ""            # no RFP linked

    # it shows up in the tenant's list
    listing = test_client.get("/proposals", headers=auth).json()
    assert [p["id"] for p in listing] == [pid]

    # detail round-trips
    detail = test_client.get(f"/proposals/{pid}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["agency"] == "US Coast Guard"

    # unknown id -> 404
    assert test_client.get(f"/proposals/{uuid.uuid4()}", headers=auth).status_code == 404


def test_create_links_rfp_and_derives_compliance(test_client, rfp_with_mixed_compliance):
    auth = _auth(rfp_with_mixed_compliance["user_id"])
    rfp_id = rfp_with_mixed_compliance["rfp_id"]

    created = test_client.post(
        "/proposals",
        json={"title": "Linked Bid", "documentId": rfp_id},
        headers=auth,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["documentId"] == rfp_id

    # counts derived live from extracted_requirements (compliant→addressed,
    # exception→partial, pending→missing)
    assert body["totalRequirements"] == 3
    assert body["addressedRequirements"] == 1
    assert body["partialRequirements"] == 1
    assert body["missingRequirements"] == 1
    # score = 100*(1 + 0.5*1)/3 ≈ 50
    assert body["complianceScore"] == 50


def test_update_and_delete(test_client, seeded_user):
    auth = _auth(seeded_user)
    pid = test_client.post("/proposals", json={"title": "Draft Bid"}, headers=auth).json()["id"]

    patched = test_client.patch(
        f"/proposals/{pid}", json={"status": "submitted", "tone": "formal", "title": "Final Bid"}, headers=auth
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "submitted"
    assert patched.json()["tone"] == "formal"
    assert patched.json()["title"] == "Final Bid"

    # partial patch leaves other fields intact
    again = test_client.patch(f"/proposals/{pid}", json={"agency": "EPA"}, headers=auth).json()
    assert again["agency"] == "EPA"
    assert again["title"] == "Final Bid"
    assert again["status"] == "submitted"

    assert test_client.delete(f"/proposals/{pid}", headers=auth).status_code == 204
    assert test_client.get(f"/proposals/{pid}", headers=auth).status_code == 404
    assert test_client.delete(f"/proposals/{pid}", headers=auth).status_code == 404  # already gone


def test_integrity_checklist_derived_from_real_data(
    test_client, rfp_with_mixed_compliance, other_tenant
):
    auth = _auth(rfp_with_mixed_compliance["user_id"])
    rfp_id = rfp_with_mixed_compliance["rfp_id"]

    # unlinked proposal → everything 'missing'
    bare = test_client.post("/proposals", json={"title": "Bare"}, headers=auth).json()["id"]
    bare_items = test_client.get(f"/proposals/{bare}/integrity", headers=auth)
    assert bare_items.status_code == 200
    assert {i["id"] for i in bare_items.json()} == {
        "req-extracted", "req-addressed", "sections-drafted", "sections-approved", "compliance-score",
    }
    assert all(i["status"] == "missing" for i in bare_items.json())

    # linked proposal (3 reqs: compliant/exception/pending, no sections)
    linked = test_client.post("/proposals", json={"title": "Linked", "documentId": rfp_id}, headers=auth).json()["id"]
    items = {i["id"]: i["status"] for i in test_client.get(f"/proposals/{linked}/integrity", headers=auth).json()}
    assert items["req-extracted"] == "verified"        # 3 requirements exist
    assert items["req-addressed"] == "missing"          # one is 'pending' → missing
    assert items["sections-drafted"] == "missing"       # no sections yet
    assert items["sections-approved"] == "missing"
    assert items["compliance-score"] == "missing"       # score 50 < 70

    # another tenant cannot read it
    assert test_client.get(f"/proposals/{linked}/integrity", headers=_auth(other_tenant)).status_code == 404


def test_tenant_isolation_and_foreign_rfp_link(test_client, rfp_with_mixed_compliance):
    owner_auth = _auth(rfp_with_mixed_compliance["user_id"])
    owner_rfp = rfp_with_mixed_compliance["rfp_id"]
    pid = test_client.post("/proposals", json={"title": "Owner Bid"}, headers=owner_auth).json()["id"]

    # a second, unrelated tenant
    conn = _conn()
    cur = conn.cursor()
    other_id = _insert_user(cur)
    conn.commit()
    cur.close()
    conn.close()
    try:
        other = _auth(other_id)

        # other tenant sees an empty list and cannot read/patch/delete the owner's proposal
        assert test_client.get("/proposals", headers=other).json() == []
        assert test_client.get(f"/proposals/{pid}", headers=other).status_code == 404
        assert test_client.patch(f"/proposals/{pid}", json={"title": "hijack"}, headers=other).status_code == 404
        assert test_client.delete(f"/proposals/{pid}", headers=other).status_code == 404

        # other tenant cannot link the owner's RFP (cross-tenant link -> 400)
        assert test_client.post(
            "/proposals", json={"title": "Bad Link", "documentId": owner_rfp}, headers=other
        ).status_code == 400

        # a non-UUID documentId is rejected too
        assert test_client.post(
            "/proposals", json={"title": "Bad Link", "documentId": "not-a-uuid"}, headers=other
        ).status_code == 400
    finally:
        conn = _conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE user_id = %s;", (other_id,))
        conn.commit()
        cur.close()
        conn.close()
