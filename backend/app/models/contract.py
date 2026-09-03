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
from uuid import UUID

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


class RegisterRequest(CamelModel):
    email: str
    password: str
    first_name: str
    last_name: str = ""
    # Optional: signing up under an existing organisation name joins it.
    company: str = ""


class PasswordChangeRequest(CamelModel):
    current_password: str
    new_password: str


class SetActiveRequest(CamelModel):
    is_active: bool


class User(CamelModel):
    id: str
    email: str
    name: str
    role: Role
    company_id: str
    avatar_url: Optional[str] = None
    created_at: str
    totp_enabled: bool = False


class Session(CamelModel):
    user: User
    access_token: str
    # No refresh_token: it is delivered as an HttpOnly cookie so that no script
    # can read it (GAP_ANALYSIS §2.5). Putting it here would hand it straight
    # back to the JavaScript the cookie exists to hide it from.
    expires_at: str


class ActiveSession(CamelModel):
    id: str
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: str
    is_current: bool


# ---------------------------------------------------------------------------
# Two-factor authentication (TOTP)
# ---------------------------------------------------------------------------

class TwoFactorChallenge(CamelModel):
    """Returned by /auth/login in place of a Session when the account has 2FA
    enabled — the password checked out, but the session isn't open yet."""

    requires_two_factor: Literal[True] = True
    challenge_token: str


class TwoFactorLoginRequest(CamelModel):
    challenge_token: str
    code: str


class TwoFactorSetupResponse(CamelModel):
    secret: str
    otpauth_url: str


class TwoFactorVerifyRequest(CamelModel):
    code: str


class TwoFactorDisableRequest(CamelModel):
    password: str


class MessageResponse(CamelModel):
    message: str


# ---------------------------------------------------------------------------
# Documents / Upload
# ---------------------------------------------------------------------------

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
    # The AI writer's lifecycle for *this* proposal: idle | drafting | drafted |
    # draft_failed. It lived on the document until migration 0005, where two
    # proposals answering one RFP overwrote each other's progress.
    drafting_status: str
    drafting_failure_reason: Optional[str] = None
    total_requirements: int
    addressed_requirements: int
    partial_requirements: int
    missing_requirements: int


class Requirement(CamelModel):
    id: str
    # The RFP this was extracted from. Named documentId to match Proposal.documentId
    # — it is an rfp_id, and calling it proposalId (as it was) is what let the
    # two id spaces be confused in the first place (GAP_ANALYSIS §1.2).
    document_id: str
    number: int
    section: str
    text: str
    category: RequirementCategory
    type: RequirementType
    compliance_status: ComplianceStatus
    # Concrete terms (certifications, standards, clause numbers) for locating
    # past-performance evidence for this requirement — from the extractor, not
    # user-editable via RequirementUpdate below.
    search_keywords: list[str] = []
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
    # Sections belong to the proposal, not the document behind it — two
    # proposals answering one RFP each own their own drafts.
    proposal_id: str
    title: str
    content: str
    status: SectionStatus
    word_count: int
    ai_confidence_score: float
    ai_flags: list[AIFlag] = []
    mapped_requirement_ids: list[str] = []
    reference_tags: list[str] = []
    # Compliance critic's unresolved feedback when the section is needs_review.
    review_notes: Optional[str] = None
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


class DraftRequest(CamelModel):
    """Optional knowledge-base pre-filter for a drafting run — see
    retrieval.search_similar. All fields optional and free-text (not a fixed
    enum, matching HistoryIngestRequest's tags); omitting the body entirely
    (or every field) means no filtering, unchanged from before this existed.
    """

    industry: Optional[str] = None
    document_type: Optional[str] = None
    outcome: Optional[str] = None


class HistoryIngestRequest(CamelModel):
    source_name: str
    content: str
    # Pre-filter tags applied to every chunk from this source (see
    # retrieval.search_similar) — e.g. industry="Marine Engineering",
    # document_type="past_performance"|"case_study"|"resume"|
    # "capability_statement", outcome="won"|"lost". All optional; free-text,
    # not a fixed enum, matching extracted_requirements.category's convention.
    industry: Optional[str] = None
    document_type: Optional[str] = None
    outcome: Optional[str] = None


class HistorySource(CamelModel):
    source_name: str
    chunks: int
    created_at: str
    industry: Optional[str] = None
    document_type: Optional[str] = None
    outcome: Optional[str] = None


class HistoryIngestResponse(CamelModel):
    source_name: str
    chunks: int


# ---------------------------------------------------------------------------
# Proposal write-side (create / update) — persisted in the proposals table
# ---------------------------------------------------------------------------

