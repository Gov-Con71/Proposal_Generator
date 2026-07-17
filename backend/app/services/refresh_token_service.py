"""Refresh-token persistence and rotation (Sprint 7).

Every refresh consumes the presented token and issues a new one. Presenting an
already-consumed token means it leaked (the legitimate client would have moved
on to its replacement), so the whole family is revoked and the user is forced to
re-authenticate. This is the OWASP refresh-token-rotation pattern.
"""

import logging
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.core.db import get_connection
from app.core.security import generate_refresh_token, hash_refresh_token

logger = logging.getLogger(__name__)


class InvalidRefreshTokenError(Exception):
    """Raised when a refresh token is unknown, expired, or already consumed."""


def issue(user_id: UUID, replaces: UUID | None = None) -> str:
    """Stores a new refresh token for `user_id` and returns the raw value."""
    raw, token_hash, expires_at = generate_refresh_token()
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
                VALUES (%s, %s, %s)
                RETURNING token_id;
                """,
                (str(user_id), token_hash, expires_at),
            )
            new_id = cur.fetchone()["token_id"]
            if replaces is not None:
                # Link the chain so a reuse can be traced back to its family.
                cur.execute(
                    "UPDATE refresh_tokens SET replaced_by = %s WHERE token_id = %s;",
                    (str(new_id), str(replaces)),
                )
    finally:
        conn.close()
    return raw


def rotate(raw_token: str) -> tuple[UUID, str]:
    """Consumes `raw_token` and returns (user_id, new_raw_token).

    Raises InvalidRefreshTokenError if the token is unknown, expired, or has
    already been consumed — the last case also revokes every other token for
    that user, since a replayed token means it escaped the client.
    """
    token_hash = hash_refresh_token(raw_token)
    conn = get_connection()
    # Never raise inside the `with conn` block below: psycopg2 rolls the
    # transaction back on exception, which would silently undo the family
    # revocation this function performs. Collect the outcome, commit, then raise.
    failure: str | None = None
    reused_by: UUID | None = None
    user_id: UUID | None = None
    old_id: UUID | None = None
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT token_id, user_id, revoked_at, expires_at < NOW() AS expired
                FROM refresh_tokens WHERE token_hash = %s
                FOR UPDATE;
                """,
                (token_hash,),
            )
            row = cur.fetchone()

            if row is None:
                failure = "Unknown refresh token."
            elif row["revoked_at"] is not None:
                # Replay of a consumed token: assume compromise, drop the family.
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = NOW() "
                    "WHERE user_id = %s AND revoked_at IS NULL;",
                    (str(row["user_id"]),),
                )
                reused_by = row["user_id"]
                failure = "Refresh token already used."
            elif row["expired"]:
                failure = "Refresh token expired."
            else:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_id = %s;",
                    (str(row["token_id"]),),
                )
                user_id = row["user_id"]
                old_id = row["token_id"]
    finally:
        conn.close()

    if failure is not None:
        if reused_by is not None:
            logger.warning(
                "Refresh token reuse detected for user %s — revoked all sessions",
                reused_by,
            )
        raise InvalidRefreshTokenError(failure)

    # Issued outside the transaction above so the consume is already committed.
    return user_id, issue(user_id, replaces=old_id)


def revoke(raw_token: str) -> None:
    """Best-effort revoke of a single token (logout). Unknown tokens are a no-op
    so logout stays idempotent and never leaks whether a token existed."""
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE refresh_tokens SET revoked_at = NOW() "
                "WHERE token_hash = %s AND revoked_at IS NULL;",
                (hash_refresh_token(raw_token),),
            )
    finally:
        conn.close()


def revoke_all_for_user(user_id: UUID) -> int:
    """Revokes every live token for a user. Returns how many were revoked."""
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE refresh_tokens SET revoked_at = NOW() "
                "WHERE user_id = %s AND revoked_at IS NULL;",
                (str(user_id),),
            )
            return cur.rowcount
    finally:
        conn.close()
