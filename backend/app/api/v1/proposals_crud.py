"""Real proposal CRUD (Sprint 6).

DB-backed replacement for the Story 1.3 mock proposals router. Mounted at
`/proposals` (no /api/v1 prefix) so paths match the frontend client
(`proposalsApi` in proposalai-frontend/lib/api). Every route is JWT-secured and
tenant-scoped via proposals.owned_by.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.deps import get_current_user_id, require_writer
from app.models.contract import (
    IntegrityItem,
    Proposal,
    ProposalCreate,
    ProposalSummary,
    ProposalUpdate,
)
from app.services import compliance_service, proposals_service as proposals, workspace_service as ws

router = APIRouter(prefix="/proposals", tags=["Proposals"])


def _not_found(exc: proposals.NotFoundError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found.")


@router.get("", response_model=list[ProposalSummary], summary="List the tenant's proposals")
def list_proposals(user_id: UUID = Depends(get_current_user_id)) -> list[ProposalSummary]:
    return proposals.list_proposals(user_id)


@router.get("/{proposal_id}", response_model=Proposal, summary="Get proposal detail")
def get_proposal(proposal_id: UUID, user_id: UUID = Depends(get_current_user_id)) -> Proposal:
    try:
        return proposals.get_proposal(proposal_id, user_id)
    except proposals.NotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("", response_model=Proposal, status_code=status.HTTP_201_CREATED, summary="Create a proposal", dependencies=[Depends(require_writer)])
def create_proposal(
    payload: ProposalCreate, user_id: UUID = Depends(get_current_user_id)
) -> Proposal:
    try:
        return proposals.create_proposal(user_id, payload)
    except proposals.InvalidLinkError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.patch("/{proposal_id}", response_model=Proposal, summary="Update a proposal", dependencies=[Depends(require_writer)])
def update_proposal(
    proposal_id: UUID, payload: ProposalUpdate, user_id: UUID = Depends(get_current_user_id)
) -> Proposal:
    try:
        return proposals.update_proposal(proposal_id, user_id, payload)
    except proposals.NotFoundError as exc:
        raise _not_found(exc) from exc
    except proposals.InvalidLinkError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.delete("/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a proposal", dependencies=[Depends(require_writer)])
def delete_proposal(proposal_id: UUID, user_id: UUID = Depends(get_current_user_id)) -> Response:
    try:
        proposals.delete_proposal(proposal_id, user_id)
    except proposals.NotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{proposal_id}/integrity",
    response_model=list[IntegrityItem],
    summary="Pre-export integrity checklist (derived from compliance + sections)",
)
def get_integrity(
    proposal_id: UUID, user_id: UUID = Depends(get_current_user_id)
) -> list[IntegrityItem]:
    try:
        proposal = proposals.get_proposal(proposal_id, user_id)
    except proposals.NotFoundError as exc:
        raise _not_found(exc) from exc

    if not proposal.document_id:  # no linked RFP yet → nothing verified
        return compliance_service.empty_integrity()
    try:
        return compliance_service.build_integrity(
            UUID(proposal.document_id), proposal_id, user_id
        )
    except ws.NotFoundError:
        return compliance_service.empty_integrity()
