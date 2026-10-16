"""CSRF checks for authentication endpoints that create or consume cookies."""
from fastapi import HTTPException, Request
from app.core.config import settings


def protect_auth_request(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origin_list:
        raise HTTPException(403, "Untrusted request origin.")
    if request.url.path in {"/auth/refresh", "/auth/logout"} and request.headers.get("x-csrf-protection") != "1":
        raise HTTPException(403, "CSRF protection header required.")
