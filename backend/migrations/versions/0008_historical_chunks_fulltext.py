"""Add full-text search over historical_chunks for hybrid retrieval.

Revision ID: 0008_chunks_fulltext
Revises: 0007_sections_grounding
Create Date: 2026-08-15

Dense cosine similarity over embeddings systematically underweights exact-token
recall — FAR/DFARS clause numbers ("52.204-21"), certification strings ("ISO
9001:2015"), CAGE codes, and contract numbers ("W91QUZ-19-C-0042") are exactly
the kind of literal tokens a paraphrase-tolerant embedding can rank below a
merely-topically-similar chunk. `search_similar` (app/services/retrieval.py)
now fuses this keyword leg with the existing dense leg via Reciprocal Rank
Fusion, so a chunk that's the unique exact match for a clause/cert/contract
number gets pulled in even when its overall semantic score is unremarkable.

`content_tsv` is a STORED generated column (not a trigger-maintained one) so it
can never drift out of sync with `content`, and ingestion code needs no changes
to keep it populated.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008_chunks_fulltext"
down_revision: Union[str, None] = "0007_sections_grounding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE historical_chunks
            ADD COLUMN IF NOT EXISTS content_tsv tsvector
                GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

        CREATE INDEX IF NOT EXISTS idx_historical_chunks_content_tsv
            ON historical_chunks USING GIN (content_tsv);
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP INDEX IF EXISTS idx_historical_chunks_content_tsv;
        ALTER TABLE historical_chunks DROP COLUMN IF EXISTS content_tsv;
        """
    )
