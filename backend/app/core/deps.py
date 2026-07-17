"""Shared FastAPI dependencies — request-time authentication (Story 4.2)
and role authorisation (Sprint 7)."""

from collections.abc import Callable
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


def get_current_user(user_id: UUID = Depends(get_current_user_id)) -> dict:
    """Loads the authenticated user's record. Roles are read from the database,
    never from the token, so a role change takes effect on the next request
    rather than whenever the access token happens to expire."""
    # Imported here to keep the module import graph free of a service cycle.
    from app.services import user_service

    user = user_service.get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*allowed: str) -> Callable[[dict], dict]:
    """Dependency factory gating a route on the caller's role.

        @router.delete("/x", dependencies=[Depends(require_role("admin"))])
    """

    def _guard(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed:
            # 403, not 404: the caller is authenticated, just not permitted.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not permit this action.",
            )
        return user

    return _guard


# Guards every state-changing route: viewers are read-only, admins and analysts
# may write. 'analyst' is the registration default, so existing accounts are
# unaffected — this only gives 'viewer' a meaning it did not have before.
require_writer = require_role("admin", "analyst")
