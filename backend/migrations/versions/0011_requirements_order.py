"""Add extracted_requirements.extraction_order

Revision ID: 0011_requirements_order
Revises: 0010_sections_sort_order
Create Date: 2026-08-16

`insert_requirements` bulk-inserts one extraction's rows via `executemany`, and
Postgres's CURRENT_TIMESTAMP is fixed for the whole transaction — every row
from one extraction gets the exact same `created_at`. `ORDER BY created_at`
therefore ties across an entire batch, i.e. always, and Postgres does not
promise any particular resolution for that tie: `get_requirements` (used by
the drafting agent to assign the integer refs its outline planner echoes back)
and `list_requirements`/`update_requirement`'s position numbering (the
`number` a reviewer sees) could each return a different order across calls
with no data change, purely from physical storage details.

Same fix as `proposal_sections.sort_order` (migration 0010): a real ordinal,
set from the extraction's own list order (itself roughly the source RFP's
document order — the reason preserving it is worth doing, not just a
determinism patch) rather than inferred from a column that was never granular
enough to carry it.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011_requirements_order"
down_revision: Union[str, None] = "0010_sections_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE extracted_requirements
            ADD COLUMN IF NOT EXISTS extraction_order INT NOT NULL DEFAULT 0;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE extracted_requirements DROP COLUMN IF EXISTS extraction_order;
        """
    )
