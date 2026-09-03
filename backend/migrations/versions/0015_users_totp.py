"""Add users.totp_secret, users.totp_enabled, users.totp_last_used_step.

Revision ID: 0015_users_totp
Revises: 0014_rt_session_started_at
Create Date: 2026-09-03

The Security page's "Two-factor authentication" card has had an Enable button
with no `onClick` at all since it was built — nothing behind it, same as the
active-sessions row before migration 0013.

`totp_secret` is set (but `totp_enabled` left false) the moment enrollment
starts, and only flips to true once the user proves they can produce a
matching code — storing it enabled up front would let "enabling 2FA" succeed
without ever confirming the user actually saved the secret.

`totp_last_used_step` is the replay guard: a TOTP code is valid for ~90s
(the ±1-step tolerance `totp_service` checks), so without tracking which step
was last consumed, a code captured in transit could be replayed for the rest
of its window.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0015_users_totp"
down_revision: Union[str, None] = "0014_rt_session_started_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT;"
    )
    bind.exec_driver_sql(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled "
        "BOOLEAN NOT NULL DEFAULT FALSE;"
    )
    bind.exec_driver_sql(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_used_step BIGINT;"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE users DROP COLUMN IF EXISTS totp_last_used_step;"
    )
    bind.exec_driver_sql("ALTER TABLE users DROP COLUMN IF EXISTS totp_enabled;")
    bind.exec_driver_sql("ALTER TABLE users DROP COLUMN IF EXISTS totp_secret;")
