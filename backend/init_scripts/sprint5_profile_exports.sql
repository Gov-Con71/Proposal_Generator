-- Sprint 5 — company profile + export jobs.
-- Runs after init_schema.sql (needs the users table). Idempotent so it can be
-- re-applied to an existing database.

-- Company profile: one row per tenant (keyed by the owning user, matching the
-- history_service tenancy model). List/object fields are stored as JSONB.
CREATE TABLE IF NOT EXISTS company_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE, -- tenant boundary
    legal_name VARCHAR(255) NOT NULL DEFAULT '',
    duns_number VARCHAR(50) NOT NULL DEFAULT '',
    uei_number VARCHAR(50) NOT NULL DEFAULT '',
    primary_address TEXT NOT NULL DEFAULT '',
    cage_code VARCHAR(50) NOT NULL DEFAULT '',
    naics_code VARCHAR(50) NOT NULL DEFAULT '',
    naics_description TEXT NOT NULL DEFAULT '',
    cmmc_level VARCHAR(50) NOT NULL DEFAULT '',
    socio_economic_status JSONB NOT NULL DEFAULT '[]',   -- list[str]
    annual_revenue NUMERIC NOT NULL DEFAULT 0,
    fringe_rate NUMERIC NOT NULL DEFAULT 0,
    overhead_rate NUMERIC NOT NULL DEFAULT 0,
    ga_rate NUMERIC NOT NULL DEFAULT 0,
    capabilities_overview TEXT NOT NULL DEFAULT '',
    certifications JSONB NOT NULL DEFAULT '[]',           -- list[str]
    security_clearance VARCHAR(100) NOT NULL DEFAULT '',
    past_performance JSONB NOT NULL DEFAULT '[]',          -- list[PastPerformance]
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Export jobs: render a proposal to a downloadable artifact. proposal_id is a
-- plain string for now (no proposals table yet); tighten to a FK once it lands.
CREATE TABLE IF NOT EXISTS export_jobs (
    job_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_by UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, -- tenant boundary
    proposal_id VARCHAR(255) NOT NULL,
    format VARCHAR(20) NOT NULL,          -- pdf | docx | xlsx | zip
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | generating | ready | failed
    download_url VARCHAR(512),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_export_jobs_created_by ON export_jobs(created_by);

-- Rendered-artifact location (S3) + failure reason, populated by the async
-- render_export worker task. Added via ALTER so this file stays idempotent.
ALTER TABLE export_jobs ADD COLUMN IF NOT EXISTS s3_key VARCHAR(512);
ALTER TABLE export_jobs ADD COLUMN IF NOT EXISTS error TEXT;
