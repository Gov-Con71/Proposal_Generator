"""Encryption for TOTP secrets. Production requires a separate persistent key."""
import base64
import hashlib
from cryptography.fernet import Fernet
from app.core.config import settings


def _cipher() -> Fernet:
    key = settings.totp_encryption_key or base64.urlsafe_b64encode(
        hashlib.sha256(("development-totp:" + settings.jwt_secret).encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_secret(secret: str) -> str:
    return "fernet:" + _cipher().encrypt(secret.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value.startswith("fernet:"):
        raise ValueError("Unencrypted TOTP secret; run the session-security migration")
    return _cipher().decrypt(value.removeprefix("fernet:").encode()).decode()
