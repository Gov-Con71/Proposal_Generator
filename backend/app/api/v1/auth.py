"""Real authentication endpoints (Story 4.2, extended in Sprint 7 and Sprint 9).

Registers/authenticates against the `users` table and issues real JWTs whose
subject is the user's UUID. The upload pipeline derives tenancy from these
tokens. Refresh tokens are opaque, stored hashed, and rotated on every use.

**The refresh token never appears in a response body.** It is set as an
HttpOnly cookie, so no script — including one injected through a dependency or
a stored XSS — can read it (GAP_ANALYSIS §2.5). The access token still comes
back in the body, because the client must attach it as an Authorization header
and therefore has to be able to see it; it is deliberately short-lived (15
minutes) and the client keeps it in memory only, so closing the tab discards it
and nothing durable holds a credential.

That split is the whole design: the long-lived credential is unreadable by
script, and the script-readable credential is short-lived.
"""

import logging
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core import rate_limit
from app.core.config import settings
from app.core.deps import get_current_user_id, require_role
from app.core.password_policy import WeakPasswordError, validate_password
from app.core.security import create_access_token
from app.models.contract import (
    LoginRequest,
    MessageResponse,
    PasswordChangeRequest,
    RegisterRequest,
    Session,
    SetActiveRequest,
    User,
)
from app.services import refresh_token_service as refresh_tokens
from app.services import user_service as users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Stores the refresh token where script cannot reach it.

    `max_age` matches the token's own lifetime so the browser drops it at the
    same moment the server would reject it — a cookie that outlives its token
    just produces a confusing 401 on the next visit. Attributes come from
    settings because the dev and production topologies need different ones; see
    the comment on `Settings.refresh_cookie_name`.
    """
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain or None,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    # The attributes must match the ones it was set with, or the browser keeps
    # the original cookie and "logout" silently does nothing.
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain or None,
        path="/",
    )


def _open_session(user: dict, response: Response) -> Session:
    """Issues an access token in the body and a refresh token in the cookie."""
    token, expire = create_access_token(user["id"])
    _set_refresh_cookie(response, refresh_tokens.issue(user["id"]))
    return Session(
        user=User(**user),
        access_token=token,
        expires_at=expire.astimezone(timezone.utc).isoformat(),
    )


@router.post(
    "/register",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and open a session",
)
def register(payload: RegisterRequest, request: Request, response: Response) -> Session:
    # Per-IP only: there is no account to key on yet, which is precisely why
    # this endpoint was left unthrottled (§2.3). Successes count as well as
    # failures — the abuse here is bulk account creation, and all of that
    # succeeds by definition.
    ip = rate_limit.client_ip(request)
    retry_after = rate_limit.check("register_ip", ip, settings.register_max_per_ip)
    if retry_after:
        logger.warning("Rate limited registration from ip=%s", ip)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many accounts created from this address. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        validate_password(
            payload.password,
            email=payload.email,
            name=f"{payload.first_name} {payload.last_name}",
        )
    except WeakPasswordError as exc:
        # 422, matching the framework's own validation failures: the request was
        # understood and its content rejected.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

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

    rate_limit.record_failure("register_ip", ip, settings.register_window_seconds)
    return _open_session(user, response)


@router.post("/login", response_model=Session, summary="Authenticate and open a session")
def login(payload: LoginRequest, request: Request, response: Response) -> Session:
    account = payload.email.lower().strip()
    ip = rate_limit.client_ip(request)
    window = settings.login_failure_window_seconds

    # Check both buckets before touching bcrypt — a throttled caller should cost
    # us nothing, and hashing is deliberately expensive.
    for bucket, ident, limit in (
        ("login_account", account, settings.login_max_failures_per_account),
        ("login_ip", ip, settings.login_max_failures_per_ip),
    ):
        retry_after = rate_limit.check(bucket, ident, limit)
        if retry_after:
            logger.warning("Rate limited login for %s=%s", bucket, ident)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many failed sign-in attempts. Try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

    try:
        user = users.authenticate(payload.email, payload.password)
    except users.InvalidCredentialsError as exc:
        # Count only failures, so a correct password is never throttled and an
        # attacker cannot lock a victim out by exhausting their budget.
        rate_limit.record_failure("login_account", account, window)
        rate_limit.record_failure("login_ip", ip, window)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password."
        ) from exc

    rate_limit.reset("login_account", account)
    return _open_session(user, response)


@router.get("/me", response_model=User, summary="Return the current authenticated user")
def me(user_id=Depends(get_current_user_id)) -> User:
    user = users.get_active_user(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account is no longer active.")
    return User(**user)


@router.post(
    "/refresh",
    response_model=Session,
    summary="Exchange the refresh cookie for a new session",
)
def refresh(request: Request, response: Response) -> Session:
    """Rotates the refresh token: the presented one is consumed and a new one
    issued. Replaying a consumed token revokes every session for that user.

    The token is read from the HttpOnly cookie, never from the body. This is
    also the client's bootstrap on page load — the access token lives only in
    memory, so a reload has nothing until this call returns.
    """
    raw = request.cookies.get(settings.refresh_cookie_name)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No active session.")

    try:
        user_id, new_refresh = refresh_tokens.rotate(raw)
    except refresh_tokens.InvalidRefreshTokenError as exc:
        # Clear it: keeping a cookie the server rejects means every subsequent
        # bootstrap re-attempts a token that can never work again.
        _clear_refresh_cookie(response)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired session."
        ) from exc

    user = users.get_active_user(user_id)
    if user is None:
        # Deactivated (or deleted) between issue and refresh. Revoking here is
        # what makes deactivation stick: without it the holder could keep
        # rotating indefinitely.
        refresh_tokens.revoke(new_refresh)
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account is no longer active.")

    token, expire = create_access_token(user["id"])
    _set_refresh_cookie(response, new_refresh)
    return Session(
        user=User(**user),
        access_token=token,
        expires_at=expire.astimezone(timezone.utc).isoformat(),
    )


@router.post("/logout", response_model=MessageResponse, summary="Revoke the session")
def logout(request: Request, response: Response) -> MessageResponse:
    """Revokes the refresh token and clears the cookie. The access token stays
    valid until it expires — inherent to stateless JWTs, and why the access
    lifetime is 15 minutes against the refresh token's 30 days."""
    raw = request.cookies.get(settings.refresh_cookie_name)
    if raw:
        refresh_tokens.revoke(raw)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Session cleared.")


