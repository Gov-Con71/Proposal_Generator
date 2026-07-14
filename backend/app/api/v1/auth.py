"""Real authentication endpoints (Story 4.2, pulled forward to close the gap).

Replaces the mock auth router: registers/authenticates against the `users`
table and issues real JWTs whose subject is the user's UUID. The upload
pipeline derives tenancy from these tokens.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user_id
from app.core.security import create_access_token
from app.models.contract import (
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    Session,
    User,
)
from app.services import user_service as users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _session_for(user: dict) -> Session:
    token, expire = create_access_token(user["id"])
    return Session(
        user=User(**user),
        access_token=token,
        # No refresh-token rotation yet; re-issue the access token as a stand-in.
        refresh_token=token,
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
            payload.email, payload.password, payload.first_name, payload.last_name
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


@router.post("/logout", response_model=MessageResponse, summary="Client-side session clear")
def logout() -> MessageResponse:
    # Stateless JWT: nothing to revoke server-side; the client drops the token.
    return MessageResponse(message="Session cleared.")
