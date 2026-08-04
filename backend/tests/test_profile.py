"""Sprint 5 — company-profile persistence integration test.

Real Postgres; exercises the DB-backed profile endpoints end to end:

    GET /profile  → the tenant's stored profile, or an empty default if none
    PUT /profile  → merge a partial update (JSONB list/object fields) and persist

Requirements to run:
  * a reachable Postgres with the init schema + sprint5_profile_exports.sql applied

Reads never mutate, so a fresh tenant sees an empty default; saves upsert and are
read back from the DB (each request opens its own connection — real persistence,
not in-process state).
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


@pytest.fixture
def seeded_user():
    """Inserts a throwaway user (FK target for company_profiles); cleans up after."""
    user_id = str(uuid.uuid4())
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
        "VALUES (%s, %s, 'h', 'Profile', 'Tester');",
        (user_id, f"profile_{uuid.uuid4().hex[:6]}@example.com"),
    )
    conn.commit()
    yield user_id
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))  # cascades company_profiles
    conn.commit()
    cur.close()
    conn.close()


def _profile_row_count(user_id: str) -> int:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM company_profiles WHERE user_id = %s;", (user_id,))
            (count,) = cur.fetchone()
    finally:
        conn.close()
    return count


def test_profile_default_is_empty_and_reads_do_not_persist(test_client, seeded_user):
    # unauthenticated -> 401
    assert test_client.get("/profile").status_code == 401

    resp = test_client.get("/profile", headers=_auth(seeded_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == seeded_user
    assert body["legalName"] == ""
    assert body["certifications"] == []
    assert body["pastPerformance"] == []

    # a GET must not create a row
    assert _profile_row_count(seeded_user) == 0


def test_profile_save_and_readback_roundtrips_jsonb(test_client, seeded_user):
    auth = _auth(seeded_user)
    payload = {
        "legalName": "Acme Federal LLC",
        "fringeRate": 31.5,
        "annualRevenue": 4200000,
        "socioEconomicStatus": ["SDVOSB", "HUBZone"],
        "certifications": ["ISO 9001", "CMMI-3"],
        "pastPerformance": [
            {
                "id": "pp1",
                "contractNumber": "N00024-23-C-0001",
                "agency": "US Coast Guard",
                "value": 1200000,
                "scope": "Centrifugal pump overhaul",
                "period": "2023-2024",
            }
        ],
    }
    saved = test_client.put("/profile", json=payload, headers=auth)
    assert saved.status_code == 200, saved.text
    assert saved.json()["legalName"] == "Acme Federal LLC"

    # exactly one row persisted
    assert _profile_row_count(seeded_user) == 1

    # read back from the DB (fresh connection inside the request)
    got = test_client.get("/profile", headers=auth).json()
    assert got["legalName"] == "Acme Federal LLC"
    assert got["fringeRate"] == 31.5
    assert got["annualRevenue"] == 4200000
    assert got["socioEconomicStatus"] == ["SDVOSB", "HUBZone"]
    assert got["certifications"] == ["ISO 9001", "CMMI-3"]
    assert len(got["pastPerformance"]) == 1
    assert got["pastPerformance"][0]["agency"] == "US Coast Guard"
    assert got["pastPerformance"][0]["contractNumber"] == "N00024-23-C-0001"


def test_profile_partial_update_preserves_other_fields(test_client, seeded_user):
    auth = _auth(seeded_user)
    test_client.put(
        "/profile",
        json={
            "legalName": "Acme Federal LLC",
            "certifications": ["ISO 9001"],
            "pastPerformance": [
                {"id": "pp1", "contractNumber": "N001", "agency": "EPA",
                 "value": 500000, "scope": "Remediation", "period": "2022"}
            ],
        },
        headers=auth,
    )

    # a subsequent partial PUT must not clobber unrelated fields
    merged = test_client.put("/profile", json={"cageCode": "1ABC2"}, headers=auth).json()
    assert merged["cageCode"] == "1ABC2"
    assert merged["legalName"] == "Acme Federal LLC"
    assert merged["certifications"] == ["ISO 9001"]
    assert len(merged["pastPerformance"]) == 1
    assert merged["pastPerformance"][0]["agency"] == "EPA"

    # still exactly one row (upsert, not insert)
    assert _profile_row_count(seeded_user) == 1


def test_profile_is_tenant_isolated(test_client, seeded_user, other_tenant):
    # tenant A saves a profile
    test_client.put("/profile", json={"legalName": "Acme Federal LLC"}, headers=_auth(seeded_user))

    # a different tenant sees only their own empty default, never A's data
    other = _auth(other_tenant)
    body = test_client.get("/profile", headers=other).json()
    assert body["legalName"] == ""
    assert body["id"] != seeded_user
