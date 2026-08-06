"""Expand: give proposal_sections a proposal_id and backfill it.

Revision ID: 0002_sections_proposal_id
Revises: 0001_baseline
Create Date: 2026-08-04

`proposal_sections.rfp_id` means sections belong to the *document*, so two
proposals answering the same RFP silently share drafted sections — one tenant's
edits appearing under the other's proposal, with nothing in the UI to suggest
it. Sections are proposal-scoped work product; this re-keys them to say so
(GAP_ANALYSIS.md §1.2 follow-up).

**Expand half of expand/contract.** This revision only adds and backfills. It
is deliberately safe for the *currently deployed* code to keep running against:
`proposal_id` is nullable, so writers that still populate only `rfp_id` continue
to work. `rfp_id` is made nullable in the same step so the *next* release can
stop writing it. `0003` then enforces NOT NULL and drops the old column.

Deploy them one release apart. Applying both at once is safe only when nothing
is serving traffic against the old schema — true for this project today, since
production is not yet provisioned, and untrue the moment it is.

The backfill picks the earliest-created proposal per RFP, deterministically
(`DISTINCT ON` + a total ordering including proposal_id, so ties cannot make the
result depend on physical row order). Where several proposals already share one
RFP the association is genuinely ambiguous — that ambiguity *is* the bug — and
oldest-first matches the order sections would have been drafted in.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002_sections_proposal_id"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UPGRADE_SQL = r"""
-- ON DELETE CASCADE: a section is work product belonging to its proposal, and
-- has no meaning once that proposal is gone. (rfp_id used the same rule.)
ALTER TABLE proposal_sections
    ADD COLUMN IF NOT EXISTS proposal_id UUID REFERENCES proposals(proposal_id) ON DELETE CASCADE;

UPDATE proposal_sections s
SET proposal_id = p.proposal_id
FROM (
    SELECT DISTINCT ON (rfp_id) rfp_id, proposal_id
    FROM proposals
    WHERE rfp_id IS NOT NULL
    ORDER BY rfp_id, created_at, proposal_id
) p
WHERE p.rfp_id = s.rfp_id
  AND s.proposal_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_sections_proposal ON proposal_sections(proposal_id);

-- Lets the next release insert sections without an rfp_id. Until 0003 runs,
-- both columns are populated by old writers and only proposal_id by new ones.
ALTER TABLE proposal_sections ALTER COLUMN rfp_id DROP NOT NULL;
"""


DOWNGRADE_SQL = r"""
-- Restore rfp_id for any row written by new code (proposal_id only), or the
-- NOT NULL below fails.
UPDATE proposal_sections s
SET rfp_id = p.rfp_id
FROM proposals p
WHERE p.proposal_id = s.proposal_id
  AND s.rfp_id IS NULL
  AND p.rfp_id IS NOT NULL;

-- A section that still has no rfp_id cannot satisfy the restored constraint and
-- is unreachable under the old schema anyway.
DELETE FROM proposal_sections WHERE rfp_id IS NULL;

ALTER TABLE proposal_sections ALTER COLUMN rfp_id SET NOT NULL;
DROP INDEX IF EXISTS idx_sections_proposal;
ALTER TABLE proposal_sections DROP COLUMN IF EXISTS proposal_id;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE_SQL)
