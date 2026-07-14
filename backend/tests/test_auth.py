"""Auth flow integration test — register → login → me, plus guard checks.

Requires a reachable Postgres with the init schema (same as the other DB tests).
"""

import uuid

import psycopg2
import pytest

from app.core.config import settings


@pytest.fixture
def cleanup_emails():
    """Deletes any users created during a test by collected email."""
    created: list[str] = []
    yield created
    if created:
        conn = psycopg2.connect(settings.database_url)
        cur = conn.cursor()
        cur.executemany("DELETE FROM users WHERE email = %s;", [(e,) for e in created])
        conn.commit()
        cur.close()
        conn.close()


def test_register_login_me_flow(test_client, cleanup_emails):
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)

    # --- register ---
    reg = test_client.post(
        "/auth/register",
        json={"email": email, "password": "s3cret!", "firstName": "Ada", "lastName": "Lovelace"},
    )
    assert reg.status_code == 201, reg.text
    session = reg.json()
    assert session["accessToken"]
    assert session["user"]["email"] == email
    assert session["user"]["name"] == "Ada Lovelace"

    # duplicate email is rejected
    dup = test_client.post(
        "/auth/register",
        json={"email": email, "password": "x", "firstName": "Ada", "lastName": "L"},
    )
    assert dup.status_code == 409

    # --- login ---
    login = test_client.post("/auth/login", json={"email": email, "password": "s3cret!"})
    assert login.status_code == 200, login.text
    token = login.json()["accessToken"]

    # wrong password rejected
    assert test_client.post(
        "/auth/login", json={"email": email, "password": "nope"}
    ).status_code == 401

    # --- me (protected) ---
    me = test_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email

    # missing / bad token rejected
    assert test_client.get("/auth/me").status_code == 401
    assert test_client.get(
        "/auth/me", headers={"Authorization": "Bearer garbage"}
    ).status_code == 401
