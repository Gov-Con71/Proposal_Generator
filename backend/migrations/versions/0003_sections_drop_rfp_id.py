"""Contract: make proposal_sections.proposal_id required and drop rfp_id.

Revision ID: 0003_sections_drop_rfp
Revises: 0002_sections_proposal_id
Create Date: 2026-08-04

The contract half of the re-key started in 0002. Run this only once every
writer populates `proposal_id` — i.e. one release after 0002.

Refuses to run rather than deleting anything. A section with no `proposal_id`
at this point belongs to an RFP that no proposal references: unreachable through
the API either way, but it is still drafted content, and quietly deleting a
tenant's work to satisfy a constraint is not a migration's decision to make.
The error names the exact query to inspect.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_sections_drop_rfp"
down_revision: Union[str, None] = "0002_sections_proposal_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    orphans = bind.exec_driver_sql(
        "SELECT count(*) FROM proposal_sections WHERE proposal_id IS NULL;"
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} proposal_sections row(s) have no proposal_id and would be "
            "lost by this migration. They belong to an RFP that no proposal "
            "references. Inspect them with:\n"
            "  SELECT section_id, rfp_id, section_title FROM proposal_sections "
            "WHERE proposal_id IS NULL;\n"
            "Then either attach the RFP to a proposal and re-run 0002's backfill, "
            "or delete the rows deliberately."
        )

    bind.exec_driver_sql(
        """
        ALTER TABLE proposal_sections ALTER COLUMN proposal_id SET NOT NULL;
        -- idx_proposals_rfp (on proposal_sections(rfp_id), despite the name) is
        -- dropped automatically along with the column.
        ALTER TABLE proposal_sections DROP COLUMN IF EXISTS rfp_id;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE proposal_sections
            ADD COLUMN IF NOT EXISTS rfp_id UUID REFERENCES rfp_documents(rfp_id) ON DELETE CASCADE;

        UPDATE proposal_sections s
        SET rfp_id = p.rfp_id
        FROM proposals p
        WHERE p.proposal_id = s.proposal_id
          AND s.rfp_id IS NULL;

        -- Restores the original (misleadingly named) index from init_schema.sql.
        CREATE INDEX IF NOT EXISTS idx_proposals_rfp ON proposal_sections(rfp_id);

        ALTER TABLE proposal_sections ALTER COLUMN proposal_id DROP NOT NULL;
        """
    )
