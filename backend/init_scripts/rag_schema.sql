-- Sprint 3 — RAG engine schema. Runs after init_schema.sql (lexicographic order).

-- Activate pgvector (image is ankane/pgvector, so the extension is available).
CREATE EXTENSION IF NOT EXISTS vector;

-- Historical past-performance chunks: shredded, embedded, tenant-scoped.
CREATE TABLE IF NOT EXISTS historical_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    uploaded_by UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, -- tenant boundary
    source_name VARCHAR(255) NOT NULL,   -- e.g. "USCG Pump Overhaul 2024"
    content TEXT NOT NULL,               -- the raw chunk text
    embedding vector(768),               -- google-genai text-embedding-004
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_historical_chunks_user ON historical_chunks(uploaded_by);

-- Workspace editing state for draft sections (Story 3.4).
ALTER TABLE proposal_sections
    ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'draft'; -- draft|approved|needs_review|empty

-- Approximate-nearest-neighbour index over the embedding (cosine distance).
CREATE INDEX IF NOT EXISTS idx_historical_chunks_embedding
    ON historical_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
