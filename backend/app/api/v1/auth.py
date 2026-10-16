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
from datetime import datetime, timezone
from typing import Union
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from app.core.csrf import protect_auth_request

from app.core import rate_limit
from app.core.config import settings
from app.core.deps import get_current_user, get_current_user_id, require_role
from app.core.password_policy import (
    MAX_PASSWORD_BYTES, MIN_DISTINCT_CHARACTERS, WeakPasswordError, validate_password,
)
from app.core.security import (
    create_access_token,
    create_two_factor_challenge_token,
    decode_two_factor_challenge_token,
    hash_refresh_token,
)
from app.models.contract import (
    ActiveSession,
    LoginRequest,
    MessageResponse,
    PasswordChangeRequest,
    PasswordPolicyResponse,
    RegisterRequest,
    Session,
    SetActiveRequest,
    TwoFactorChallenge,
    TwoFactorDisableRequest,
    TwoFactorLoginRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    User,
)
from app.services import refresh_token_service as refresh_tokens
from app.services import totp_service as totp
from app.services import user_service as users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"], dependencies=[Depends(protect_auth_request)])


def _sensitive_attempt(user_id, bucket="security_password"):
    rate_limit.require_attempt(bucket, str(user_id), settings.sensitive_max_attempts, settings.sensitive_window_seconds)


def _access_for_session(user_id, raw):
    session = refresh_tokens.session_for_token(raw)
    return create_access_token(str(user_id), session_id=str(session["session_id"]),
                               session_expires_at=session["session_expires_at"])


def _rejected_refresh(detail: str):
    response = JSONResponse(status_code=401, content={"detail": detail})
    _clear_refresh_cookie(response)
    return response


