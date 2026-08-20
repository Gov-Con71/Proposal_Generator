"""Add extracted_requirements.search_keywords

Revision ID: 0009_requirements_keywords
Revises: 0009_chunks_proposal_scope
Create Date: 2026-08-16

The compliance extractor already produces, per requirement, a short list of
search terms useful for locating supporting past-performance evidence (e.g.
["CMMC Level 2", "wood packaging", "ISPM 15"]) — this just persists what the
LLM already generates instead of discarding it after the extraction call
returns. TEXT[] with a NOT NULL DEFAULT '{}' rather than nullable: "no
keywords" and "column not populated" would otherwise be indistinguishable to
every reader of this column, and every caller would need a null check for a
list that is legitimately just empty most of the time.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009_requirements_keywords"
down_revision: Union[str, None] = "0009_chunks_proposal_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE extracted_requirements
            ADD COLUMN IF NOT EXISTS search_keywords TEXT[] NOT NULL DEFAULT '{}';
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE extracted_requirements DROP COLUMN IF EXISTS search_keywords;
        """
    )
