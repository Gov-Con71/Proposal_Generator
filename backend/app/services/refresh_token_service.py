"""Atomic refresh rotation and revocable sessions, serialized per user."""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from psycopg2.extras import RealDictCursor
from app.core.config import settings
from app.core.db import get_connection
from app.core.security import generate_refresh_token, hash_refresh_token

logger = logging.getLogger(__name__)


class InvalidRefreshTokenError(Exception):
    pass


class ConcurrentRefreshError(Exception):
    """A recently rotated cookie is in flight; retry with the browser's new cookie."""


def _lock_user(cur, user_id):
    cur.execute("SELECT is_active, auth_version FROM users WHERE user_id = %s FOR UPDATE;", (str(user_id),))
    return cur.fetchone()


def _insert(cur, user_id, session_id, started, expires, user_agent, ip_address):
    raw, token_hash, sliding_expiry = generate_refresh_token()
    cur.execute("""INSERT INTO refresh_tokens
        (user_id, token_hash, expires_at, user_agent, ip_address, session_started_at, session_id, session_expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING token_id;""",
        (str(user_id), token_hash, min(sliding_expiry, expires), user_agent, ip_address, started, str(session_id), expires))
    return raw, cur.fetchone()["token_id"]


def issue(user_id: UUID, *, user_agent=None, ip_address=None, expected_auth_version=None) -> str:
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            user = _lock_user(cur, user_id)
            if not user or not user["is_active"] or (expected_auth_version is not None and user["auth_version"] != expected_auth_version):
                raise InvalidRefreshTokenError("Credentials changed; sign in again.")
            started = datetime.now(timezone.utc)
            expires = started + timedelta(days=settings.session_absolute_expire_days)
            raw, _ = _insert(cur, user_id, uuid4(), started, expires, user_agent, ip_address)
    finally:
        conn.close()
    return raw


def session_for_token(raw_token: str) -> dict:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT session_id, session_expires_at FROM refresh_tokens WHERE token_hash = %s;",
                        (hash_refresh_token(raw_token),))
            row = cur.fetchone()
            if not row:
                raise InvalidRefreshTokenError("Unknown session.")
            return dict(row)
    finally:
        conn.close()


def rotate(raw_token: str, user_agent=None, ip_address=None) -> tuple[UUID, str]:
    conn = get_connection()
    failure = None
    new_raw = None
    user_id = None
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Discover owner without locking a token ahead of its user.
            cur.execute("SELECT user_id FROM refresh_tokens WHERE token_hash = %s;", (hash_refresh_token(raw_token),))
            owner = cur.fetchone()
            if not owner:
                failure = InvalidRefreshTokenError("Unknown refresh token.")
            else:
                user_id = owner["user_id"]
                user = _lock_user(cur, user_id)
                cur.execute("""SELECT *, expires_at <= NOW() OR session_expires_at <= NOW() AS expired,
                    revoked_at > NOW() - (%s * INTERVAL '1 second') AS recently_rotated
                    FROM refresh_tokens WHERE token_hash = %s FOR UPDATE;""",
                    (settings.refresh_concurrency_seconds, hash_refresh_token(raw_token)))
                row = cur.fetchone()
                if not user or not user["is_active"] or not row:
                    failure = InvalidRefreshTokenError("Inactive account.")
                elif row["revoked_at"] is not None:
                    # No credentials or cookies are returned during this bounded grace.
                    # An explicitly revoked successor must never qualify as concurrency.
                    cur.execute("SELECT 1 FROM refresh_tokens WHERE token_id = %s AND revoked_at IS NULL AND expires_at > NOW();",
                                (str(row["replaced_by"]),) if row["replaced_by"] else (None,))
                    successor_alive = cur.fetchone() is not None
                    if row["recently_rotated"] and successor_alive:
                        failure = ConcurrentRefreshError()
                    else:
                        if row["replaced_by"]:
                            cur.execute("UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = %s AND revoked_at IS NULL;", (str(user_id),))
                            logger.warning("Refresh token reuse detected for user %s", user_id)
                        failure = InvalidRefreshTokenError("Refresh token already used.")
                elif row["expired"]:
                    failure = InvalidRefreshTokenError("Session expired.")
                else:
                    new_raw, new_id = _insert(cur, user_id, row["session_id"], row["session_started_at"],
                                             row["session_expires_at"], user_agent, ip_address)
                    cur.execute("UPDATE refresh_tokens SET revoked_at = NOW(), replaced_by = %s WHERE token_id = %s;",
                                (str(new_id), str(row["token_id"])))
        # Commit replay revocations before raising.
    finally:
        conn.close()
    if failure is not None:
        raise failure
    return user_id, new_raw


def is_active_session(user_id: UUID, session_id: UUID) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT 1 FROM refresh_tokens WHERE user_id = %s AND session_id = %s
                AND revoked_at IS NULL AND expires_at > NOW() AND session_expires_at > NOW() LIMIT 1;""",
                (str(user_id), str(session_id)))
            return cur.fetchone() is not None
    finally:
        conn.close()


def revoke(raw_token: str) -> None:
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT user_id, session_id FROM refresh_tokens WHERE token_hash = %s;", (hash_refresh_token(raw_token),))
            row = cur.fetchone()
            if row:
                _lock_user(cur, row["user_id"])
                cur.execute("UPDATE refresh_tokens SET revoked_at = NOW() WHERE session_id = %s AND revoked_at IS NULL;", (str(row["session_id"]),))
    finally:
        conn.close()


def revoke_session(user_id: UUID, session_id: UUID) -> bool:
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            _lock_user(cur, user_id)
            cur.execute("""UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = %s
                AND session_id = %s AND revoked_at IS NULL;""", (str(user_id), str(session_id)))
            return cur.rowcount > 0
    finally:
        conn.close()


def revoke_all_for_user(user_id: UUID) -> int:
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            _lock_user(cur, user_id)
            cur.execute("UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = %s AND revoked_at IS NULL;", (str(user_id),))
            return cur.rowcount
    finally:
        conn.close()


def list_active(user_id: UUID, current_token_hash=None) -> list[dict]:
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT session_id, user_agent, ip_address, session_started_at,
                session_id = (SELECT session_id FROM refresh_tokens WHERE token_hash = %s) AS is_current
                FROM refresh_tokens WHERE user_id = %s AND revoked_at IS NULL
                AND expires_at > NOW() AND session_expires_at > NOW() ORDER BY session_started_at DESC;""",
                (current_token_hash, str(user_id)))
            return [{"token_id": r["session_id"], "user_agent": r["user_agent"], "ip_address": r["ip_address"],
                     "created_at": r["session_started_at"], "is_current": bool(r["is_current"])} for r in cur.fetchall()]
    finally:
        conn.close()
