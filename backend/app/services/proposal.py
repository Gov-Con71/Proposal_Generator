import psycopg2
from app.models.schemas import ProposalCreate

class ProposalService:
    def __init__(self, db_url: str):
        self.db_url = db_url

    def create_rfp_record(self, proposal_in: ProposalCreate) -> dict:
        """Executes business persistence logic matching the streamlined schema."""
        query = """
        INSERT INTO rfp_documents (uploaded_by, file_name, s3_storage_key, processing_status)
        VALUES (%s, %s, %s, 'pending') 
        RETURNING rfp_id, file_name, processing_status;
        """
        
        dummy_s3_key = f"uploads/{proposal_in.uploaded_by}/{proposal_in.file_name}"
        
        with psycopg2.connect(self.db_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query, 
                    (
                        str(proposal_in.uploaded_by) if proposal_in.uploaded_by else None, 
                        proposal_in.file_name, 
                        dummy_s3_key
                    )
                )
                record = cursor.fetchone()
                
                connection.commit() 
                
        return {
            "rfp_id": record[0],
            "file_name": record[1],
            "processing_status": record[2]
        }
