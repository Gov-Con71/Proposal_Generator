"""Expand: give proposals their own drafting lifecycle.

Revision ID: 0005_proposals_drafting_status
Revises: 0004_failure_reason
Create Date: 2026-08-04

Drafting progress was tracked on `rfp_documents.processing_status`, which is a
property of the *document*. Sections became proposal-scoped in 0002/0003, so
two proposals drafting from one RFP now correctly produce two independent sets
of sections while still overwriting each other's progress flag — one bid's
"drafted" clearing the other's "drafting", and a failure reason from one run
displayed against the other. Ingestion statuses stay on the document, where
they belong: parsing an RFP genuinely is per-document work.

**Backfill.** Deliberately derived from the sections themselves rather than
copied from the document, because the document's flag cannot say *which*
proposal it referred to — that ambiguity is the bug being fixed. A proposal
with drafted sections is 'drafted'; that is observable and per-proposal.

The one unambiguous case worth carrying over is a failure: if a document is
'draft_failed' and exactly one proposal is built on it, that proposal is the
one that failed, and its reason is worth keeping. Where several proposals share
the RFP the attribution is guesswork, so they are left 'idle' — a re-run costs
one job and states the truth, where a wrong attribution reads as fact.

In-flight 'drafting' is not carried over at all: the worker holding that state
does not survive the deploy, so importing it would strand a proposal showing
progress that nothing is making.

Ships with its contract half (0006) — see DEPLOYMENT.md §3.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005_proposals_drafting_status"
down_revision: Union[str, None] = "0004_failure_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UPGRADE_SQL = r"""
ALTER TABLE proposals
    ADD COLUMN IF NOT EXISTS drafting_status VARCHAR(20) NOT NULL DEFAULT 'idle',
    ADD COLUMN IF NOT EXISTS drafting_failure_reason TEXT;

-- Observable and per-proposal: it has drafted sections, so it was drafted.
UPDATE proposals p
SET drafting_status = 'drafted'
WHERE EXISTS (
    SELECT 1 FROM proposal_sections s WHERE s.proposal_id = p.proposal_id
);

-- The single unambiguous failure case: one proposal on the RFP, so the
-- document's failure can only have been about that one.
UPDATE proposals p
SET drafting_status = 'draft_failed',
    drafting_failure_reason = d.failure_reason
FROM rfp_documents d
WHERE d.rfp_id = p.rfp_id
  AND d.processing_status = 'draft_failed'
  AND (SELECT count(*) FROM proposals x WHERE x.rfp_id = p.rfp_id) = 1;
"""


DOWNGRADE_SQL = r"""
-- The document flag is the pre-0005 source of truth, so put back what a
-- proposal can still say unambiguously: a lone proposal's failed draft.
UPDATE rfp_documents d
SET processing_status = 'draft_failed',
    failure_reason = p.drafting_failure_reason
FROM proposals p
WHERE p.rfp_id = d.rfp_id
  AND p.drafting_status = 'draft_failed'
  AND (SELECT count(*) FROM proposals x WHERE x.rfp_id = d.rfp_id) = 1
  AND d.processing_status = 'completed';

ALTER TABLE proposals
    DROP COLUMN IF EXISTS drafting_status,
    DROP COLUMN IF EXISTS drafting_failure_reason;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE_SQL)
