"""Alembic environment.

Resolves the database URL through the application's own settings object rather
than alembic.ini, so a migration can only ever target the database the app
itself would talk to.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# One source of truth for where the database is. See alembic.ini.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Autogenerate is intentionally unavailable. The services use psycopg2 directly
# — there is no ORM model layer to diff against — and the schema leans on raw
# Postgres features (pgvector, uuid-ossp, DO blocks, expression indexes) that
# autogenerate reflects poorly. Revisions are written by hand.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (`alembic upgrade head --sql`).

    Useful when a DBA, not CI, applies the change to production.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        # Every revision runs in one transaction, so a failure half-way leaves
        # no partially-migrated schema behind.
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
