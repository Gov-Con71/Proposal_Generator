"""Baseline schema — squashed from init_scripts/ (Sprints 1-8).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-03

This is the whole schema as `init_scripts/*.sql` produced it, in the exact
lexicographic order Postgres applied them under `docker-entrypoint-initdb.d`:

    init_schema → rag_schema → sprint5_profile_exports → sprint6_proposals
    → sprint7_auth → sprint8_section_review_notes → sprint8_solicitation_summary
    → tuning

The SQL is inlined rather than read from `init_scripts/` at runtime. A revision
must mean the same thing forever; one that sources an external file silently
changes meaning the next time that file is edited, and the schema history stops
being reproducible.

**Idempotent throughout.** The four `CREATE TABLE`s and three `CREATE INDEX`es
that `init_schema.sql` declared bare have gained `IF NOT EXISTS`; nothing else
is altered. That lets an already-provisioned database (dev, or a container
whose entrypoint scripts already ran) adopt Alembic with either

    alembic stamp 0001_baseline   # preferred: record it, apply nothing
    alembic upgrade head          # also safe: every statement is a no-op

so migrating to Alembic needs no flag day and cannot destroy existing data.

Raw DDL, not `op.create_table`: the schema depends on pgvector, uuid-ossp,
`DO $$` blocks and expression indexes that the Alembic operations layer models
poorly, and transcribing 258 lines by hand would risk silent divergence from
the schema now running in production.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BASELINE_SQL = r"""
-- ─── init_schema.sql ────────────────────────────────────────────────────────

-- Enable critical database extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- Enables random UUID generation hooks

