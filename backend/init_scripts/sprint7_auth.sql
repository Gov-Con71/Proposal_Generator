-- Sprint 7 — real auth: companies, persisted roles, refresh-token rotation.
-- Runs after init_schema.sql (needs the users table). Idempotent so it can be
-- re-applied to an existing database.

-- A company is the organisation a user signs up under. Collected on the
-- register form, which previously discarded it.
CREATE TABLE IF NOT EXISTS companies (
    company_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Match companies case-insensitively so "Acro Inc." and "acro inc." are one org.
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_name_lower ON companies (LOWER(name));

-- Roles were hardcoded to 'analyst' in the API layer; persist them instead.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'analyst';
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES companies(company_id) ON DELETE SET NULL;

-- Keep the DB in step with the Role union in the API contract.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'analyst', 'viewer'));

CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);

-- Refresh tokens are opaque random strings, never JWTs: they must be revocable,
-- and a stateless token cannot be. Only a SHA-256 hash is stored, so a database
-- leak does not hand over usable sessions.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,       -- hex sha256 of the raw token
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,       -- set on rotation, logout, or reuse
    replaced_by UUID REFERENCES refresh_tokens(token_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);