@router.post(
    "/password",
    response_model=MessageResponse,
    summary="Change the current user's password",
)
def change_password(
    payload: PasswordChangeRequest,
    response: Response,
    user_id=Depends(get_current_user_id),
) -> MessageResponse:
    """Changes the password, then signs every other session out.

    The Security page has had this form since Sprint 5 with nothing behind it
    (GAP_ANALYSIS §4.3). Revoking on success is the part that matters: a
    password change is what someone does when they believe their account is
    compromised, and leaving the attacker's refresh token alive would make the
    change pointless.
    """
    try:
        validate_password(payload.new_password)
    except WeakPasswordError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    try:
        users.change_password(user_id, payload.current_password, payload.new_password)
    except users.InvalidCredentialsError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your current password is incorrect."
        ) from exc

    revoked = refresh_tokens.revoke_all_for_user(user_id)
    _clear_refresh_cookie(response)
    logger.info("Password change revoked %d refresh token(s) for %s", revoked, user_id)
    return MessageResponse(
        message="Password updated. Sign in again to continue."
    )


@router.patch(
    "/users/{target_id}/active",
    response_model=User,
    summary="Activate or deactivate an account (admin)",
    dependencies=[Depends(require_role("admin"))],
)
def set_user_active(
    target_id: str, payload: SetActiveRequest, actor_id=Depends(get_current_user_id)
) -> User:
    """Gives `users.is_active` a writer.

    It has gated every login since Sprint 7 and been settable by nothing
    (GAP_ANALYSIS §4.4), so an account could be created and never shut off.

    Deactivating also revokes the target's refresh tokens, which is what bounds
    their remaining access to one access-token lifetime (15 minutes) rather than
    to the 30-day refresh window.
    """
    if str(actor_id) == target_id and not payload.is_active:
        # Locking yourself out of the only admin account is unrecoverable
        # without database access.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account."
        )

    user = users.set_active(target_id, payload.is_active)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if not payload.is_active:
        refresh_tokens.revoke_all_for_user(target_id)
    return User(**user)
