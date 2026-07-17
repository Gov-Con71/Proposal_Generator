"""Workspace CRUD + RAG generation endpoints (Stories 3.4 / 3.5).

Real requirement/section reads and edits (paths mirror the frontend client),
plus the context-aware draft writer. All routes are JWT-secured and tenant-
scoped via rfp_documents ownership.
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
from app.services import draft_writer, workspace_service as ws

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Workspace"])


def _guard(fn, *args):
    try:
        return fn(*args)
    except ws.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc


# --- requirements -----------------------------------------------------------

@router.get("/proposals/{rfp_id}/requirements", response_model=list[Requirement])
def list_requirements(rfp_id: UUID, user_id: UUID = Depends(get_current_user_id)):
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
        cache.requirements_key(user_id, result.proposal_id),
        cache.compliance_key(user_id, result.proposal_id),
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


@router.get("/proposals/{rfp_id}/sections", response_model=list[ProposalSection])
def list_sections(rfp_id: UUID, user_id: UUID = Depends(get_current_user_id)):
    key = cache.sections_key(user_id, rfp_id)
    cached = cache.cache_get(key)
    if cached is not None:
        return cached
    result = _guard(ws.list_sections, rfp_id, user_id)
    cache.cache_set(key, [s.model_dump(by_alias=True) for s in result])
    return result


@router.post(
    "/proposals/{rfp_id}/sections",
    response_model=ProposalSection,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_writer)],
)
def create_section(
    rfp_id: UUID, payload: SectionCreate, user_id: UUID = Depends(get_current_user_id)
):
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
    "/proposals/{rfp_id}/sections/generate",
    response_model=ProposalSection,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_writer)],
)
def generate_section(
    rfp_id: UUID,
    payload: GenerateSectionRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    """Creates a new section for a requirement and fills it with a RAG draft."""
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
