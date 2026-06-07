-- Enable critical database extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- Enables random UUID generation hooks

-- Create Users Table
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL, -- Stored securely encrypted by the backend
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create RFP Documents Table (The uploaded files tracked in S3)
CREATE TABLE rfp_documents (
    rfp_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    uploaded_by UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    s3_storage_key VARCHAR(512) NOT NULL, -- Points to the raw file resting inside AWS S3
    processing_status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'parsing', 'completed', 'failed'
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create Extracted Requirements Table (The Core Compliance Matrix rows)
CREATE TABLE extracted_requirements (
    requirement_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rfp_id UUID NOT NULL REFERENCES rfp_documents(rfp_id) ON DELETE CASCADE,
    section_number VARCHAR(100), -- e.g., "Section C.3.2"
    raw_text_content TEXT NOT NULL, -- The explicit text deliverable rule pulled out by the AI shredder
    category VARCHAR(100), -- e.g., "Technical", "Security", "Past Performance"
    compliance_status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'compliant', 'exception'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create Proposal Layouts / Sections Table (The editable Rich-Text Canvas)
CREATE TABLE proposal_sections (
    section_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rfp_id UUID NOT NULL REFERENCES rfp_documents(rfp_id) ON DELETE CASCADE,
    requirement_id UUID REFERENCES extracted_requirements(requirement_id) ON DELETE SET NULL, -- Maps section explicitly to the rule it fulfills
    section_title VARCHAR(255) NOT NULL, -- e.g., "Technical Management Plan"
    generated_draft_content TEXT, -- The editable draft string compiled by the AI writer agent
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Define Performance & Scalability Indexes
-- B-Tree indexes on frequent search fields to make your user dashboards load instantly
CREATE INDEX idx_rfps_workspace ON rfp_documents(uploaded_by);
CREATE INDEX idx_requirements_rfp ON extracted_requirements(rfp_id);
CREATE INDEX idx_proposals_rfp ON proposal_sections(rfp_id);
