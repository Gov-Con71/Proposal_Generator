"""Add proposal_sections.sort_order

Revision ID: 0010_sections_sort_order
Revises: 0009_requirements_keywords
Create Date: 2026-08-16

Sections draft concurrently (drafting_agent.run_drafting fans out over the
outline with bounded concurrency) and each is persisted the moment its own
draft/critic/revise cycle finishes — so `ORDER BY created_at` reflects
*completion* order, not the outline's planned order. That's silently wrong for
a Section-L-mirroring outline: a section queued third can finish (and insert)
before one queued first, if it needed fewer revision rounds. The exported
document's section order could drift from the compliance-critical order the
outline planner produced.

`sort_order` fixes the ordering source: drafted sections get their outline
index (0, 1, 2, ...); manually-created/on-demand sections (`create_section`)
append to the end via MAX(sort_order)+1, rather than defaulting to 0 and
jumping ahead of drafted content. NOT NULL DEFAULT 0 so pre-existing rows (no
migration to backfill a meaningful order for them) sort together at the front,
in their prior `created_at` order — see the app-layer `ORDER BY sort_order,
created_at` in workspace_service.list_sections.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010_sections_sort_order"
down_revision: Union[str, None] = "0009_requirements_keywords"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE proposal_sections
            ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE proposal_sections DROP COLUMN IF EXISTS sort_order;
        """
    )
