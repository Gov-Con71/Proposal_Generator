"""Add historical_chunks metadata tagging for pre-filtered retrieval

Revision ID: 0012_historical_chunks_metadata
Revises: 0011_requirements_order
Create Date: 2026-08-18

Knowledge-base gap: every retrieval searches a tenant's entire past-performance
history undifferentiated — there is no way to scope a search to "this
industry", "this kind of document" (past-performance narrative vs. case study
vs. resume), or "a proposal we actually won" before the vector similarity match
runs. This adds three nullable tag columns to `historical_chunks`, set once per
`store_history` ingest call (every chunk of one source shares that source's
tags), plus a partial btree index per column so a pre-filter is a cheap index
lookup rather than a sequential scan on top of the existing tenant-scoped
ivfflat index.

Free-text VARCHAR, no CHECK constraint — same convention as
`extracted_requirements.category` (see compliance_extractor.py): the accepted-
values list lives in the app layer, so widening it later needs no migration.
Nullable and defaulted to nothing, so every row ingested before this migration
is simply untagged (unfiltered on these dimensions) rather than invalid.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012_historical_chunks_metadata"
down_revision: Union[str, None] = "0011_requirements_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE historical_chunks
            ADD COLUMN IF NOT EXISTS industry VARCHAR(100),
            ADD COLUMN IF NOT EXISTS document_type VARCHAR(50),
            ADD COLUMN IF NOT EXISTS outcome VARCHAR(20);

        CREATE INDEX IF NOT EXISTS idx_historical_chunks_industry
            ON historical_chunks (uploaded_by, industry) WHERE industry IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_historical_chunks_doc_type
            ON historical_chunks (uploaded_by, document_type) WHERE document_type IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_historical_chunks_outcome
            ON historical_chunks (uploaded_by, outcome) WHERE outcome IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP INDEX IF EXISTS idx_historical_chunks_industry;
        DROP INDEX IF EXISTS idx_historical_chunks_doc_type;
        DROP INDEX IF EXISTS idx_historical_chunks_outcome;
        ALTER TABLE historical_chunks
            DROP COLUMN IF EXISTS industry,
            DROP COLUMN IF EXISTS document_type,
            DROP COLUMN IF EXISTS outcome;
        """
    )