class ProposalCreate(CamelModel):
    """Partial<Proposal> from the client's `proposalsApi.create`.

    Every field is optional so the frontend can create a shell proposal and
    fill it in later. `document_id` links the created proposal to an already
    uploaded/ingested RFP.
    """

    title: Optional[str] = None
    solicitation_number: Optional[str] = None
    agency: Optional[str] = None
    due_date: Optional[str] = None
    document_id: Optional[str] = None
    contract_type: Optional[str] = None
    naics_code: Optional[str] = None
    naics_description: Optional[str] = None
    pricing_model: Optional[str] = None
    target_profit_margin: Optional[float] = None
    drafting_level: Optional[Literal["technical", "executive"]] = None
    tone: Optional[str] = None
    page_limit: Optional[int] = None


class ProposalUpdate(ProposalCreate):
    """Same optional field set as create; used by `proposalsApi.update` (PATCH)."""

    status: Optional[ProposalStatus] = None


# ---------------------------------------------------------------------------
# Company profile (Story: /profile) — persisted in the company_profiles table
# ---------------------------------------------------------------------------

class PastPerformance(CamelModel):
    id: str
    contract_number: str
    agency: str
    value: float
    scope: str
    period: str


class CompanyProfile(CamelModel):
    id: str
    legal_name: str = ""
    duns_number: str = ""
    uei_number: str = ""
    primary_address: str = ""
    cage_code: str = ""
    naics_code: str = ""
    naics_description: str = ""
    cmmc_level: str = ""
    socio_economic_status: list[str] = []
    annual_revenue: float = 0
    fringe_rate: float = 0
    overhead_rate: float = 0
    ga_rate: float = 0
    capabilities_overview: str = ""
    certifications: list[str] = []
    security_clearance: str = ""
    past_performance: list[PastPerformance] = []
    updated_at: str


class CompanyProfileUpdate(CamelModel):
    """Partial<CompanyProfile> accepted by PUT /profile."""

    legal_name: Optional[str] = None
    duns_number: Optional[str] = None
    uei_number: Optional[str] = None
    primary_address: Optional[str] = None
    cage_code: Optional[str] = None
    naics_code: Optional[str] = None
    naics_description: Optional[str] = None
    cmmc_level: Optional[str] = None
    socio_economic_status: Optional[list[str]] = None
    annual_revenue: Optional[float] = None
    fringe_rate: Optional[float] = None
    overhead_rate: Optional[float] = None
    ga_rate: Optional[float] = None
    capabilities_overview: Optional[str] = None
    certifications: Optional[list[str]] = None
    security_clearance: Optional[str] = None
    past_performance: Optional[list[PastPerformance]] = None


# ---------------------------------------------------------------------------
# Compliance matrix (GET /proposals/{id}/compliance) — real, derived from
# extracted_requirements via workspace_service.
# ---------------------------------------------------------------------------

class ComplianceCounts(CamelModel):
    all: int
    addressed: int
    partial: int
    missing: int
    na: int


class ComplianceMatrix(CamelModel):
    proposal_id: str
    compliance_score: int
    counts: ComplianceCounts
    requirements: list[Requirement]


# ---------------------------------------------------------------------------
# Pre-export integrity checks (GET /proposals/{id}/integrity) — derived from
# the compliance matrix + sections.
# ---------------------------------------------------------------------------

IntegrityStatus = Literal["verified", "review_required", "missing"]


class IntegrityItem(CamelModel):
    id: str
    label: str
    status: IntegrityStatus


# ---------------------------------------------------------------------------
# Exports (POST /exports, GET /exports/{id}) — persisted in the export_jobs table
# ---------------------------------------------------------------------------

ExportFormat = Literal["pdf", "docx", "xlsx", "zip"]
ExportStatus = Literal["pending", "generating", "ready", "failed"]


class ExportCreateRequest(CamelModel):
    # Typed as UUID so request validation rejects a malformed id with a 422,
    # matching every other route that takes one. Parsing it by hand here meant
    # bad input was reported as "Proposal not found".
    proposal_id: UUID
    format: ExportFormat


class ExportJob(CamelModel):
    id: str
    proposal_id: str
    format: ExportFormat
    status: ExportStatus
    download_url: Optional[str] = None
    created_at: str
    expires_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Pipeline progress stream (GET /proposals/{id}/pipeline/stream, SSE)
# ---------------------------------------------------------------------------

PipelineStepStatus = Literal["pending", "running", "completed", "failed"]
PipelineRunStatus = Literal["idle", "running", "completed", "failed"]


class PipelineStep(CamelModel):
    id: str
    label: str
    description: str
    status: PipelineStepStatus
    completed_at: Optional[str] = None
    meta: Optional[str] = None


class Pipeline(CamelModel):
    proposal_id: str
    status: PipelineRunStatus
    overall_progress: int
    steps: list[PipelineStep]
    started_at: str
    completed_at: Optional[str] = None
    status_message: Optional[str] = None