-- Create Users Table
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL, -- Stored securely encrypted by the backend
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create RFP Documents Table (The uploaded files tracked in S3)
CREATE TABLE IF NOT EXISTS rfp_documents (
    rfp_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    uploaded_by UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    s3_storage_key VARCHAR(512) NOT NULL, -- Points to the raw file resting inside AWS S3
    processing_status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'parsing', 'completed', 'failed'
    solicitation_summary JSONB, -- Document-level administrative/deadline/submission/technical summary (Sprint 8)
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create Extracted Requirements Table (The Core Compliance Matrix rows)
CREATE TABLE IF NOT EXISTS extracted_requirements (
    requirement_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rfp_id UUID NOT NULL REFERENCES rfp_documents(rfp_id) ON DELETE CASCADE,
    section_number VARCHAR(100), -- e.g., "Section C.3.2"
    raw_text_content TEXT NOT NULL, -- The explicit text deliverable rule pulled out by the AI shredder
    category VARCHAR(100), -- e.g., "Technical", "Security", "Past Performance"
    compliance_status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'compliant', 'exception'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create Proposal Layouts / Sections Table (The editable Rich-Text Canvas)
CREATE TABLE IF NOT EXISTS proposal_sections (
    section_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rfp_id UUID NOT NULL REFERENCES rfp_documents(rfp_id) ON DELETE CASCADE,
    requirement_id UUID REFERENCES extracted_requirements(requirement_id) ON DELETE SET NULL, -- Maps section explicitly to the rule it fulfills
    section_title VARCHAR(255) NOT NULL, -- e.g., "Technical Management Plan"
    generated_draft_content TEXT, -- The editable draft string compiled by the AI writer agent
    review_notes TEXT, -- Compliance critic's unresolved feedback when a section is saved needs_review
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Define Performance & Scalability Indexes
-- B-Tree indexes on frequent search fields to make your user dashboards load instantly
CREATE INDEX IF NOT EXISTS idx_rfps_workspace ON rfp_documents(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_requirements_rfp ON extracted_requirements(rfp_id);
CREATE INDEX IF NOT EXISTS idx_proposals_rfp ON proposal_sections(rfp_id);

-- ─── rag_schema.sql (Sprint 3 — RAG engine) ─────────────────────────────────

-- Activate pgvector (image is ankane/pgvector, so the extension is available).
CREATE EXTENSION IF NOT EXISTS vector;

-- Historical past-performance chunks: shredded, embedded, tenant-scoped.
CREATE TABLE IF NOT EXISTS historical_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    uploaded_by UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, -- tenant boundary
    source_name VARCHAR(255) NOT NULL,   -- e.g. "USCG Pump Overhaul 2024"
    content TEXT NOT NULL,               -- the raw chunk text
    embedding vector(768),               -- google-genai gemini-embedding-001, pinned to 768 dims
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_historical_chunks_user ON historical_chunks(uploaded_by);

-- Workspace editing state for draft sections (Story 3.4).
ALTER TABLE proposal_sections
    ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'draft'; -- draft|approved|needs_review|empty

-- Approximate-nearest-neighbour index over the embedding (cosine distance).
CREATE INDEX IF NOT EXISTS idx_historical_chunks_embedding
    ON historical_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ─── sprint5_profile_exports.sql ────────────────────────────────────────────

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

-- Export jobs: render a proposal to a downloadable artifact. proposal_id starts
-- as a plain string here and is tightened to a UUID FK by sprint6 below.
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
-- render_export worker task.
ALTER TABLE export_jobs ADD COLUMN IF NOT EXISTS s3_key VARCHAR(512);
ALTER TABLE export_jobs ADD COLUMN IF NOT EXISTS error TEXT;

-- ─── sprint6_proposals.sql ──────────────────────────────────────────────────

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

-- ─── sprint7_auth.sql ───────────────────────────────────────────────────────

-- A company is the organisation a user signs up under. Collected on the
-- register form, which previously discarded it.
CREATE TABLE IF NOT EXISTS companies (
    company_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Match companies case-insensitively so "Acro Inc." and "acro inc." are one org.
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_name_lower ON companies (LOWER(name));

-- Roles were hardcoded to 'analyst' in the API layer; persist them instead.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'analyst';
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES companies(company_id) ON DELETE SET NULL;

-- Keep the DB in step with the Role union in the API contract.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'analyst', 'viewer'));

CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);

-- Refresh tokens are opaque random strings, never JWTs: they must be revocable,
-- and a stateless token cannot be. Only a SHA-256 hash is stored, so a database
-- leak does not hand over usable sessions.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,       -- hex sha256 of the raw token
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,       -- set on rotation, logout, or reuse
    replaced_by UUID REFERENCES refresh_tokens(token_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);

-- ─── sprint8_section_review_notes.sql ───────────────────────────────────────

-- When the drafting agent exhausts its revision budget with the critic still
-- flagging gaps, the section is saved as needs_review. This column keeps the
-- critic's final feedback so a human reviewer can see *why*.
ALTER TABLE proposal_sections
    ADD COLUMN IF NOT EXISTS review_notes TEXT;

-- ─── sprint8_solicitation_summary.sql ───────────────────────────────────────

-- A complementary extraction to the compliance matrix: one JSON object per
-- document capturing administrative, deadline, submission and technical-core
-- facts, each value carrying an exact source_quote citation. Written
-- best-effort by ingestion, so NULL simply means "not extracted".
ALTER TABLE rfp_documents
    ADD COLUMN IF NOT EXISTS solicitation_summary JSONB;

-- ─── tuning.sql (Sprint 4.4 — index tuning) ─────────────────────────────────

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
"""


# Reverse dependency order. CASCADE covers the FKs that cross these tables
# (users ← companies via users.company_id, export_jobs → proposals).
DROP_SQL = r"""
DROP TABLE IF EXISTS refresh_tokens CASCADE;
DROP TABLE IF EXISTS export_jobs CASCADE;
DROP TABLE IF EXISTS proposals CASCADE;
DROP TABLE IF EXISTS company_profiles CASCADE;
DROP TABLE IF EXISTS historical_chunks CASCADE;
DROP TABLE IF EXISTS proposal_sections CASCADE;
DROP TABLE IF EXISTS extracted_requirements CASCADE;
DROP TABLE IF EXISTS rfp_documents CASCADE;
DROP TABLE IF EXISTS companies CASCADE;
DROP TABLE IF EXISTS users CASCADE;
"""


def upgrade() -> None:
    # exec_driver_sql, not op.execute: the latter routes through SQLAlchemy's
    # text(), which reads `proposal_id::uuid` as a bind parameter named `:uuid`
    # and fails. This hands the SQL to psycopg2 verbatim.
    op.get_bind().exec_driver_sql(BASELINE_SQL)


def downgrade() -> None:
    # Extensions (uuid-ossp, vector) are deliberately left in place: they are
    # database-wide, may predate this application, and dropping them would take
    # any other schema's columns with them.
    op.get_bind().exec_driver_sql(DROP_SQL)
