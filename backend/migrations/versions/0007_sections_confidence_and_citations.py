"""Persist a section's retrieval grounding: confidence score and source tags.

Revision ID: 0007_sections_grounding
Revises: 0006_docs_drop_drafting
Create Date: 2026-08-04

`ProposalSection.aiConfidenceScore` and `.referenceTags` have been in the API
contract, and rendered by the workspace, since Sprint 3 — always as a hardcoded
`0.0` and `[]`, because there was nowhere to put the real values. The retriever
has been computing them all along and discarding them at the point of save
(GAP_ANALYSIS open follow-up: "observed 0.0 and [] on a real RAG draft").

`ai_confidence_score` is REAL and NOT NULL DEFAULT 0, which reads correctly for
the rows that predate this: a section drafted before the columns existed has no
recorded evidence, and 0 is exactly what "no recorded evidence" means. It is
deliberately not backfilled — the retrieval that produced those drafts is gone,
and inventing a score for them would be worse than showing none.

`reference_tags` is JSONB rather than TEXT[] to match how the rest of this
schema stores list-shaped contract fields (`company_profiles.socio_economic_status`,
`rfp_documents.solicitation_summary`), so the psycopg2 adapters already in use
apply unchanged.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0007_sections_grounding"
down_revision: Union[str, None] = "0006_docs_drop_drafting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE proposal_sections
            ADD COLUMN IF NOT EXISTS ai_confidence_score REAL NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS reference_tags JSONB NOT NULL DEFAULT '[]'::jsonb;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE proposal_sections
            DROP COLUMN IF EXISTS ai_confidence_score,
            DROP COLUMN IF EXISTS reference_tags;
        """
    )
