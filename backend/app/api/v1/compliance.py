"""Compliance-matrix endpoint (real, Sprint 3 read-side).

    GET /proposals/{rfp_id}/compliance  → status roll-up + score + requirements

Tenant-scoped through workspace_service ownership checks.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core import cache
from app.core.deps import get_current_user_id
from app.models.contract import ComplianceMatrix
from app.services import compliance_service, workspace_service as ws

router = APIRouter(tags=["Workspace"])


@router.get("/proposals/{rfp_id}/compliance", response_model=ComplianceMatrix)
def get_compliance_matrix(
    rfp_id: UUID, user_id: UUID = Depends(get_current_user_id)
) -> ComplianceMatrix:
    key = cache.compliance_key(user_id, rfp_id)
    cached = cache.cache_get(key)
    if cached is not None:
        return cached
    try:
        matrix = compliance_service.build_matrix(rfp_id, user_id)
    except ws.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    cache.cache_set(key, matrix.model_dump(by_alias=True))
    return matrix
