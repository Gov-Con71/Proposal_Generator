"""Auth flow integration test — register → login → me, plus guard checks.

Requires a reachable Postgres with the init schema (same as the other DB tests).
"""

import uuid

import psycopg2
import pytest

from app.core.config import settings

# Satisfies the Sprint 9 password policy: long, and sharing no 4+ character
# run with the generated "auth_..." emails or the "Ada Lovelace" name the
# helpers below register with.
VALID_PASSWORD = "trombone-marmalade-97"
REFRESH_COOKIE = settings.refresh_cookie_name


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
        json={"email": email, "password": VALID_PASSWORD, "firstName": "Ada", "lastName": "Lovelace"},
    )
    assert reg.status_code == 201, reg.text
    session = reg.json()
    assert session["accessToken"]
    assert session["user"]["email"] == email
    assert session["user"]["name"] == "Ada Lovelace"

    # duplicate email is rejected
    dup = test_client.post(
        "/auth/register",
        json={"email": email, "password": VALID_PASSWORD, "firstName": "Ada", "lastName": "L"},
    )
    assert dup.status_code == 409

    # --- login ---
    login = test_client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
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
        "password": VALID_PASSWORD,
        "firstName": "Ada",
        "lastName": "Lovelace",
        **extra,
    }
    res = test_client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _cookie_from(response) -> str | None:
    """The raw refresh token *this response* set.

    Read from the response rather than the client's jar: a test that replays an
    old token has to put it in the jar by hand, and a hand-set cookie and a
    server-set one differ by domain, so both linger and httpx refuses to say
    which is "the" cookie.
    """
    return response.cookies.get(REFRESH_COOKIE)


def _refresh_with(test_client, raw: str | None):
    """POSTs /auth/refresh presenting `raw` as the cookie."""
    test_client.cookies.clear()
    return test_client.post(
        "/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={raw}"}
    )


def test_refresh_token_rotates_and_detects_reuse(test_client, cleanup_emails):
    """Each refresh consumes the old token; replaying one kills the family."""
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    test_client.cookies.clear()
    reg = test_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": VALID_PASSWORD,
            "firstName": "Ada",
            "lastName": "Lovelace",
        },
    )
    assert reg.status_code == 201, reg.text
    session = reg.json()

    # The refresh token is *not* in the response body — that is the point of
    # moving it to an HttpOnly cookie (GAP_ANALYSIS §2.5). A script that can
    # read the body can read it from anywhere it is later stored.
    assert "refreshToken" not in session

    first = _cookie_from(reg)
    assert first, "register must set the refresh cookie"
    # It must be opaque, not a JWT — it has to be revocable.
    assert first.count(".") != 2

    # --- rotation ---
    r1 = _refresh_with(test_client, first)
    assert r1.status_code == 200, r1.text
    second = _cookie_from(r1)
    assert second != first
    assert r1.json()["accessToken"]
    assert "refreshToken" not in r1.json()

    # the rotated token keeps working
    r2 = _refresh_with(test_client, second)
    assert r2.status_code == 200
    third = _cookie_from(r2)

    # --- reuse detection: replaying a consumed token is rejected ---
    assert _refresh_with(test_client, first).status_code == 401

    # ...and the whole family is revoked, so the live token dies too.
    assert _refresh_with(test_client, third).status_code == 401

    # garbage is rejected without side effects
    assert _refresh_with(test_client, "nope").status_code == 401


def test_refresh_without_a_cookie_is_rejected(test_client, cleanup_emails):
    """The bootstrap path for a signed-out visitor: a plain 401, not a 500."""
    test_client.cookies.clear()
    assert test_client.post("/auth/refresh").status_code == 401


def test_the_refresh_cookie_is_not_readable_by_script(test_client, cleanup_emails):
    """HttpOnly is the entire mitigation, so assert the attributes explicitly.

    A cookie that is merely *not read* by today's client is one line of code
    away from being read by tomorrow's.
    """
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    test_client.cookies.clear()
    res = test_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": VALID_PASSWORD,
            "firstName": "Ada",
            "lastName": "Lovelace",
        },
    )
    assert res.status_code == 201, res.text
    header = res.headers["set-cookie"]
    assert REFRESH_COOKIE in header
    assert "HttpOnly" in header
    assert "SameSite" in header


