"""Scope historical_chunks to a proposal, for per-bid supporting documents.

Revision ID: 0009_chunks_proposal_scope
Revises: 0008_chunks_fulltext
Create Date: 2026-08-17

`historical_chunks` had exactly one pool per tenant: everything a company had
ever ingested, searched together for every bid. That is the right model for a
reusable past-performance library, and the wrong one for the documents a user
attaches because they are relevant to *this* solicitation — those get diluted by
the whole archive at retrieval time.

`proposal_id` splits the store in two without splitting the table:

  * NULL          — the long-term library, reusable across every bid
  * set           — supporting documents for that one proposal

Retrieval prefers a proposal's own chunks and falls back to the library only
when they do not cover a section (see `retrieval.search_similar`).

ON DELETE CASCADE is the whole lifecycle: supporting documents live exactly as
long as the bid does. No expiry job, no orphan sweep — deleting the proposal
takes its evidence with it.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009_chunks_proposal_scope"
down_revision: Union[str, None] = "0008_chunks_fulltext"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        ALTER TABLE historical_chunks
            ADD COLUMN IF NOT EXISTS proposal_id UUID
            REFERENCES proposals(proposal_id) ON DELETE CASCADE;
        """
    )
    # Retrieval always filters on the tenant first, then narrows to one pool, so
    # the composite matches the query shape rather than needing two indexes.
    bind.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_historical_chunks_tenant_proposal
            ON historical_chunks (uploaded_by, proposal_id);
        """
    )
    # Every row that predates this column is library content by definition —
    # it was ingested when the library was the only pool. The column is already
    # NULL for them; this is a statistics refresh, not a backfill.
    bind.exec_driver_sql("ANALYZE historical_chunks;")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP INDEX IF EXISTS idx_historical_chunks_tenant_proposal;")
    # Dropping the column discards the library/bid distinction; the chunks
    # themselves survive and read as library content again.
    bind.exec_driver_sql("ALTER TABLE historical_chunks DROP COLUMN IF EXISTS proposal_id;")
