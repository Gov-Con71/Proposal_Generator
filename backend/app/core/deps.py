"""Shared FastAPI dependencies — request-time authentication (Story 4.2)."""

from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token

# auto_error=False so we can raise a consistent 401 ourselves.
_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UUID:
    """Resolves the authenticated user's id from the Authorization: Bearer token.

    This is the tenant boundary — every protected route derives ownership from
    the token, never from client-supplied body fields.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        subject = decode_token(credentials.credentials)
        return UUID(subject)
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
