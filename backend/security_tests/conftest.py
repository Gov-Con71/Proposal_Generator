"""Focused auth tests; opt in with an isolated TEST_DATABASE_URL, never project DB."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import auth
from app.core.config import settings
from app.core.middleware import install_exception_handlers


@pytest.fixture(scope="session")
def auth_schema():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL must point to a disposable PostgreSQL database")
    schema = "auth_test_" + uuid4().hex
    conn = psycopg2.connect(url)
    with conn, conn.cursor() as cur:
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        cur.execute(f'CREATE SCHEMA {schema}')
        cur.execute(f'SET search_path TO {schema}, public')
        cur.execute('''CREATE TABLE companies (
            company_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name TEXT UNIQUE);
            CREATE TABLE users (
            user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, first_name TEXT, last_name TEXT,
            company_id UUID REFERENCES companies(company_id), role TEXT NOT NULL DEFAULT 'analyst',
            is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), totp_secret TEXT,
            totp_enabled BOOLEAN NOT NULL DEFAULT FALSE, totp_last_used_step BIGINT);
            CREATE TABLE refresh_tokens (
            token_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), user_id UUID NOT NULL REFERENCES users ON DELETE CASCADE,
            token_hash CHAR(64) NOT NULL UNIQUE, expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ, replaced_by UUID REFERENCES refresh_tokens,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), user_agent TEXT, ip_address TEXT,
            session_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW());''')
    conn.close()
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema},public"})
    spec = importlib.util.spec_from_file_location("session_migration", Path(__file__).parents[1] / "migrations/versions/0018_session_security.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    yield psycopg2.extensions.make_dsn(url, options=f"-c search_path={schema},public"), engine, migration
    engine.dispose()
    conn = psycopg2.connect(url)
    with conn, conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA {schema} CASCADE')
    conn.close()


@pytest.fixture
def db(auth_schema, monkeypatch):
    dsn, _, _ = auth_schema
    monkeypatch.setattr(settings, "database_url", dsn)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE users, companies CASCADE")
    return dsn


@pytest.fixture
def security_client(db):
    app = FastAPI()
    app.include_router(auth.router)
    install_exception_handlers(app)
    with TestClient(app, headers={"X-CSRF-Protection": "1"}) as client:
        yield client