def test_logout_revokes_refresh_token(test_client, cleanup_emails):
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    test_client.cookies.clear()
    reg = test_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": VALID_PASSWORD,
            "firstName": "Ada",
            "lastName": "Lovelace",
        },
    )
    token = _cookie_from(reg)

    assert test_client.post(
        "/auth/logout", headers={"Cookie": f"{REFRESH_COOKIE}={token}"}
    ).status_code == 200
    # Revoked: it can no longer be exchanged for a session, even if the caller
    # kept a copy of the cookie value.
    assert _refresh_with(test_client, token).status_code == 401


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
        "/auth/login", json={"email": email, "password": VALID_PASSWORD}
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
        "/auth/login", json={"email": email, "password": VALID_PASSWORD}
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
        "/auth/login", json={"email": victim, "password": VALID_PASSWORD}
    ).status_code == 429

    # The bystander is untouched — buckets are per-account, not global.
    assert test_client.post(
        "/auth/login", json={"email": bystander, "password": VALID_PASSWORD}
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


# ---------------------------------------------------------------------------
# Password policy (GAP_ANALYSIS §2.4) — there was none at all
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "password,because",
    [
        ("short1!", "under the 12-character floor"),
        ("password1234", "a top-of-every-breach-list word"),
        ("aaaaaaaaaaaaaaa", "too few distinct characters"),
        ("P@ssw0rd" + "!" * 5, "leetspeak is not strength"),
        ("  spaced out phrase ", "leading/trailing whitespace"),
    ],
)
def test_registration_rejects_weak_passwords(test_client, password, because):
    res = test_client.post(
        "/auth/register",
        json={
            "email": f"weak_{uuid.uuid4().hex[:8]}@example.com",
            "password": password,
            "firstName": "Ada",
            "lastName": "Lovelace",
        },
    )
    assert res.status_code == 422, f"should reject {because}: {res.text}"


def test_registration_rejects_a_password_containing_the_account_identifiers(
    test_client,
):
    """The first targeted guess, and one every length rule lets through."""
    res = test_client.post(
        "/auth/register",
        json={
            "email": "bartholomew@example.com",
            "password": "bartholomew-2026-spring",
            "firstName": "Ada",
            "lastName": "Lovelace",
        },
    )
    assert res.status_code == 422, res.text
    assert "email" in res.json()["detail"].lower()


