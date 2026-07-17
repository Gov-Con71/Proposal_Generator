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
    }


_USER_COLS = (
    "user_id, email, first_name, last_name, role, company_id, created_at"
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
