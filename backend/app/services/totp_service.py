"""TOTP-based two-factor authentication (RFC 6238).

Wires the Security page's "Two-factor authentication" card — an Enable button
with nothing behind it since it was built. Enrollment is two steps: `start`
stores a secret unconfirmed, `confirm` only flips `totp_enabled` on once the
caller proves they can produce a matching code, so "enabling 2FA" can't
succeed without the user actually having saved the secret in an authenticator
app.
"""

import logging
import time
from uuid import UUID

import pyotp
from psycopg2.extras import RealDictCursor

from app.core.config import settings
from app.core.db import get_connection
from app.core.secret_encryption import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)

_STEP_SECONDS = 30


class TwoFactorAlreadyEnabledError(Exception):
    """Raised when enrollment is attempted while 2FA is already on. The caller
    must disable first — otherwise a stolen access token could silently swap
    in an attacker-controlled secret on an already-protected account."""


class InvalidCodeError(Exception):
    """Raised when a submitted TOTP code does not verify."""


def start_enrollment(user_id: UUID, email: str) -> tuple[str, str]:
    """Generates a new secret, stores it unconfirmed, and returns
    (secret, otpauth_uri) for QR-code enrollment."""
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT totp_enabled FROM users WHERE user_id = %s FOR UPDATE;",
                (str(user_id),),
            )
            row = cur.fetchone()
            if row and row["totp_enabled"]:
                raise TwoFactorAlreadyEnabledError(str(user_id))
            secret = pyotp.random_base32()
            cur.execute(
                "UPDATE users SET totp_secret = %s, totp_last_used_step = NULL "
                "WHERE user_id = %s;",
                (encrypt_secret(secret), str(user_id)),
            )
    finally:
        conn.close()
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.app_name)
    return secret, uri


def confirm_enrollment(user_id: UUID, code: str) -> None:
    """Verifies `code` against the pending secret and turns 2FA on.

    Raises InvalidCodeError if there is no pending secret or the code does
    not match.
    """
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT totp_secret, totp_last_used_step, totp_enabled FROM users "
                "WHERE user_id = %s FOR UPDATE;",
                (str(user_id),),
            )
            row = cur.fetchone()
            secret = decrypt_secret(row["totp_secret"]) if row and row["totp_secret"] else None
            if secret is None or row["totp_enabled"]:
                raise InvalidCodeError(str(user_id))
            step = _verify_and_get_step(secret, code, row["totp_last_used_step"])
            if step is None:
                raise InvalidCodeError(str(user_id))
            cur.execute(
                "UPDATE users SET totp_enabled = TRUE, auth_version = auth_version + 1, totp_last_used_step = %s "
                "WHERE user_id = %s;",
                (step, str(user_id)),
            )
    finally:
        conn.close()
    logger.info("2FA enabled for user %s", user_id)


def verify_login_code(user_id: UUID, code: str, expected_auth_version: int) -> bool:
    """Checks `code` for a user whose 2FA is already enabled, as the second
    step of login. Consumes the matched time step so it cannot be replayed."""
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT totp_secret, totp_enabled, totp_last_used_step, auth_version, is_active FROM users "
                "WHERE user_id = %s FOR UPDATE;",
                (str(user_id),),
            )
            row = cur.fetchone()
            if row is None or not row["is_active"] or row["auth_version"] != expected_auth_version or not row["totp_enabled"] or row["totp_secret"] is None:
                return False
            step = _verify_and_get_step(
                decrypt_secret(row["totp_secret"]), code, row["totp_last_used_step"]
            )
            if step is None:
                return False
            cur.execute(
                "UPDATE users SET totp_last_used_step = %s WHERE user_id = %s;",
                (step, str(user_id)),
            )
    finally:
        conn.close()
    return True


def disable(user_id: UUID, password: str) -> None:
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            from app.core.security import verify_password
            from app.services.user_service import InvalidCredentialsError
            cur.execute("SELECT password_hash, is_active FROM users WHERE user_id = %s FOR UPDATE;", (str(user_id),))
            row = cur.fetchone()
            if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
                raise InvalidCredentialsError(str(user_id))
            cur.execute(
                "UPDATE users SET totp_enabled = FALSE, auth_version = auth_version + 1, totp_secret = NULL, "
                "totp_last_used_step = NULL WHERE user_id = %s;",
                (str(user_id),),
            )
    finally:
        conn.close()
    logger.info("2FA disabled for user %s", user_id)


def _verify_and_get_step(secret: str, code: str, last_used_step: int | None) -> int | None:
    """Checks `code` against the ±1-step window around now and returns the
    matching step, or None if nothing in the window matches — or the only
    match is a step already consumed (a replay).

    Steps are checked individually, rather than via `pyotp`'s own
    `valid_window`, specifically so the matching step can be recorded and a
    captured code cannot be replayed for the rest of its ~90s window.
    """
    totp = pyotp.TOTP(secret)
    now_step = int(time.time()) // _STEP_SECONDS
    for step in (now_step - 1, now_step, now_step + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        # TOTP.at() takes a Unix timestamp, not a step index — the step must
        # be scaled back up to seconds, or every call collapses onto totally
        # different (and wrong) 30s windows than the ones being checked.
        if totp.at(step * _STEP_SECONDS) == code:
            return step
    return None
