"""Add rfp_documents.failure_reason.

Revision ID: 0004_failure_reason
Revises: 0003_sections_drop_rfp
Create Date: 2026-08-04

`document_service` marks a document `failed` and stores nothing about why, so
the UI cannot tell "the configured model was retired" from "this PDF is
corrupt". That gap is exactly why a two-word config typo presented as a dead
product for days and was first diagnosed as a billing problem
(GAP_ANALYSIS.md §1.1) — the reason existed only in worker logs.

NULL means "no failure recorded", which is the correct reading for every
document that has not failed.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004_failure_reason"
down_revision: Union[str, None] = "0003_sections_drop_rfp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE rfp_documents ADD COLUMN IF NOT EXISTS failure_reason TEXT;"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE rfp_documents DROP COLUMN IF EXISTS failure_reason;"
    )