@router.get("/password-policy", response_model=PasswordPolicyResponse)
def password_policy() -> PasswordPolicyResponse:
    return PasswordPolicyResponse(
        min_length=settings.password_min_length,
        max_bytes=MAX_PASSWORD_BYTES,
        min_distinct_characters=MIN_DISTINCT_CHARACTERS,
    )


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Stores the refresh token where script cannot reach it.

    `max_age` matches the token's own lifetime so the browser drops it at the
    same moment the server would reject it — a cookie that outlives its token
    just produces a confusing 401 on the next visit. Attributes come from
    settings because the dev and production topologies need different ones; see
    the comment on `Settings.refresh_cookie_name`.
    """
    session = refresh_tokens.session_for_token(raw_token)
    remaining = int((session["session_expires_at"] - datetime.now(timezone.utc)).total_seconds())
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_token,
        max_age=max(0, min(settings.refresh_token_expire_days * 24 * 60 * 60, remaining)),
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


def _open_session(user: dict, request: Request, response: Response) -> Session:
    """Issues an access token in the body and a refresh token in the cookie."""
    try:
        raw = refresh_tokens.issue(
            user["id"],
            user_agent=request.headers.get("user-agent"),
            ip_address=rate_limit.client_ip(request),
            expected_auth_version=user["auth_version"],
        )
    except refresh_tokens.InvalidRefreshTokenError as exc:
        raise HTTPException(401, "Credentials changed. Please sign in again.") from exc
    token, expire = _access_for_session(user["id"], raw)
    _set_refresh_cookie(response, raw)
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
    return _open_session(user, request, response)


@router.post(
    "/login",
    response_model=Union[Session, TwoFactorChallenge],
    summary="Authenticate and open a session",
)
def login(
    payload: LoginRequest, request: Request, response: Response
) -> Session | TwoFactorChallenge:
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
        # Count failures. Exhausted buckets reject every attempt until expiry,
        # including correct passwords, to bound guessing and bcrypt work.
        rate_limit.record_failure("login_account", account, window)
        rate_limit.record_failure("login_ip", ip, window)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password."
        ) from exc

    rate_limit.reset("login_account", account)

    if user["totp_enabled"]:
        # Password checked out, but the session stays closed until the code
        # does too — no cookie, no access token, nothing usable yet.
        return TwoFactorChallenge(
            challenge_token=create_two_factor_challenge_token(user["id"], user["auth_version"])
        )
    return _open_session(user, request, response)


@router.post(
    "/2fa/login",
    response_model=Session,
    summary="Complete sign-in with a two-factor code",
)
def two_factor_login(
    payload: TwoFactorLoginRequest, request: Request, response: Response
) -> Session:
    """Exchanges a login's challenge token plus a TOTP code for a real session.

    The challenge token already proves the password step passed — it is
    signed by the server and short-lived (5 minutes) — so this only has to
    check the code.
    """
    try:
        user_id, auth_version = decode_two_factor_challenge_token(payload.challenge_token)
        UUID(user_id)
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "That sign-in attempt has expired. Please sign in again."
        ) from exc

    retry_after = rate_limit.check(
        "totp_login", user_id, settings.totp_max_failures_per_account
    )
    if retry_after:
        logger.warning("Rate limited 2FA login for user=%s", user_id)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many incorrect codes. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )

    if not totp.verify_login_code(UUID(user_id), payload.code, auth_version):
        rate_limit.record_failure(
            "totp_login", user_id, settings.totp_failure_window_seconds
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect code.")
    rate_limit.reset("totp_login", user_id)

    user = users.get_active_user(UUID(user_id))
    if user is None or user["auth_version"] != auth_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credentials changed. Please sign in again.")
    return _open_session(user, request, response)


@router.get("/me", response_model=User, summary="Return the current authenticated user")
def me(user_id=Depends(get_current_user_id)) -> User:
    user = users.get_active_user(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account is no longer active.")
    return User(**user)


@router.get(
    "/sessions",
    response_model=list[ActiveSession],
    summary="List this user's active sessions",
)
def list_sessions(request: Request, user_id=Depends(get_current_user_id)) -> list[ActiveSession]:
    """Every device with a live (unrevoked, unexpired) refresh token.

    Backs the Security page's "Active sessions" card (GAP_ANALYSIS §4.3),
    which used to render one hardcoded row regardless of who was signed in.
    """
    raw = request.cookies.get(settings.refresh_cookie_name)
    current_hash = hash_refresh_token(raw) if raw else None
    sessions = refresh_tokens.list_active(user_id, current_token_hash=current_hash)
    return [
        ActiveSession(
            id=str(s["token_id"]),
            user_agent=s["user_agent"],
            ip_address=s["ip_address"],
            created_at=s["created_at"].isoformat(),
            is_current=s["is_current"],
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
def revoke_device(session_id: UUID, request: Request, response: Response,
                  user_id=Depends(get_current_user_id)) -> MessageResponse:
    if not refresh_tokens.revoke_session(user_id, session_id):
        raise HTTPException(404, "Session not found.")
    raw = request.cookies.get(settings.refresh_cookie_name)
    if raw:
        try:
            current = refresh_tokens.session_for_token(raw)
            if str(current["session_id"]) == str(session_id):
                _clear_refresh_cookie(response)
        except refresh_tokens.InvalidRefreshTokenError:
            pass
    return MessageResponse(message="Device signed out.")


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
        user_id, new_refresh = refresh_tokens.rotate(
            raw,
            user_agent=request.headers.get("user-agent"),
            ip_address=rate_limit.client_ip(request),
        )
    except refresh_tokens.ConcurrentRefreshError:
        # Never clear or overwrite the cookie installed by the winning request.
        return JSONResponse(status_code=409, content={"detail": {"code": "refresh_in_progress"}},
                            headers={"Retry-After": "1"})
    except refresh_tokens.InvalidRefreshTokenError:
        return _rejected_refresh("Invalid or expired session.")

    user = users.get_active_user(user_id)
    if user is None:
        # Deactivated (or deleted) between issue and refresh. Revoking here is
        # what makes deactivation stick: without it the holder could keep
        # rotating indefinitely.
        refresh_tokens.revoke(new_refresh)
        return _rejected_refresh("This account is no longer active.")

    token, expire = _access_for_session(user["id"], new_refresh)
    _set_refresh_cookie(response, new_refresh)
    return Session(
        user=User(**user),
        access_token=token,
        expires_at=expire.astimezone(timezone.utc).isoformat(),
    )


@router.post("/logout", response_model=MessageResponse, summary="Revoke the session")
def logout(request: Request, response: Response) -> MessageResponse:
    """Revokes the refresh token and clears the cookie. Access tokens carry the stable session ID and become unusable immediately."""
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

    _sensitive_attempt(user_id)
    try:
        users.change_password(user_id, payload.current_password, payload.new_password)
    except users.InvalidCredentialsError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "incorrect_current_password",
                "message": "Your current password is incorrect.",
            },
        ) from exc

    _clear_refresh_cookie(response)
    return MessageResponse(
        message="Password updated. Sign in again to continue."
    )


@router.post(
    "/2fa/setup",
    response_model=TwoFactorSetupResponse,
    summary="Begin two-factor enrollment",
)
def setup_two_factor(user: dict = Depends(get_current_user)) -> TwoFactorSetupResponse:
    """Generates a new TOTP secret and returns it plus an otpauth:// URI for a
    QR code. Not enabled yet — /2fa/verify confirms it."""
    _sensitive_attempt(user["id"], "totp_enrollment")
    try:
        secret, uri = totp.start_enrollment(UUID(user["id"]), user["email"])
    except totp.TwoFactorAlreadyEnabledError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Two-factor authentication is already enabled. Disable it first to re-enroll.",
        ) from exc
    return TwoFactorSetupResponse(secret=secret, otpauth_url=uri)


@router.post(
    "/2fa/verify",
    response_model=MessageResponse,
    summary="Confirm two-factor enrollment with a code",
)
def verify_two_factor(
    payload: TwoFactorVerifyRequest, user_id=Depends(get_current_user_id)
) -> MessageResponse:
    """Proves the caller saved the secret from /2fa/setup, then turns 2FA on."""
    _sensitive_attempt(user_id, "totp_enrollment")
    try:
        totp.confirm_enrollment(user_id, payload.code)
    except totp.InvalidCodeError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Incorrect code. Check your authenticator app and try again.",
        ) from exc
    return MessageResponse(message="Two-factor authentication is now enabled.")


@router.post(
    "/2fa/disable",
    response_model=MessageResponse,
    summary="Disable two-factor authentication",
)
def disable_two_factor(
    payload: TwoFactorDisableRequest, user_id=Depends(get_current_user_id)
) -> MessageResponse:
    """Requires the account password, not just the bearer token — otherwise a
    15-minute access token stolen from an unattended tab would be enough to
    strip the second factor protecting the account."""
    _sensitive_attempt(user_id)
    try:
        totp.disable(user_id, payload.password)
    except users.InvalidCredentialsError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "incorrect_current_password", "message": "Your password is incorrect."},
        ) from exc
    return MessageResponse(message="Two-factor authentication is now disabled.")


@router.patch(
    "/users/{target_id}/active",
    response_model=User,
    summary="Activate or deactivate an account (admin)",
    dependencies=[Depends(require_role("admin"))],
)
def set_user_active(
    target_id: UUID, payload: SetActiveRequest, actor_id=Depends(get_current_user_id)
) -> User:
    """Gives `users.is_active` a writer.

    It has gated every login since Sprint 7 and been settable by nothing
    (GAP_ANALYSIS §4.4), so an account could be created and never shut off.

    Deactivation revokes sessions atomically; protected requests reject the account immediately.
    """
    if actor_id == target_id and not payload.is_active:
        # Locking yourself out of the only admin account is unrecoverable
        # without database access.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account."
        )

    user = users.set_active(target_id, payload.is_active)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return User(**user)
