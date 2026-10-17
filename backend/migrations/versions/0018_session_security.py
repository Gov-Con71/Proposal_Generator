"""Bind JWTs to revocable sessions and encrypt existing TOTP secrets."""
from alembic import op
from sqlalchemy import text
from app.core.secret_encryption import encrypt_secret

revision = "0018_session_security"
down_revision = "0017_durable_jobs_revisions"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE refresh_tokens ADD COLUMN session_id UUID NOT NULL DEFAULT uuid_generate_v4()")
    op.execute("ALTER TABLE refresh_tokens ADD COLUMN session_expires_at TIMESTAMPTZ")
    # Old JWTs lack a session ID. Force fresh sign-in instead of retaining a weaker path.
    op.execute("UPDATE refresh_tokens SET revoked_at = COALESCE(revoked_at, NOW()), session_expires_at = expires_at")
    op.execute("ALTER TABLE refresh_tokens ALTER COLUMN session_expires_at SET NOT NULL")
    op.execute("CREATE INDEX idx_refresh_session ON refresh_tokens(user_id, session_id)")
    bind = op.get_bind()
    for row in bind.execute(text("SELECT user_id, totp_secret FROM users WHERE totp_secret IS NOT NULL")).mappings():
        if not row["totp_secret"].startswith("fernet:"):
            bind.execute(text("UPDATE users SET totp_secret = :secret WHERE user_id = :id"),
                         {"secret": encrypt_secret(row["totp_secret"]), "id": row["user_id"]})


def downgrade():
    from app.core.secret_encryption import decrypt_secret
    bind = op.get_bind()
    for row in bind.execute(text("SELECT user_id, totp_secret FROM users WHERE totp_secret IS NOT NULL")).mappings():
        if row["totp_secret"].startswith("fernet:"):
            bind.execute(text("UPDATE users SET totp_secret = :secret WHERE user_id = :id"),
                         {"secret": decrypt_secret(row["totp_secret"]), "id": row["user_id"]})
    op.execute("DROP INDEX idx_refresh_session")
    op.execute("ALTER TABLE refresh_tokens DROP COLUMN session_expires_at, DROP COLUMN session_id")
    op.execute("ALTER TABLE users DROP COLUMN auth_version")
