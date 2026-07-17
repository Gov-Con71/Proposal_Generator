"""Auth flow integration test — register → login → me, plus guard checks.

Requires a reachable Postgres with the init schema (same as the other DB tests).
"""

import uuid

import psycopg2
import pytest

from app.core.config import settings


@pytest.fixture
def cleanup_emails():
    """Deletes any users created during a test by collected email.

    Deleting the user cascades to their refresh_tokens, proposals and profile.
    """
    created: list[str] = []
    yield created
    if created:
        conn = psycopg2.connect(settings.database_url)
        cur = conn.cursor()
        cur.executemany("DELETE FROM users WHERE email = %s;", [(e,) for e in created])
        conn.commit()
        cur.close()
        conn.close()


@pytest.fixture
def cleanup_companies():
    """Deletes companies created during a test.

    Companies deliberately outlive their members (ON DELETE SET NULL), so
    deleting the user does not remove them — without this the table accumulates
    an orphan per test run.
    """
    created: list[str] = []
    yield created
    if created:
        conn = psycopg2.connect(settings.database_url)
        cur = conn.cursor()
        cur.executemany(
            "DELETE FROM companies WHERE LOWER(name) = LOWER(%s);", [(c,) for c in created]
        )
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


def _register(test_client, email, **extra):
    payload = {
        "email": email,
        "password": "s3cret!",
        "firstName": "Ada",
        "lastName": "Lovelace",
        **extra,
    }
    res = test_client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_refresh_token_rotates_and_detects_reuse(test_client, cleanup_emails):
    """Each refresh consumes the old token; replaying one kills the family."""
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    session = _register(test_client, email)

    first = session["refreshToken"]
    # A refresh token must be opaque, not a JWT — it has to be revocable.
    assert first.count(".") != 2

    # --- rotation ---
    r1 = test_client.post("/auth/refresh", json={"refreshToken": first})
    assert r1.status_code == 200, r1.text
    second = r1.json()["refreshToken"]
    assert second != first
    assert r1.json()["accessToken"]

    # the rotated token keeps working
    r2 = test_client.post("/auth/refresh", json={"refreshToken": second})
    assert r2.status_code == 200
    third = r2.json()["refreshToken"]

    # --- reuse detection: replaying a consumed token is rejected ---
    replay = test_client.post("/auth/refresh", json={"refreshToken": first})
    assert replay.status_code == 401

    # ...and the whole family is revoked, so the live token dies too.
    assert test_client.post("/auth/refresh", json={"refreshToken": third}).status_code == 401

    # garbage is rejected without side effects
    assert test_client.post("/auth/refresh", json={"refreshToken": "nope"}).status_code == 401


def test_logout_revokes_refresh_token(test_client, cleanup_emails):
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    session = _register(test_client, email)
    token = session["refreshToken"]

    assert test_client.post("/auth/logout", json={"refreshToken": token}).status_code == 200
    # Revoked: it can no longer be exchanged for a session.
    assert test_client.post("/auth/refresh", json={"refreshToken": token}).status_code == 401


def test_register_joins_company_and_defaults_to_analyst(
    test_client, cleanup_emails, cleanup_companies
):
    """Organization on the register form persists, and two users signing up under
    the same name land in the same company."""
    org = f"Acro {uuid.uuid4().hex[:6]}"
    cleanup_companies.append(org)
    a = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    b = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.extend([a, b])

    ua = _register(test_client, a, company=org)["user"]
    ub = _register(test_client, b, company=org.lower())["user"]  # case-insensitive

    assert ua["role"] == "analyst"          # was hardcoded before Sprint 7
    assert ua["companyId"]                  # was always "" before Sprint 7
    assert ua["companyId"] == ub["companyId"]


def test_login_is_rate_limited_after_repeated_failures(test_client, cleanup_emails, monkeypatch):
    """Unlimited password guessing was possible: 20 rapid wrong passwords all
    returned a plain 401 with no throttling."""
    from app.core.config import settings as cfg

    monkeypatch.setattr(cfg, "login_max_failures_per_account", 3)
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    _register(test_client, email)

    for _ in range(3):
        assert test_client.post(
            "/auth/login", json={"email": email, "password": "wrong"}
        ).status_code == 401

    # Budget spent — further attempts are refused before bcrypt even runs.
    blocked = test_client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0

    # The real password is refused too while the window is open: an attacker who
    # eventually guesses right must not be let in.
    assert test_client.post(
        "/auth/login", json={"email": email, "password": "s3cret!"}
    ).status_code == 429


def test_successful_login_clears_the_failure_budget(test_client, cleanup_emails, monkeypatch):
    """Only failures count, so a user who fumbles their password then gets it
    right is not throttled on their next attempt."""
    from app.core.config import settings as cfg

    monkeypatch.setattr(cfg, "login_max_failures_per_account", 3)
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    _register(test_client, email)

    for _ in range(2):  # two fumbles, one short of the limit
        assert test_client.post(
            "/auth/login", json={"email": email, "password": "wrong"}
        ).status_code == 401

    assert test_client.post(
        "/auth/login", json={"email": email, "password": "s3cret!"}
    ).status_code == 200

    # The budget reset, so the next fumble starts from zero rather than tripping.
    assert test_client.post(
        "/auth/login", json={"email": email, "password": "wrong"}
    ).status_code == 401


def test_rate_limiting_cannot_lock_a_victim_out(test_client, cleanup_emails, monkeypatch):
    """Per-account throttling must not become a denial-of-service: an attacker
    burning one account's budget must not affect a different account."""
    from app.core.config import settings as cfg

    monkeypatch.setattr(cfg, "login_max_failures_per_account", 3)
    victim = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    bystander = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.extend([victim, bystander])
    _register(test_client, victim)
    _register(test_client, bystander)

    for _ in range(4):  # attacker exhausts the victim's budget
        test_client.post("/auth/login", json={"email": victim, "password": "wrong"})
    assert test_client.post(
        "/auth/login", json={"email": victim, "password": "s3cret!"}
    ).status_code == 429

    # The bystander is untouched — buckets are per-account, not global.
    assert test_client.post(
        "/auth/login", json={"email": bystander, "password": "s3cret!"}
    ).status_code == 200


def test_viewer_role_is_read_only(test_client, cleanup_emails):
    """Roles are read from the database per request, so a demotion takes effect
    immediately rather than when the access token happens to expire."""
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    session = _register(test_client, email)
    headers = {"Authorization": f"Bearer {session['accessToken']}"}

    # As an analyst (the default), writing is allowed.
    assert test_client.put("/profile", json={"legalName": "Acro"}, headers=headers).status_code == 200

    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute("UPDATE users SET role = 'viewer' WHERE email = %s;", (email,))
    conn.commit()
    cur.close()
    conn.close()

    # Same token, no re-login: reads still work, writes are now forbidden.
    assert test_client.get("/proposals", headers=headers).status_code == 200
    assert test_client.put("/profile", json={"legalName": "X"}, headers=headers).status_code == 403
    assert test_client.post("/proposals", json={"title": "X"}, headers=headers).status_code == 403
