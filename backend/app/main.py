from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import documents
from app.api.v1 import auth
from app.api.v1 import history
from app.api.v1 import workspace
from app.api.v1 import compliance
from app.api.v1 import profile
from app.api.v1 import exports
from app.api.v1 import pipeline
from app.api.v1 import monitoring
from app.api.v1 import proposals_crud
from app.core.config import settings

# --- Error reporting (Story 5.4) — no-op unless SENTRY_DSN is configured ---
if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
    )

DESCRIPTION = """
Interactive API contract for the AI Proposal Platform.

All routes are real and persistence-backed (Postgres + pgvector, S3 for
artifacts, Redis/Celery for async work). Responses mirror the frontend
TypeScript types exactly (camelCase JSON) — see `proposalai-frontend/lib/api`.
"""

tags_metadata = [
    {"name": "Auth", "description": "Register/login with JWT sessions; tenancy derives from the token."},
    {"name": "Documents", "description": "Live RFP upload → S3 streaming → async ingestion pipeline (Sprint 2)."},
    {"name": "Workspace", "description": "Requirement/section CRUD + RAG draft writer (Sprint 3)."},
    {"name": "History (RAG)", "description": "Past-performance ingestion into the pgvector store (Sprint 3)."},
    {"name": "Profile", "description": "Company profile read/write (Sprint 5)."},
    {"name": "Exports", "description": "Proposal export job lifecycle: create → poll → download (Sprint 5)."},
    {"name": "Proposals", "description": "Live, DB-backed proposal CRUD (Sprint 6)."},
]

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Runs the boot-time checks that make a silently degraded process say so.

    Both of the dependencies checked here fail quietly by design — the cache
    degrades to a miss, and a bad model name only shows up on the first
    generation, minutes later, inside a worker. See app/core/startup_checks.py
    for the two incidents that motivated it.
    """
    from app.core.startup_checks import run_startup_checks

    run_startup_checks()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=DESCRIPTION,
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Operational endpoints (health/ready/metrics) ---
app.include_router(monitoring.router)

# --- Real auth (JWT) ---
app.include_router(auth.router)

# --- Live document ingestion pipeline (Sprint 2) ---
app.include_router(documents.router)

# --- RAG workspace + history (Sprint 3) ---
app.include_router(workspace.router)
app.include_router(history.router)
app.include_router(compliance.router)

# --- Company profile + exports + live pipeline stream (frontend contract) ---
app.include_router(profile.router)
app.include_router(exports.router)
app.include_router(pipeline.router)

# --- Live, DB-backed proposal CRUD (Sprint 6) ---
app.include_router(proposals_crud.router)


@app.get("/")
def read_root():
    return {"message": "Scalable FastAPI Architecture Online!", "docs": "/docs"}
