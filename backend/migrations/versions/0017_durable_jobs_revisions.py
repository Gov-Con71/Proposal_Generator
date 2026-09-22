"""Durable dispatch and staged proposal revisions; preserve all legacy sections."""
from alembic import op

revision = '0017_durable_jobs_revisions'
down_revision = '0016_drafting_trajectories'
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE drafting_runs (
        run_id UUID PRIMARY KEY,
        proposal_id UUID NOT NULL REFERENCES proposals ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed')),
        snapshot JSONB NOT NULL,
        outline JSONB,
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX one_active_draft ON drafting_runs(proposal_id) WHERE status IN ('queued','running');
    CREATE TABLE drafting_run_sections (
        run_id UUID NOT NULL REFERENCES drafting_runs ON DELETE CASCADE,
        outline_index INTEGER NOT NULL,
        section_id UUID NOT NULL UNIQUE,
        payload JSONB NOT NULL,
        PRIMARY KEY (run_id, outline_index)
    );
    ALTER TABLE proposal_sections ADD COLUMN generated_run_id UUID REFERENCES drafting_runs ON DELETE SET NULL;
    ALTER TABLE proposal_sections ADD COLUMN user_modified BOOLEAN NOT NULL DEFAULT TRUE;
    CREATE TABLE dispatch_jobs (
        job_id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        operation TEXT NOT NULL CHECK (operation IN ('ingest_document','draft_proposal','render_export')),
        entity_id UUID NOT NULL,
        payload JSONB NOT NULL,
        idempotency_key TEXT,
        request_hash TEXT NOT NULL,
        response JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed')),
        attempts INTEGER NOT NULL DEFAULT 0,
        publish_failures INTEGER NOT NULL DEFAULT 0,
        next_dispatch_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(user_id, operation, idempotency_key)
    );
    CREATE INDEX dispatch_due ON dispatch_jobs(next_dispatch_at) WHERE status IN ('queued','running');
    """)


def downgrade():
    op.execute("""
    DROP TABLE dispatch_jobs;
    ALTER TABLE proposal_sections DROP COLUMN generated_run_id, DROP COLUMN user_modified;
    DROP TABLE drafting_run_sections;
    DROP TABLE drafting_runs;
    """)
