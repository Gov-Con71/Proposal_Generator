"""User persistence + authentication against the `users` table (Story 4.2)."""

import logging
from uuid import UUID

from psycopg2 import errors
from psycopg2.extras import RealDictCursor

from app.core.db import get_connection
from app.core.security import hash_password, verify_password

logger = logging.getLogger(__name__)


class EmailAlreadyExistsError(Exception):
    """Raised when registering an email that is already taken."""


class InvalidCredentialsError(Exception):
    """Raised on login when the email/password pair does not match."""


def _row_to_user(row: dict) -> dict:
    """Shapes a DB row into the API user dict (never includes the hash)."""
    first = row.get("first_name") or ""
    last = row.get("last_name") or ""
    return {
        "id": str(row["user_id"]),
        "email": row["email"],
        "name": (f"{first} {last}").strip() or row["email"],
        "role": row.get("role") or "analyst",
        "company_id": str(row["company_id"]) if row.get("company_id") else "",
        "avatar_url": None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "totp_enabled": bool(row.get("totp_enabled", False)),
    }


_USER_COLS = (
    "user_id, email, first_name, last_name, role, company_id, created_at, totp_enabled"
)


def _resolve_company(cur, name: str | None) -> str | None:
    """Finds or creates the company by case-insensitive name. Returns its id.

    Signing up under an existing organisation name joins it rather than creating
    a duplicate — the unique index on LOWER(name) enforces that.
    """
    if not name or not name.strip():
        return None
    clean = name.strip()
    cur.execute("SELECT company_id FROM companies WHERE LOWER(name) = LOWER(%s);", (clean,))
    row = cur.fetchone()
    if row:
        return str(row["company_id"])
    cur.execute(
        "INSERT INTO companies (name) VALUES (%s) RETURNING company_id;", (clean,)
    )
    return str(cur.fetchone()["company_id"])


def register_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    company: str | None = None,
) -> dict:
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            company_id = _resolve_company(cur, company)
            cur.execute(
                f"""
                INSERT INTO users (email, password_hash, first_name, last_name, company_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {_USER_COLS};
                """,
                (
                    email.lower().strip(),
                    hash_password(password),
                    first_name,
                    last_name,
                    company_id,
                ),
            )
            row = cur.fetchone()
    except errors.UniqueViolation as exc:
        conn.rollback()
        raise EmailAlreadyExistsError(email) from exc
    finally:
        conn.close()
    logger.info("Registered user %s", row["user_id"])
    return _row_to_user(row)


def authenticate(email: str, password: str) -> dict:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {_USER_COLS}, password_hash, is_active "
                "FROM users WHERE email = %s;",
                (email.lower().strip(),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None or not row.get("is_active", True):
        raise InvalidCredentialsError(email)
    if not verify_password(password, row["password_hash"]):
        raise InvalidCredentialsError(email)
    return _row_to_user(row)


def get_user(user_id: UUID) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {_USER_COLS} FROM users WHERE user_id = %s;",
                (str(user_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _row_to_user(row) if row else None


def change_password(user_id: UUID, current: str, new: str) -> None:
    """Verifies the current password and replaces it.

    The current password is required even though the caller is already
    authenticated: it is what stops a stolen access token — or an unattended
    logged-in browser — from being turned into permanent account ownership.

    Callers are expected to revoke the user's refresh tokens afterwards; that is
    left to the route so this stays a pure persistence concern.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT password_hash, is_active FROM users WHERE user_id = %s;",
                (str(user_id),),
            )
            row = cur.fetchone()
            if row is None or not row.get("is_active", True):
                raise InvalidCredentialsError(str(user_id))
            if not verify_password(current, row["password_hash"]):
                raise InvalidCredentialsError(str(user_id))
            cur.execute(
                "UPDATE users SET password_hash = %s, updated_at = NOW() "
                "WHERE user_id = %s;",
                (hash_password(new), str(user_id)),
            )
        conn.commit()
    finally:
        conn.close()
    logger.info("Password changed for user %s", user_id)


def verify_password_for(user_id: UUID, password: str) -> None:
    """Raises InvalidCredentialsError unless `password` matches the account.

    Used to gate disabling 2FA on an already-authenticated request: an access
    token alone (bearer, 15-minute-lived, and the only thing an XSS or a
    shoulder-surfed unattended tab would hand an attacker) should not be
    enough to turn off the second factor protecting the account.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT password_hash, is_active FROM users WHERE user_id = %s;",
                (str(user_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None or not row.get("is_active", True):
        raise InvalidCredentialsError(str(user_id))
    if not verify_password(password, row["password_hash"]):
        raise InvalidCredentialsError(str(user_id))


def set_active(user_id: UUID, is_active: bool) -> dict:
    """Activates or deactivates an account. Returns the updated user.

    `users.is_active` has been read on every login since Sprint 7 and written by
    nothing (GAP_ANALYSIS §4.4) — an account could be created but never shut
    off. Deactivation only bites on the *next* token check, so the caller also
    revokes refresh tokens; with a 15-minute access token that bounds a
    deactivated user's remaining access to one token lifetime.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE users SET is_active = %s, updated_at = NOW() "
                f"WHERE user_id = %s RETURNING {_USER_COLS};",
                (is_active, str(user_id)),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    if row is None:
        return {}
    logger.info("User %s is_active set to %s", user_id, is_active)
    return _row_to_user(row)


def get_active_user(user_id: UUID) -> dict | None:
    """Like `get_user`, but returns None for a deactivated account.

    One query rather than a get-then-check, because this runs on every
    authenticated request that needs a role. Deactivation previously took effect
    only at the next *login*, which a user with a live token never performs —
    so an account could be switched off and keep working indefinitely.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {_USER_COLS}, is_active FROM users WHERE user_id = %s;",
                (str(user_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None or not row.get("is_active", True):
        return None
    return _row_to_user(row)
