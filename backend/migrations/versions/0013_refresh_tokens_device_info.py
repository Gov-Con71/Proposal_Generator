"""Add refresh_tokens.user_agent and refresh_tokens.ip_address.

Revision ID: 0013_refresh_tokens_device_info
Revises: 0012_historical_chunks_metadata
Create Date: 2026-09-03

The Security page's "Active sessions" card has shown a single hardcoded
"Chrome on macOS / Arlington, VA" row since it was built — nothing behind it.
Wiring it to real data needs somewhere to read a device from; refresh_tokens
already is the one row-per-session record, so it gets a home for the
User-Agent and client IP captured at issue time. Both nullable: existing
tokens issued before this migration simply show as "Unknown device".
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013_refresh_tokens_device_info"
down_revision: Union[str, None] = "0012_historical_chunks_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS user_agent TEXT;"
    )
    op.get_bind().exec_driver_sql(
        "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS ip_address TEXT;"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS ip_address;"
    )
    op.get_bind().exec_driver_sql(
        "ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS user_agent;"
    )