def test_registration_is_rate_limited_per_ip(test_client, cleanup_emails, monkeypatch):
    """Unlike login, this counts successes: the abuse is bulk account creation,
    and every one of those succeeds (§2.3 left this endpoint open)."""
    from app.core.config import settings as cfg

    monkeypatch.setattr(cfg, "register_max_per_ip", 2)
    for _ in range(2):
        email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
        cleanup_emails.append(email)
        _register(test_client, email)

    blocked = test_client.post(
        "/auth/register",
        json={
            "email": f"auth_{uuid.uuid4().hex[:8]}@example.com",
            "password": VALID_PASSWORD,
            "firstName": "Ada",
            "lastName": "Lovelace",
        },
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


# ---------------------------------------------------------------------------
# Password change (GAP_ANALYSIS §4.3) — the form had nothing behind it
# ---------------------------------------------------------------------------

NEW_PASSWORD = "wheelbarrow-tangerine-42"


def test_password_change_requires_the_current_password(test_client, cleanup_emails):
    """Being signed in is not enough: this is what stops a stolen access token
    or an unattended browser becoming permanent account ownership."""
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    session = _register(test_client, email)
    headers = {"Authorization": f"Bearer {session['accessToken']}"}

    wrong = test_client.post(
        "/auth/password",
        json={"currentPassword": "not-the-password", "newPassword": NEW_PASSWORD},
        headers=headers,
    )
    assert wrong.status_code == 401
    # ...and the old password still works, i.e. nothing was changed.
    assert test_client.post(
        "/auth/login", json={"email": email, "password": VALID_PASSWORD}
    ).status_code == 200


def test_password_change_enforces_the_policy(test_client, cleanup_emails):
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    session = _register(test_client, email)

    res = test_client.post(
        "/auth/password",
        json={"currentPassword": VALID_PASSWORD, "newPassword": "123456"},
        headers={"Authorization": f"Bearer {session['accessToken']}"},
    )
    assert res.status_code == 422


def test_password_change_revokes_every_other_session(test_client, cleanup_emails):
    """A password change is what someone does when they think they are
    compromised. Leaving the attacker's refresh token alive makes it pointless."""
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    test_client.cookies.clear()
    reg = test_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": VALID_PASSWORD,
            "firstName": "Ada",
            "lastName": "Lovelace",
        },
    )
    stolen_refresh = _cookie_from(reg)
    headers = {"Authorization": f"Bearer {reg.json()['accessToken']}"}

    changed = test_client.post(
        "/auth/password",
        json={"currentPassword": VALID_PASSWORD, "newPassword": NEW_PASSWORD},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text

    # The refresh token that existed before the change is dead.
    assert _refresh_with(test_client, stolen_refresh).status_code == 401
    # The new password works; the old one does not.
    assert test_client.post(
        "/auth/login", json={"email": email, "password": NEW_PASSWORD}
    ).status_code == 200
    assert test_client.post(
        "/auth/login", json={"email": email, "password": VALID_PASSWORD}
    ).status_code == 401


# ---------------------------------------------------------------------------
# is_active (GAP_ANALYSIS §4.4) — read on every login, written by nothing
# ---------------------------------------------------------------------------

def _make_admin(email: str) -> None:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute("UPDATE users SET role = 'admin' WHERE email = %s;", (email,))
    conn.commit()
    cur.close()
    conn.close()


def test_admin_can_deactivate_an_account_and_it_takes_effect_at_once(
    test_client, cleanup_emails
):
    """Deactivation used to be consulted only at login — which a user holding a
    live token never performs again — so switching an account off did nothing."""
    admin_email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    target_email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.extend([admin_email, target_email])

    admin = _register(test_client, admin_email)
    _make_admin(admin_email)
    # Re-login so the admin's own session is unremarkable; role is read per
    # request from the database, so the existing token is already an admin's.
    admin_headers = {"Authorization": f"Bearer {admin['accessToken']}"}

    test_client.cookies.clear()
    target_reg = test_client.post(
        "/auth/register",
        json={
            "email": target_email,
            "password": VALID_PASSWORD,
            "firstName": "Ada",
            "lastName": "Lovelace",
        },
    )
    target = target_reg.json()
    target_refresh = _cookie_from(target_reg)
    target_headers = {"Authorization": f"Bearer {target['accessToken']}"}
    target_id = target["user"]["id"]

    # Working before.
    assert test_client.get("/proposals", headers=target_headers).status_code == 200

    res = test_client.patch(
        f"/auth/users/{target_id}/active",
        json={"isActive": False},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    # Same token, no re-login: already rejected.
    assert test_client.get("/proposals", headers=target_headers).status_code == 401
    assert test_client.get("/auth/me", headers=target_headers).status_code == 401
    # The refresh token was revoked too, so they cannot mint a fresh one.
    assert _refresh_with(test_client, target_refresh).status_code == 401
    # And they cannot sign back in.
    assert test_client.post(
        "/auth/login", json={"email": target_email, "password": VALID_PASSWORD}
    ).status_code == 401

    # Reactivation restores access.
    assert test_client.patch(
        f"/auth/users/{target_id}/active",
        json={"isActive": True},
        headers=admin_headers,
    ).status_code == 200
    assert test_client.post(
        "/auth/login", json={"email": target_email, "password": VALID_PASSWORD}
    ).status_code == 200


def test_deactivation_requires_admin(test_client, cleanup_emails):
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    session = _register(test_client, email)  # analyst by default

    res = test_client.patch(
        f"/auth/users/{session['user']['id']}/active",
        json={"isActive": False},
        headers={"Authorization": f"Bearer {session['accessToken']}"},
    )
    assert res.status_code == 403


def test_an_admin_cannot_deactivate_themselves(test_client, cleanup_emails):
    """Locking the last admin out is unrecoverable without database access."""
    email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    cleanup_emails.append(email)
    session = _register(test_client, email)
    _make_admin(email)

    res = test_client.patch(
        f"/auth/users/{session['user']['id']}/active",
        json={"isActive": False},
        headers={"Authorization": f"Bearer {session['accessToken']}"},
    )
    assert res.status_code == 400
