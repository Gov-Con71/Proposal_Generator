from pydantic import BaseModel
from typing import Optional
from uuid import UUID

# This defines what the test payload must contain
class ProposalCreate(BaseModel):
    file_name: str
    uploaded_by: Optional[UUID] = None

# This defines what the database service must return to the test client
class ProposalResponse(BaseModel):
    rfp_id: UUID
    file_name: str
    processing_status: str

    # Pydantic V2 syntax compatibility
    model_config = {"from_attributes": True}