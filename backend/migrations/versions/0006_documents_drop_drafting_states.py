"""Contract: retire the drafting states from rfp_documents.processing_status.

Revision ID: 0006_docs_drop_drafting
Revises: 0005_proposals_drafting_status
Create Date: 2026-08-04

0005 moved the drafting lifecycle onto the proposal. This clears the states it
left behind on the document, so `processing_status` means one thing again —
where ingestion got to — and nothing reads a drafting state from a column that
no longer receives one.

There is no constraint to drop: `processing_status` is a bare VARCHAR(50) whose
allowed values live only in a comment and in `pipeline._STATUS_MAP`. So this is
a data migration, and the mapping is exact — every drafting state means
ingestion had already finished, which is precisely 'completed'.

`failure_reason` is cleared only for rows being moved out of 'draft_failed'.
An ingestion failure keeps its reason: that one is still the document's.

Ships with its expand half (0005) — see DEPLOYMENT.md §3.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006_docs_drop_drafting"
down_revision: Union[str, None] = "0005_proposals_drafting_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE rfp_documents
        SET processing_status = 'completed',
            failure_reason = CASE
                WHEN processing_status = 'draft_failed' THEN NULL
                ELSE failure_reason
            END
        WHERE processing_status IN ('drafting', 'drafted', 'draft_failed');
        """
    )


def downgrade() -> None:
    """Re-derives what it can; a downgrade cannot invent what 0005 discarded.

    Only 'drafted' is recoverable, and only where the RFP has exactly one
    proposal — the same unambiguity rule 0005 used. In-flight 'drafting' was
    never carried across in either direction.
    """
    op.get_bind().exec_driver_sql(
        """
        UPDATE rfp_documents d
        SET processing_status = 'drafted'
        FROM proposals p
        WHERE p.rfp_id = d.rfp_id
          AND p.drafting_status = 'drafted'
          AND (SELECT count(*) FROM proposals x WHERE x.rfp_id = d.rfp_id) = 1
          AND d.processing_status = 'completed';
        """
    )
