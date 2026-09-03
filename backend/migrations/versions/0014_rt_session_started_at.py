"""Add refresh_tokens.session_started_at.

Revision ID: 0014_rt_session_started_at
Revises: 0013_refresh_tokens_device_info
Create Date: 2026-09-03

`refresh_tokens.created_at` is when *that row* was inserted — but every
refresh rotates the token (a new row, the old one revoked), and the access
token is memory-only, so a page reload rotates too. The Security page's
active-sessions list used `created_at` as "signed in at", which meant it
crept forward on every reload instead of showing the actual sign-in time
(GAP_ANALYSIS-adjacent: same class of bug as §4.3, just introduced by the fix
for it).

`session_started_at` is the fix: set once at login/register and carried
forward unchanged through every rotation in `refresh_token_service.issue()`,
so the whole `replaced_by` chain shares one value. Existing rows have no
recorded chain origin further back than what `replaced_by` links already
capture, so the backfill below walks each row's `replaced_by` predecessors
back to the root and takes the root's `created_at` — the best available
approximation of when that session actually began.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0014_rt_session_started_at"
down_revision: Union[str, None] = "0013_refresh_tokens_device_info"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE refresh_tokens "
        "ADD COLUMN IF NOT EXISTS session_started_at TIMESTAMP WITH TIME ZONE;"
    )
    # Walk each row's `replaced_by` predecessors back to the chain's root and
    # take the root's created_at — a predecessor is always older, so the
    # earliest one found is the session's true start.
    bind.exec_driver_sql(
        """
        WITH RECURSIVE chain(token_id, current_id, current_created_at) AS (
            -- `current_id` is the walking pointer; `token_id` stays fixed to
            -- the row this branch of the recursion is computing an origin for.
            SELECT t.token_id, t.token_id, t.created_at FROM refresh_tokens t
            UNION ALL
            SELECT c.token_id, p.token_id, p.created_at
            FROM chain c
            JOIN refresh_tokens p ON p.replaced_by = c.current_id
        ),
        origin AS (
            SELECT token_id, MIN(current_created_at) AS started_at
            FROM chain
            GROUP BY token_id
        )
        UPDATE refresh_tokens rt
        SET session_started_at = origin.started_at
        FROM origin
        WHERE rt.token_id = origin.token_id;
        """
    )
    bind.exec_driver_sql(
        "ALTER TABLE refresh_tokens "
        "ALTER COLUMN session_started_at SET DEFAULT NOW();"
    )
    bind.exec_driver_sql(
        "ALTER TABLE refresh_tokens "
        "ALTER COLUMN session_started_at SET NOT NULL;"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS session_started_at;"
    )
