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
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core import cache
from app.core.deps import get_current_user_id, require_writer
from app.models.contract import (
    GenerateSectionRequest,
    ProposalSection,
    Requirement,
    RequirementUpdate,
    SectionCreate,
    SectionUpdate,
)
from app.services import draft_writer, proposals_service, workspace_service as ws

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Workspace"])


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
    cache.cache_delete(cache.sections_key(user_id, section.document_id))


@router.get("/proposals/{proposal_id}/sections", response_model=list[ProposalSection])
def list_sections(proposal_id: UUID, user_id: UUID = Depends(get_current_user_id)):
    rfp_id = _rfp(proposal_id, user_id)
    key = cache.sections_key(user_id, rfp_id)
    cached = cache.cache_get(key)
    if cached is not None:
        return cached
    result = _guard(ws.list_sections, rfp_id, user_id)
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
    rfp_id = _rfp(proposal_id, user_id)
    result = _guard(ws.create_section, rfp_id, user_id, payload.title, payload.requirement_id)
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
    _guard(ws.get_section, section_id, user_id)  # ownership check
    requirement_text = ws.requirement_text_for_section(section_id)
    result = draft_writer.generate_draft(user_id, requirement_text)
    section = ws.save_generated_draft(section_id, result["content"])
    _invalidate_sections(user_id, section)
    return section


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
    # list_requirements enforces rfp ownership for this tenant.
    requirements = _guard(ws.list_requirements, rfp_id, user_id)
    match = next((r for r in requirements if r.id == payload.requirement_id), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    title = payload.title or f"Response to {match.section or 'requirement'}"
    section = ws.create_section(rfp_id, user_id, title, payload.requirement_id)
    result = draft_writer.generate_draft(user_id, match.text)
    section = ws.save_generated_draft(UUID(section.id), result["content"])
    _invalidate_sections(user_id, section)
    return section
