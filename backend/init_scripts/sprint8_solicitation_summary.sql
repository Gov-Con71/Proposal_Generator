-- Sprint 8: document-level solicitation summary.
--
-- A complementary extraction to the compliance matrix (extracted_requirements):
-- one JSON object per document capturing administrative, deadline, submission,
-- and technical-core facts, each value carrying an exact source_quote citation.
-- Written best-effort by ingestion, so NULL simply means "not extracted".
--
-- Idempotent so it is safe to re-run against an existing database.

ALTER TABLE rfp_documents
    ADD COLUMN IF NOT EXISTS solicitation_summary JSONB;
