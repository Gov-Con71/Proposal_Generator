from pydantic import BaseModel, Field
from uuid import UUID

class ProposalCreate(BaseModel):
    file_name: str = Field(..., description="The original name of the uploaded RFP file")
    uploaded_by: UUID = Field(..., description="The unique ID of the user uploading the document")

class ProposalResponse(BaseModel):
    rfp_id: UUID = Field(..., description="The auto-generated database primary key for the RFP")
    file_name: str
    processing_status: str

    # Pydantic V2 configuration mapping database/ORM attributes seamlessly
    model_config = {"from_attributes": True}
