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
        "role": "analyst",  # single role for now; RBAC is future work
        "company_id": "",   # workspaces/companies not modelled yet
        "avatar_url": None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def register_user(email: str, password: str, first_name: str, last_name: str) -> dict:
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash, first_name, last_name)
                VALUES (%s, %s, %s, %s)
                RETURNING user_id, email, first_name, last_name, created_at;
                """,
                (email.lower().strip(), hash_password(password), first_name, last_name),
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
                "SELECT user_id, email, password_hash, first_name, last_name, "
                "created_at, is_active FROM users WHERE email = %s;",
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
                "SELECT user_id, email, first_name, last_name, created_at "
                "FROM users WHERE user_id = %s;",
                (str(user_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _row_to_user(row) if row else None
