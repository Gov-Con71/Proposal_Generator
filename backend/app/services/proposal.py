import psycopg2
from app.models.schemas import ProposalCreate

class ProposalService:
    def __init__(self, db_url: str):
        self.db_url = db_url

    def create_rfp_record(self, proposal_in: ProposalCreate) -> dict:
        """Executes business persistence logic matching the streamlined schema."""
        connection = psycopg2.connect(self.db_url)
        cursor = connection.cursor()
        
        # Updated to map exactly to your new table parameters (using uploaded_by instead of workspace)
        query = """
        INSERT INTO rfp_documents (uploaded_by, file_name, s3_storage_key, processing_status)
        VALUES (%s, %s, %s, 'pending') 
        RETURNING rfp_id, file_name, processing_status;
        """
        
        # Updated your S3 key mapping strategy to group files cleanly by user_id instead of workspace
        dummy_s3_key = f"uploads/{proposal_in.uploaded_by}/{proposal_in.file_name}"
        
        # CRITICAL FIX: Wrapped query parameters inside a tuple context ( ... ) 
        # so psycopg2 parses the variables matching the %s sequence parameters safely.
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
        cursor.close()
        connection.close()
        
        return {
            "rfp_id": record[0],
            "file_name": record[1],
            "processing_status": record[2]
        }