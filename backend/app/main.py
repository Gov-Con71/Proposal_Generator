from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import proposals
from app.api.v1 import documents
from app.api.v1 import auth
from app.api.v1 import history
from app.api.v1 import workspace
from app.api.mock import proposals as mock_proposals
from app.core.config import settings

DESCRIPTION = """
Interactive API contract for the AI Proposal Platform.

**Story 1.3 — Contract sign-off.** The `(mock)` routers below publish the
request/response shapes the frontend (`proposalai-frontend/lib/api`) and AI
layer build against, with deterministic mock responses. They mirror the
frontend TypeScript types exactly (camelCase JSON).

Real, persistence-backed routes live under `/api/v1`.
"""

tags_metadata = [
    {"name": "Auth", "description": "Register/login with JWT sessions; tenancy derives from the token."},
    {"name": "Documents", "description": "Live RFP upload → S3 streaming → async ingestion pipeline (Sprint 2)."},
    {"name": "Workspace", "description": "Requirement/section CRUD + RAG draft writer (Sprint 3)."},
    {"name": "History (RAG)", "description": "Past-performance ingestion into the pgvector store (Sprint 3)."},
    {"name": "Proposals (mock)", "description": "Proposal list/detail (no proposals table yet)."},
    {"name": "Proposals", "description": "Live, DB-backed proposal persistence."},
]

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=DESCRIPTION,
    openapi_tags=tags_metadata,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Real auth (JWT) ---
app.include_router(auth.router)

# --- Live document ingestion pipeline (Sprint 2) ---
app.include_router(documents.router)

# --- RAG workspace + history (Sprint 3) ---
app.include_router(workspace.router)
app.include_router(history.router)

# --- Story 1.3: mock contract routers (read-side, still awaiting real impl) ---
app.include_router(mock_proposals.router)

# --- Live, DB-backed routes ---
app.include_router(proposals.router, prefix="/api/v1")


@app.get("/")
def read_root():
    return {"message": "Scalable FastAPI Architecture Online!", "docs": "/docs"}
