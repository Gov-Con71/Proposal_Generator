"""
API Contract Schemas (Story 1.3)
================================
Pydantic models that mirror the frontend TypeScript types in
`proposalai-frontend/types/index.ts` one-for-one.

All models serialise to **camelCase** via `to_camel`, so the JSON the backend
emits matches exactly what the Next.js client (`lib/api/index.ts`) expects.
These power the Swagger `/docs` contract used for front-end / AI sign-off.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Shared enums (mirror the TS string-literal unions)
# ---------------------------------------------------------------------------

Role = Literal["admin", "analyst", "viewer"]

ProposalStatus = Literal[
    "draft", "processing", "in_progress", "review_needed",
    "incomplete", "submitted", "archived",
]

RequirementCategory = Literal[
    "scope", "technical", "testing", "quality_assurance", "packaging",
    "marking", "financial", "legal", "compliance", "personnel",
    "reporting", "security", "service_level", "admin",
]

RequirementType = Literal["mandatory", "optional", "technical"]

ComplianceStatus = Literal["addressed", "partial", "missing", "na"]

SectionStatus = Literal["draft", "approved", "needs_review", "empty"]

ProcessingStatus = Literal["pending", "parsing", "extracting", "completed", "failed"]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class LoginRequest(CamelModel):
    email: str
    password: str


class RequestAccessRequest(CamelModel):
    email: str
    name: str
    company: str


class RegisterRequest(CamelModel):
    email: str
    password: str
    first_name: str
    last_name: str = ""


class User(CamelModel):
    id: str
    email: str
    name: str
    role: Role
    company_id: str
    avatar_url: Optional[str] = None
    created_at: str


class Session(CamelModel):
    user: User
    access_token: str
    refresh_token: str
    expires_at: str


class MessageResponse(CamelModel):
    message: str


# ---------------------------------------------------------------------------
# Documents / Upload
# ---------------------------------------------------------------------------

class UploadResponse(CamelModel):
    document_id: str
    proposal_id: str
    file_name: str
    size_bytes: int
    s3_key: str
    processing_status: ProcessingStatus
    uploaded_at: str


class ReanalyzeResponse(CamelModel):
    document_id: str
    processing_status: ProcessingStatus
    message: str


# ---------------------------------------------------------------------------
# Proposal views
# ---------------------------------------------------------------------------

class ProposalSummary(CamelModel):
    id: str
    title: str
    solicitation_number: str
    agency: str
    due_date: str
    compliance_score: int
    status: ProposalStatus
    created_at: str
    updated_at: str


class Proposal(ProposalSummary):
    contract_type: str
    naics_code: str
    naics_description: str
    pricing_model: str
    target_profit_margin: float
    drafting_level: Literal["technical", "executive"]
    tone: str
    page_limit: int
    document_id: str
    total_requirements: int
    addressed_requirements: int
    partial_requirements: int
    missing_requirements: int


class Requirement(CamelModel):
    id: str
    proposal_id: str
    number: int
    section: str
    text: str
    category: RequirementCategory
    type: RequirementType
    compliance_status: ComplianceStatus
    confidence_score: Optional[float] = None
    proposal_section_id: Optional[str] = None
    proposal_section_title: Optional[str] = None
    created_at: str


class AIFlag(CamelModel):
    id: str
    message: str
    severity: Literal["warning", "error"]


class ProposalSection(CamelModel):
    id: str
    proposal_id: str
    title: str
    content: str
    status: SectionStatus
    word_count: int
    ai_confidence_score: float
    ai_flags: list[AIFlag] = []
    mapped_requirement_ids: list[str] = []
    reference_tags: list[str] = []
    last_edited_at: str
    last_edited_by: str


# ---------------------------------------------------------------------------
# Workspace CRUD + RAG (Sprint 3)
# ---------------------------------------------------------------------------

class RequirementUpdate(CamelModel):
    compliance_status: Optional[ComplianceStatus] = None
    category: Optional[RequirementCategory] = None
    text: Optional[str] = None


class SectionCreate(CamelModel):
    title: str
    requirement_id: Optional[str] = None


class SectionUpdate(CamelModel):
    content: Optional[str] = None
    status: Optional[SectionStatus] = None


class GenerateSectionRequest(CamelModel):
    requirement_id: str
    title: Optional[str] = None


class HistoryIngestRequest(CamelModel):
    source_name: str
    content: str


class HistorySource(CamelModel):
    source_name: str
    chunks: int
    created_at: str


class HistoryIngestResponse(CamelModel):
    source_name: str
    chunks: int
