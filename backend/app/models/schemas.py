from pydantic import BaseModel
from uuid import UUID

# Contract when user uploads metadata
class ProposalCreate(BaseModel):
    file_name: str
    workspace_id: UUID

# Contract when system returns structured proposal state
class ProposalResponse(BaseModel):
    rfp_id: UUID
    file_name: str
    processing_status: str

    class Config:
        from_attributes = True