"""Real authentication endpoints (Story 4.2, extended in Sprint 7).

Registers/authenticates against the `users` table and issues real JWTs whose
subject is the user's UUID. The upload pipeline derives tenancy from these
tokens. Refresh tokens are opaque, stored hashed, and rotated on every use.
"""

import logging
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user_id
from app.core.security import create_access_token
from app.models.contract import (
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    Session,
    User,
)
from app.services import refresh_token_service as refresh_tokens
from app.services import user_service as users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _session_for(user: dict) -> Session:
    token, expire = create_access_token(user["id"])
    return Session(
        user=User(**user),
        access_token=token,
        refresh_token=refresh_tokens.issue(user["id"]),
        expires_at=expire.astimezone(timezone.utc).isoformat(),
    )


@router.post(
    "/register",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and open a session",
)
def register(payload: RegisterRequest) -> Session:
    try:
        user = users.register_user(
            payload.email,
            payload.password,
            payload.first_name,
            payload.last_name,
            payload.company,
        )
    except users.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with that email already exists."
        ) from exc
    return _session_for(user)


@router.post("/login", response_model=Session, summary="Authenticate and open a session")
def login(payload: LoginRequest) -> Session:
    try:
        user = users.authenticate(payload.email, payload.password)
    except users.InvalidCredentialsError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password."
        ) from exc
    return _session_for(user)


@router.get("/me", response_model=User, summary="Return the current authenticated user")
def me(user_id=Depends(get_current_user_id)) -> User:
    user = users.get_user(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User no longer exists.")
    return User(**user)


@router.post(
    "/refresh",
    response_model=Session,
    summary="Exchange a refresh token for a new session",
)
def refresh(payload: RefreshRequest) -> Session:
    """Rotates the refresh token: the presented one is consumed and a new one
    issued. Replaying a consumed token revokes every session for that user."""
    try:
        user_id, new_refresh = refresh_tokens.rotate(payload.refresh_token)
    except refresh_tokens.InvalidRefreshTokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token."
        ) from exc

    user = users.get_user(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists.")

    token, expire = create_access_token(user["id"])
    return Session(
        user=User(**user),
        access_token=token,
        refresh_token=new_refresh,
        expires_at=expire.astimezone(timezone.utc).isoformat(),
    )


@router.post("/logout", response_model=MessageResponse, summary="Revoke the session")
def logout(payload: RefreshRequest | None = None) -> MessageResponse:
    """Revokes the refresh token so it cannot be rotated again. The access token
    stays valid until it expires — that is inherent to stateless JWTs, and is
    why the access lifetime is kept short relative to the refresh one."""
    if payload and payload.refresh_token:
        refresh_tokens.revoke(payload.refresh_token)
    return MessageResponse(message="Session cleared.")
