-- Sprint 6 — real proposals table + tighten the export_jobs FK.
-- Runs after init_schema.sql (users, rfp_documents) and sprint5_profile_exports.sql
-- (export_jobs). Idempotent so it can be re-applied to an existing database.

-- A proposal is a tenant-owned bid, optionally linked to an ingested RFP
-- (rfp_id) from which its requirements/sections/compliance are derived.
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owned_by UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, -- tenant boundary
    rfp_id UUID REFERENCES rfp_documents(rfp_id) ON DELETE SET NULL,     -- linked ingested RFP
    title VARCHAR(255) NOT NULL DEFAULT '',
    solicitation_number VARCHAR(255) NOT NULL DEFAULT '',
    agency VARCHAR(255) NOT NULL DEFAULT '',
    due_date VARCHAR(50) NOT NULL DEFAULT '',
    compliance_score INT NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    contract_type VARCHAR(100) NOT NULL DEFAULT '',
    naics_code VARCHAR(50) NOT NULL DEFAULT '',
    naics_description TEXT NOT NULL DEFAULT '',
    pricing_model VARCHAR(100) NOT NULL DEFAULT '',
    target_profit_margin NUMERIC NOT NULL DEFAULT 0,
    drafting_level VARCHAR(20) NOT NULL DEFAULT 'technical',
    tone VARCHAR(50) NOT NULL DEFAULT 'formal',
    page_limit INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_proposals_owned_by ON proposals(owned_by);

-- Tighten export_jobs.proposal_id: VARCHAR → UUID FK → proposals(proposal_id).
-- Guarded so re-runs are no-ops. Dev rows carry non-UUID scaffold ids
-- ('mock-1', ...); drop them before converting the column type.
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'export_jobs' AND column_name = 'proposal_id') <> 'uuid' THEN
        DELETE FROM export_jobs WHERE proposal_id !~ '^[0-9a-fA-F-]{36}$';
        ALTER TABLE export_jobs ALTER COLUMN proposal_id TYPE UUID USING proposal_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_export_jobs_proposal') THEN
        ALTER TABLE export_jobs
            ADD CONSTRAINT fk_export_jobs_proposal
            FOREIGN KEY (proposal_id) REFERENCES proposals(proposal_id) ON DELETE CASCADE;
    END IF;
END $$;
