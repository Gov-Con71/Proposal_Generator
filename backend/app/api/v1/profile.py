"""Company-profile endpoints (Sprint 5).

    GET /profile  → the authenticated tenant's company profile
    PUT /profile  → merge a partial update and return the saved profile

Backed by profile_service (persisted in the company_profiles table, one row per
tenant). Tenant-scoped via the JWT.
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user_id, require_writer
from app.models.contract import CompanyProfile, CompanyProfileUpdate
from app.services import profile_service

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("", response_model=CompanyProfile, summary="Get the tenant's company profile")
def get_profile(user_id: UUID = Depends(get_current_user_id)) -> CompanyProfile:
    return profile_service.get_profile(user_id)


@router.put("", response_model=CompanyProfile, summary="Create or update the company profile", dependencies=[Depends(require_writer)])
def save_profile(
    patch: CompanyProfileUpdate, user_id: UUID = Depends(get_current_user_id)
) -> CompanyProfile:
    return profile_service.save_profile(user_id, patch)
