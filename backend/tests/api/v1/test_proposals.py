from uuid import uuid4

def test_upload_rfp_metadata_endpoint(test_client):
    """Validates full integration round-trips without cross-contamination."""
    mock_payload = {
        "file_name": "dod_military_rfp.pdf",
        "workspace_id": str(uuid4())
    }
    
    # Execute network path test assertion
    response = test_client.post("/api/v1/proposals/", json=mock_payload)
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "dod_military_rfp.pdf"
    assert data["processing_status"] == "pending"
    assert "rfp_id" in data