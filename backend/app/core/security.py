"""Password hashing and token helpers (auth, Story 4.2 + Sprint 7).

Access tokens are stateless JWTs. Refresh tokens are opaque random strings
stored as SHA-256 hashes (see app/services/refresh_token_service.py) — a JWT
cannot be revoked, and revocation is the whole point of a refresh token.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    """Returns a bcrypt hash suitable for the users.password_hash column."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str) -> tuple[str, datetime]:
    """Signs a JWT for `subject` (the user id). Returns (token, expiry)."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "type": "access"}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expire


def create_two_factor_challenge_token(subject: str) -> str:
    """Signs a short-lived JWT proving `subject`'s password already checked out.

    Issued by `/auth/login` when the account has 2FA enabled, in place of a
    session. Five minutes is long enough to type a 6-digit code and short
    enough that a token intercepted in transit is useless soon after.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {"sub": subject, "exp": expire, "type": "2fa_challenge"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_two_factor_challenge_token(token: str) -> str:
    """Returns the subject (user id) from a valid 2FA challenge token.

    Raises jwt exceptions on a bad/expired token, and ValueError if handed a
    token of any other type — an access or refresh token must not double as
    proof the password step already passed.
    """
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    if payload.get("type") != "2fa_challenge":
        raise ValueError("Not a 2FA challenge token.")
    return payload["sub"]


def decode_token(token: str) -> str:
    """Returns the subject (user id) from a valid access token.

    Raises jwt exceptions on a bad/expired token, and ValueError if handed a
    refresh token — the two are not interchangeable.
    """
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    if payload.get("type") != "access":
        raise ValueError("Not an access token.")
    return payload["sub"]


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Mints a refresh token. Returns (raw, sha256_hex, expiry).

    The raw value goes to the client once and is never stored; only the hash is
    persisted, so the database never holds a usable credential.
    """
    raw = secrets.token_urlsafe(48)
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    return raw, hash_refresh_token(raw), expire


def hash_refresh_token(raw: str) -> str:
    """SHA-256 rather than bcrypt: the token is already 48 bytes of entropy, so
    key-stretching buys nothing and would only slow every refresh."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
