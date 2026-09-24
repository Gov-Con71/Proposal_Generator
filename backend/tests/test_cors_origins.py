"""CORS origin allow-listing, exact and by pattern.

Nothing covered this before, and it is one of the few settings where being
*too permissive* fails silently: a wrong value here doesn't break a request,
it hands an authenticated session to a site that shouldn't have one. Since
allow_credentials=True, every origin matched here can read responses with the
user's cookie attached.

`make_app` mirrors the two arguments `app/main.py` passes, because `app` is
constructed at import with settings already baked in and cannot be rebuilt per
test. The final test exercises the real app to confirm the shipped default is
closed.
"""

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.config import settings

PROD = "https://proposalai.vercel.app"
# What Vercel actually generates for a branch build: project, hash, team.
PREVIEW = "https://proposalai-frontend-k3f9dl2-govcon71.vercel.app"
# Anchored and prefixed with our own project, so it cannot match Vercel at large.
PREVIEW_RE = r"^https://proposalai-frontend-[a-z0-9-]+\.vercel\.app$"


def make_app(origins: list[str], regex: str = "") -> TestClient:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    def ping():  # pragma: no cover — only the CORS headers matter
        return {"ok": True}

    return TestClient(app)


def allowed_origin(client: TestClient, origin: str) -> str | None:
    """The Access-Control-Allow-Origin a preflight from `origin` comes back with."""
    res = client.options(
        "/ping",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    return res.headers.get("access-control-allow-origin")


def test_exact_origin_is_allowed():
    assert allowed_origin(make_app([PROD]), PROD) == PROD


def test_preview_origin_needs_the_regex():
    """The gap this setting closes: a preview hostname is not in CORS_ORIGINS.

    Vercel mints a new hostname per build, so without a pattern every preview
    branch fails CORS and the list has to be edited per branch.
    """
    assert allowed_origin(make_app([PROD]), PREVIEW) is None
    assert allowed_origin(make_app([PROD], PREVIEW_RE), PREVIEW) == PREVIEW


def test_empty_regex_is_not_permissive():
    """The dangerous failure mode: "" must not become match-everything.

    Starlette compiles the pattern it is given, so passing "" instead of None
    would compile an empty pattern — harmless under fullmatch, but this pins the
    behaviour rather than trusting it.
    """
    client = make_app([PROD], "")
    assert allowed_origin(client, "https://evil.example") is None
    assert allowed_origin(client, PREVIEW) is None


def test_anchored_regex_rejects_other_vercel_projects():
    """`.*\\.vercel\\.app` would hand every Vercel site a credentialed session."""
    client = make_app([PROD], PREVIEW_RE)
    assert allowed_origin(client, "https://someone-elses-app.vercel.app") is None
    # Also not a lookalike that merely contains the project name.
    assert allowed_origin(client, "https://proposalai-frontend-x.vercel.app.evil.com") is None


def test_allowed_origin_is_reflected_never_wildcard():
    """A credentialed request rejects `*`, so the exact origin must come back."""
    assert allowed_origin(make_app([PROD], PREVIEW_RE), PREVIEW) != "*"
    assert allowed_origin(make_app([PROD]), PROD) != "*"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://localhost:3000", ["http://localhost:3000"]),
        ("  a , b ,, c  ", ["a", "b", "c"]),
        ("", []),
    ],
)
def test_cors_origin_list_parsing(monkeypatch, raw, expected):
    monkeypatch.setattr(settings, "cors_origins", raw)
    assert settings.cors_origin_list == expected


def test_shipped_default_rejects_a_foreign_origin():
    """The real app, as configured, must not answer to an arbitrary site."""
    from app.main import app

    client = TestClient(app)
    assert allowed_origin(client, "https://evil.example") is None
