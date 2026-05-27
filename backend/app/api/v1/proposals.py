from fastapi import APIRouter, Depends
from app.models.schemas import ProposalCreate, ProposalResponse
from app.services.proposal import ProposalService
from app.core.config import settings

router = APIRouter(prefix="/proposals", tags=["Proposals"])

# Dependency Injection function to supply our decoupled service layer
def get_proposal_service() -> ProposalService:
    return ProposalService(db_url=settings.database_url)

@router.post("/", response_model=ProposalResponse)
def upload_rfp_metadata(
    payload: ProposalCreate, 
    service: ProposalService = Depends(get_proposal_service)
):
    """Thin API routing layer communicating explicitly through the Service layer."""
    result = service.create_rfp_record(payload)
    return result