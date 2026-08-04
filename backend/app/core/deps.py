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


def _subject_from_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UUID:
    """Validates the bearer token's signature and returns its subject.

    Signature only — it says nothing about whether the account still exists or
    is still permitted to act. `get_current_user` is what decides that.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return UUID(decode_token(credentials.credentials))
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(user_id: UUID = Depends(_subject_from_token)) -> dict:
    """Loads the authenticated user's record, rejecting deactivated accounts.

    Roles and active status are read from the database, never from the token, so
    both take effect on the *next request* rather than whenever the access token
    happens to expire. `is_active` was previously consulted only at login — which
    a user holding a live token never performs again — so switching an account
    off did nothing at all (GAP_ANALYSIS §4.4).

    This costs one indexed primary-key lookup per authenticated request. That is
    the price of revoking a stateless JWT: the alternative is a deactivated
    account that keeps working until its token expires, and "we can't lock this
    person out for another quarter of an hour" is not an acceptable answer to an
    offboarding. FastAPI caches the dependency per request, so a route that also
    needs the role does not pay for it twice.
    """
    # Imported here to keep the module import graph free of a service cycle.
    from app.services import user_service

    user = user_service.get_active_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account is no longer active.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user_id(user: dict = Depends(get_current_user)) -> UUID:
    """The authenticated user's id — the tenant boundary.

    Every protected route derives ownership from this, never from a
    client-supplied body field. It now resolves *through* `get_current_user`, so
    a route that only needs an id still gets the deactivation check; before, the
    check applied only to the handful of routes that happened to need a role.
    """
    return UUID(user["id"])


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
