import psycopg2
from uuid import uuid4
from app.core.config import settings

def test_upload_rfp_metadata_endpoint(test_client):
    """Validates full integration round-trips with automated DB cleanup."""
    mock_user_id = str(uuid4())
    mock_email = f"test_user_{uuid4().hex[:6]}@example.com"
    
    # Setup: Insert parent user record
    connection = psycopg2.connect(settings.database_url)
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO users (user_id, email, password_hash, first_name, last_name)
        VALUES (%s, %s, 'mock_hash_value', 'Test', 'Developer');
        """,
        (mock_user_id, mock_email)
    )
    connection.commit()

    try:
        mock_payload = {
            "file_name": "dod_military_rfp.pdf",
            "uploaded_by": mock_user_id
        }
        
        # Action
        response = test_client.post("/api/v1/proposals/", json=mock_payload)
        
        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["file_name"] == "dod_military_rfp.pdf"
        assert data["processing_status"] == "pending"
        assert "rfp_id" in data

    finally:
        # Teardown: Clean up the generated user (Cascades automatically to delete the RFP)
        cursor.execute("DELETE FROM users WHERE user_id = %s;", (mock_user_id,))
        connection.commit()
        cursor.close()
        connection.close()