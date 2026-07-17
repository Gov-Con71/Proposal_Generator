"""Compliance-matrix endpoint (real, Sprint 3 read-side).

    GET /proposals/{proposal_id}/compliance  → status roll-up + score + requirements

Takes a proposal id like the rest of the namespace and resolves it to the
underlying RFP (GAP_ANALYSIS.md §1.2). Tenant-scoped through proposal ownership.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core import cache
from app.core.deps import get_current_user_id
from app.models.contract import ComplianceMatrix
from app.services import compliance_service, proposals_service, workspace_service as ws

router = APIRouter(tags=["Workspace"])


@router.get("/proposals/{proposal_id}/compliance", response_model=ComplianceMatrix)
def get_compliance_matrix(
    proposal_id: UUID, user_id: UUID = Depends(get_current_user_id)
) -> ComplianceMatrix:
    try:
        rfp_id = proposals_service.rfp_for_proposal(proposal_id, user_id)
    except proposals_service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except proposals_service.NoLinkedDocumentError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This proposal has no ingested RFP yet. Upload one to build its compliance matrix.",
        ) from exc

    key = cache.compliance_key(user_id, rfp_id)
    cached = cache.cache_get(key)
    if cached is not None:
        return cached
    try:
        matrix = compliance_service.build_matrix(rfp_id, user_id, proposal_id)
    except ws.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    cache.cache_set(key, matrix.model_dump(by_alias=True))
    return matrix
