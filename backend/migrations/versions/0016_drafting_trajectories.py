"""Add drafting_trajectories: a replayable per-attempt record of drafting runs.

Revision ID: 0016_drafting_trajectories
Revises: 0015_users_totp
Create Date: 2026-09-04

`proposal_sections.review_notes` (sprint8) only ever holds the compliance
critic's *latest* feedback — every earlier revision round's draft content and
critic verdict is discarded the moment `_save_section_node` runs
(`app/agent/drafting_agent.py`). When a section stalls or a revision loop goes
sideways, there is today no way to reconstruct what happened short of
hand-grepping structured logs by request_id/proposal_id.

One row per section-within-a-run (not one row per attempt): `_save_section_node`
runs exactly once per section per run regardless of how many attempts it took
(up to `_MAX_ATTEMPTS`), so this is one INSERT there, not several. `attempts` is
JSONB — an ordered array of per-attempt records — following the precedent set by
`proposal_sections.reference_tags` (migration 0007_sections_grounding), chosen
there specifically so the psycopg2 adapters already in use apply unchanged to
list-shaped fields.

`section_id` is ON DELETE SET NULL, not CASCADE: a section that fails before
`_save_section_node` ever runs (guardrail rejection, draft exception, critic
exception) gets no `proposal_sections` row at all today, but its trajectory is
exactly the failure record this table exists to keep — it must survive
independent of whether a section row was ever created.

`proposal_id` is ON DELETE CASCADE, matching `proposal_sections`: trajectories
die with their proposal. That is the entire retention policy for v1 — no
separate cleanup job.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016_drafting_trajectories"
down_revision: Union[str, None] = "0015_users_totp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS drafting_trajectories (
            trajectory_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            run_id          UUID NOT NULL,
            proposal_id     UUID NOT NULL REFERENCES proposals(proposal_id) ON DELETE CASCADE,
            section_id      UUID REFERENCES proposal_sections(section_id) ON DELETE SET NULL,
            section_title   VARCHAR(255) NOT NULL,
            outline_index   INT NOT NULL DEFAULT 0,
            attempts        JSONB NOT NULL DEFAULT '[]'::jsonb,
            final_status    VARCHAR(50),
            stalled         BOOLEAN NOT NULL DEFAULT FALSE,
            attempt_count   INT NOT NULL DEFAULT 0,
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (run_id, outline_index)
        );
        """
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_drafting_trajectories_proposal "
        "ON drafting_trajectories (proposal_id, created_at DESC);"
    )
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_drafting_trajectories_run "
        "ON drafting_trajectories (run_id);"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS drafting_trajectories CASCADE;")
