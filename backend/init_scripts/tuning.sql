-- Sprint 4.4 — index tuning. Runs after init_schema.sql and rag_schema.sql.

-- Speed up the compliance-grid filters (status) and section→requirement joins.
CREATE INDEX IF NOT EXISTS idx_requirements_status
    ON extracted_requirements(compliance_status);
CREATE INDEX IF NOT EXISTS idx_requirements_rfp_created
    ON extracted_requirements(rfp_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sections_requirement
    ON proposal_sections(requirement_id);

-- Tenant lookups on uploads (ownership checks on every workspace request).
CREATE INDEX IF NOT EXISTS idx_rfp_documents_uploaded_by
    ON rfp_documents(uploaded_by);

-- Refresh planner statistics so the new indexes are used immediately.
ANALYZE extracted_requirements;
ANALYZE proposal_sections;
ANALYZE historical_chunks;
