"""Workspace CRUD + RAG generation endpoints (Stories 3.4 / 3.5).

Real requirement/section reads and edits (paths mirror the frontend client),
plus the context-aware draft writer. All routes are JWT-secured and tenant-
scoped via proposal ownership.

Addressing: every `/proposals/{proposal_id}/…` route takes a **proposal id**,
matching the rest of that namespace (CRUD, integrity, exports). Requirements and
sections are stored against the underlying `rfp_id`; `_rfp(...)` is the only
place that translates. Previously these routes took an rfp_id directly while the
dashboard linked a proposal id, so every workspace opened from the dashboard
404'd (GAP_ANALYSIS.md §1.2).
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status, Header

from app.core import cache
from app.services import dispatch_service, drafting_runs
from app.core.deps import get_current_user_id, require_writer
from app.models.contract import (
    CamelModel,
    DraftRequest,
    GenerateSectionRequest,
    ProposalSection,
    Requirement,
    RequirementUpdate,
    SectionCreate,
    SectionUpdate,
)
from app.services import document_service as docs
from app.services import draft_writer, proposals_service, trajectory_service, workspace_service as ws
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Workspace"])


class DraftQueuedResponse(CamelModel):
    proposal_id: str
    rfp_id: str
    # The proposal's own drafting lifecycle, not the document's ingestion
    # status — see migration 0005.
    drafting_status: str
    requirements_count: int


class SectionTrajectory(CamelModel):
    """One section's full attempt history for a drafting run.

    Unlike `ProposalSection.reviewNotes` (the critic's *latest* feedback only),
    `attempts` is every round in order — see migration 0016.
    """

    section_id: Optional[str] = None
    section_title: str
    outline_index: int
    final_status: Optional[str] = None
    stalled: bool
    attempt_count: int
    attempts: list[dict]


class DraftingTrajectoryResponse(CamelModel):
    run_id: str
    proposal_id: str
    sections: list[SectionTrajectory]


def _guard(fn, *args):
    try:
        return fn(*args)
    except ws.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc


def _rfp(proposal_id: UUID, user_id: UUID) -> UUID:
    """Resolves the addressed proposal to the document its content hangs off."""
    try:
        return proposals_service.rfp_for_proposal(proposal_id, user_id)
    except proposals_service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except proposals_service.NoLinkedDocumentError as exc:
        # The proposal is real, it just has no RFP yet — a 409 says "not usable
        # yet" where a 404 would wrongly imply the proposal doesn't exist.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This proposal has no ingested RFP yet. Upload one to populate its workspace.",
        ) from exc


# --- requirements -----------------------------------------------------------

@router.get("/proposals/{proposal_id}/requirements", response_model=list[Requirement])
def list_requirements(proposal_id: UUID, user_id: UUID = Depends(get_current_user_id)):
    rfp_id = _rfp(proposal_id, user_id)
    # Cache stays keyed on rfp_id: requirements are per-document, so two
    # proposals on one RFP share the entry rather than duplicating it.
    key = cache.requirements_key(user_id, rfp_id)
    cached = cache.cache_get(key)
    if cached is not None:
        return cached
    result = _guard(ws.list_requirements, rfp_id, user_id)
    cache.cache_set(key, [r.model_dump(by_alias=True) for r in result])
    return result


@router.patch("/requirements/{requirement_id}", response_model=Requirement, dependencies=[Depends(require_writer)])
def update_requirement(
    requirement_id: UUID,
    patch: RequirementUpdate,
    user_id: UUID = Depends(get_current_user_id),
):
    result = _guard(ws.update_requirement, requirement_id, user_id, patch)
    cache.cache_delete(
        cache.requirements_key(user_id, result.document_id),
        cache.compliance_key(user_id, result.document_id),
    )
    return result


@router.delete("/requirements/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_writer)])
def delete_requirement(
    requirement_id: UUID, user_id: UUID = Depends(get_current_user_id)
):
    rfp_id = _guard(ws.delete_requirement, requirement_id, user_id)
    cache.cache_delete(
        cache.requirements_key(user_id, rfp_id),
        cache.compliance_key(user_id, rfp_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- sections ---------------------------------------------------------------

def _invalidate_sections(user_id: UUID, section: ProposalSection) -> None:
    cache.cache_delete(cache.sections_key(user_id, section.proposal_id))


def _grounding(result: dict) -> tuple[float, list[str]]:
    """(confidence, reference tags) for a single-section RAG draft.

    The same derivation the full drafting agent applies, so a section written
    one at a time is scored on the same basis as one written by a full run.
    """
    citations = result.get("citations") or []
    return (
        draft_writer.grounding_confidence(citations),
        draft_writer.reference_tags(citations),
    )


@router.get("/proposals/{proposal_id}/sections", response_model=list[ProposalSection])
def list_sections(proposal_id: UUID, user_id: UUID = Depends(get_current_user_id)):
    # No _rfp() translation: sections are keyed on the proposal directly, so the
    # cache entry is per-proposal too. Two proposals on one RFP must not share it.
    key = cache.sections_key(user_id, proposal_id)
    cached = cache.cache_get(key)
    if cached is not None:
        return cached
    result = _guard(ws.list_sections, proposal_id, user_id)
    cache.cache_set(key, [s.model_dump(by_alias=True) for s in result])
    return result


@router.post(
    "/proposals/{proposal_id}/sections",
    response_model=ProposalSection,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_writer)],
)
def create_section(
    proposal_id: UUID, payload: SectionCreate, user_id: UUID = Depends(get_current_user_id)
):
    result = _guard(ws.create_section, proposal_id, user_id, payload.title, payload.requirement_id)
    _invalidate_sections(user_id, result)
    return result


@router.get("/sections/{section_id}", response_model=ProposalSection)
def get_section(section_id: UUID, user_id: UUID = Depends(get_current_user_id)):
    return _guard(ws.get_section, section_id, user_id)


@router.patch("/sections/{section_id}", response_model=ProposalSection, dependencies=[Depends(require_writer)])
def update_section(
    section_id: UUID, patch: SectionUpdate, user_id: UUID = Depends(get_current_user_id)
):
    result = _guard(ws.update_section, section_id, user_id, patch.content, patch.status)
    _invalidate_sections(user_id, result)
    return result


@router.post("/sections/{section_id}/approve", response_model=ProposalSection, dependencies=[Depends(require_writer)])
def approve_section(section_id: UUID, user_id: UUID = Depends(get_current_user_id)):
    result = _guard(ws.update_section, section_id, user_id, None, "approved")
    _invalidate_sections(user_id, result)
    return result


@router.post("/sections/{section_id}/regenerate", response_model=ProposalSection, dependencies=[Depends(require_writer)])
def regenerate_section(section_id: UUID, user_id: UUID = Depends(get_current_user_id)):
    """Re-runs the RAG draft writer for an existing section."""
    owned = _guard(ws.get_section, section_id, user_id)
    requirement_text = _guard(ws.requirement_text_for_section, section_id, user_id)
    result = draft_writer.generate_draft(user_id, requirement_text, proposal_id=UUID(owned.proposal_id))
    section = ws.save_generated_draft(section_id, result["content"], *_grounding(result))
    _invalidate_sections(user_id, section)
    return section


@router.post(
    "/proposals/{proposal_id}/draft",
    response_model=DraftQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_writer)],
    summary="Generate a full proposal draft with the AI writer agent (async)",
)
def draft_proposal(
    proposal_id: UUID,
    payload: Optional[DraftRequest] = None,
    user_id: UUID = Depends(get_current_user_id),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> DraftQueuedResponse:
    """Queues the drafting agent for one proposal.

    Addressed by proposal, not by document (it was `POST /documents/{rfp_id}/draft`
    until sections became proposal-scoped): drafting writes a proposal's own
    sections, and one RFP can back several proposals.

    An optional JSON body (`DraftRequest`) narrows every section's knowledge-
    base retrieval to matching `industry`/`documentType`/`outcome` tags (see
    `retrieval.search_similar`) — e.g. draft using only past performance tagged
    `outcome: "won"`. Omitting the body (or any of its fields) drafts unfiltered,
    exactly as before this existed.

    Poll `GET /proposals/{proposalId}` for `draftingStatus` ('drafting' →
    'drafted', or 'draft_failed' with `draftingFailureReason`) and
    `GET /proposals/{proposalId}/sections` for the results. That flag moved off
    the document in migration 0005 — polling `GET /documents/{rfpId}` would
    report whichever bid on this RFP happened to write last.
    """
    rfp_id = _rfp(proposal_id, user_id)  # 404/409 + ownership in one place
    requirements_count = docs.count_requirements(rfp_id)
    if requirements_count == 0:
        # Drafting is grounded in the extracted compliance matrix.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No requirements extracted yet — ingest the RFP before drafting.",
        )
    # Set here rather than only in the worker: between the 202 and the worker
    # picking the job up, a client polling for 'drafting' would otherwise read
    # the previous run's 'drafted' and stop, concluding instantly that a draft
    # it just requested was already finished.
    # Authorised here, before queueing: the worker resolves the proposal without
    # a tenant check because it has no request identity. Filters go through
    # kwargs, not args, so the common (unfiltered) call's args stay exactly
    # [proposal_id] — no shape change for the overwhelming majority of callers.
    retrieval_filters = (
        {
            k: v
            for k, v in {
                "industry": payload.industry,
                "document_type": payload.document_type,
                "outcome": payload.outcome,
            }.items()
            if v is not None
        }
        if payload
        else {}
    )
    try:
        with dispatch_service.request(user_id, 'draft_proposal', idempotency_key, {'proposal_id': str(proposal_id), 'filters': retrieval_filters}) as (previous, request_hash):
            if previous:
                return DraftQueuedResponse.model_validate(previous)
            run_id = drafting_runs.create(proposal_id)
            response = DraftQueuedResponse(proposal_id=str(proposal_id), rfp_id=str(rfp_id),
                                           drafting_status='drafting', requirements_count=requirements_count)
            dispatch_service.enqueue(user_id, 'draft_proposal', proposal_id,
                                     {'run_id': run_id, 'retrieval_filters': retrieval_filters},
                                     response.model_dump(mode='json', by_alias=True), request_hash, idempotency_key)
        return response
    except drafting_runs.DraftConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get(
    "/proposals/{proposal_id}/drafting/trajectory",
    response_model=DraftingTrajectoryResponse,
    summary="Get the per-attempt trajectory of a drafting run (debugging)",
)
def get_drafting_trajectory(
    proposal_id: UUID,
    run_id: Optional[UUID] = None,
    user_id: UUID = Depends(get_current_user_id),
) -> DraftingTrajectoryResponse:
    """Every section's full draft/critic attempt history for one drafting run.

    `run_id` omitted resolves to the proposal's most recent run. Unlike
    `GET /sections`, which only ever shows the final saved content and the
    critic's latest feedback, this surfaces every revision round — what was
    drafted, what the critic flagged, and whether the loop stalled — for
    diagnosing why a section needed review or never saved at all.
    """
    try:
        proposals_service.get_proposal(proposal_id, user_id)
    except proposals_service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc

    trajectory = trajectory_service.get_trajectory(proposal_id, run_id)
    if trajectory is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No drafting run recorded for this proposal."
        )
    return DraftingTrajectoryResponse.model_validate(trajectory)


@router.post(
    "/proposals/{proposal_id}/sections/generate",
    response_model=ProposalSection,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_writer)],
)
def generate_section(
    proposal_id: UUID,
    payload: GenerateSectionRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    """Creates a new section for a requirement and fills it with a RAG draft."""
    rfp_id = _rfp(proposal_id, user_id)
    # Requirements are still per-document; only the section it produces is
    # per-proposal. list_requirements enforces rfp ownership for this tenant.
    requirements = _guard(ws.list_requirements, rfp_id, user_id)
    match = next((r for r in requirements if r.id == payload.requirement_id), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    title = payload.title or f"Response to {match.section or 'requirement'}"
    section = ws.create_section(proposal_id, user_id, title, payload.requirement_id)
    result = draft_writer.generate_draft(user_id, match.text, proposal_id=proposal_id)
    section = ws.save_generated_draft(UUID(section.id), result["content"], *_grounding(result))
    _invalidate_sections(user_id, section)
    return section
