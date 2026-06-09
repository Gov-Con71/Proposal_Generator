from fastapi import APIRouter, Depends, HTTPException, status
from app.models.schemas import ProposalCreate, ProposalResponse
from app.services.proposal import ProposalService
from app.core.config import settings

router = APIRouter(prefix="/proposals", tags=["Proposals"])

def get_proposal_service() -> ProposalService:
    return ProposalService(db_url=settings.database_url)

@router.post(
    "/", 
    response_model=ProposalResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Upload RFP Metadata"
)
def upload_rfp_metadata(
    payload: ProposalCreate, 
    service: ProposalService = Depends(get_proposal_service)
):
    """Thin API routing layer communicating explicitly through the Service layer."""
    try:
        result = service.create_rfp_record(payload)
        return result
    except ForeignKeyViolation as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The specified uploaded_by user_id does not exist in the platform."
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing the proposal."
        )
