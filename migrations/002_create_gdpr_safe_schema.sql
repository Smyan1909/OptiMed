-- Migration 002: Create GDPR-safe schema
-- This migration creates the new GDPR-compliant schema while preserving existing tables
-- Run this migration before deprecating the old schema

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- A) Sessions & audit
CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_hash BYTEA NOT NULL,          -- salted hash of patient id
    user_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    lawful_basis TEXT NOT NULL,           -- e.g., care_delivery
    purpose_of_use TEXT NOT NULL,
    scopes TEXT[],
    model_config_hash BYTEA NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    action TEXT NOT NULL,                 -- FETCH, RANK, SYNTHESIZE, etc.
    resource_type TEXT,
    resource_id TEXT,
    resource_version TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome TEXT,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- B) Resource catalog (metadata only)
CREATE TABLE IF NOT EXISTS resources (
    id BIGSERIAL PRIMARY KEY,
    subject_hash BYTEA NOT NULL,
    server_alias TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    version_id TEXT,
    last_updated TIMESTAMPTZ,
    etag TEXT,
    encounter_id TEXT,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    has_binary BOOLEAN DEFAULT FALSE,
    byte_size INT,
    sha256 BYTEA,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(subject_hash, server_alias, resource_type, resource_id, COALESCE(version_id,''))
);

CREATE TABLE IF NOT EXISTS resource_codes (
    resource_fk BIGINT REFERENCES resources(id) ON DELETE CASCADE,
    system TEXT NOT NULL,
    code TEXT NOT NULL,
    display TEXT,
    units TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (resource_fk, system, code)
);

-- C) Evidence pointers (no content)
CREATE TABLE IF NOT EXISTS evidence_sets (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    question_id UUID NOT NULL,
    rank INT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_version TEXT,
    section TEXT,
    start_offset INT,
    end_offset INT,
    rerank_score REAL,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- D) Config & reproducibility
CREATE TABLE IF NOT EXISTS model_registry (
    name TEXT,
    version TEXT,
    config_json JSONB,
    config_hash BYTEA,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (name, version)
);

CREATE TABLE IF NOT EXISTS retrieval_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    params JSONB,
    config_hash BYTEA,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Optional: ephemeral cache (UNLOGGED) with crypto-shredding
CREATE UNLOGGED TABLE IF NOT EXISTS temp_content (
    session_id UUID,
    resource_type TEXT,
    resource_id TEXT,
    dek_id TEXT,                          -- DEK stored in KMS/HSM
    ciphertext BYTEA,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    ttl_at TIMESTAMPTZ,
    PRIMARY KEY (session_id, resource_type, resource_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS ix_sessions_subject_hash ON sessions(subject_hash);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_tenant_id ON sessions(tenant_id);
CREATE INDEX IF NOT EXISTS ix_sessions_started_at ON sessions(started_at);

CREATE INDEX IF NOT EXISTS ix_audit_events_session_id ON audit_events(session_id);
CREATE INDEX IF NOT EXISTS ix_audit_events_action ON audit_events(action);
CREATE INDEX IF NOT EXISTS ix_audit_events_occurred_at ON audit_events(occurred_at);

CREATE INDEX IF NOT EXISTS ix_resources_subject_type_date ON resources(subject_hash, resource_type, last_updated);
CREATE INDEX IF NOT EXISTS ix_resources_server_alias ON resources(server_alias);
CREATE INDEX IF NOT EXISTS ix_resources_resource_type ON resources(resource_type);

CREATE INDEX IF NOT EXISTS ix_resource_codes_code ON resource_codes(system, code);
CREATE INDEX IF NOT EXISTS ix_resource_codes_display ON resource_codes(display);

CREATE INDEX IF NOT EXISTS ix_evidence_sets_session_id ON evidence_sets(session_id);
CREATE INDEX IF NOT EXISTS ix_evidence_sets_question_id ON evidence_sets(question_id);
CREATE INDEX IF NOT EXISTS ix_evidence_sets_rank ON evidence_sets(rank);

CREATE INDEX IF NOT EXISTS ix_retrieval_config_config_hash ON retrieval_config(config_hash);

-- TTL index for temp_content cleanup
CREATE INDEX IF NOT EXISTS ix_temp_content_ttl ON temp_content(ttl_at);

-- Comments for documentation
COMMENT ON TABLE sessions IS 'Session tracking with pseudonymized patient IDs and audit trail';
COMMENT ON TABLE audit_events IS 'Audit trail for all data access and processing activities';
COMMENT ON TABLE resources IS 'FHIR resource metadata catalog without PHI content';
COMMENT ON TABLE resource_codes IS 'Medical codes and terminologies from FHIR resources';
COMMENT ON TABLE evidence_sets IS 'Evidence pointers for retrieval without storing content';
COMMENT ON TABLE model_registry IS 'Model configurations for reproducibility';
COMMENT ON TABLE retrieval_config IS 'Retrieval algorithm configurations';
COMMENT ON TABLE temp_content IS 'Ephemeral encrypted cache with crypto-shredding';

COMMENT ON COLUMN sessions.subject_hash IS 'Salted hash of patient ID for pseudonymization';
COMMENT ON COLUMN sessions.lawful_basis IS 'GDPR lawful basis for processing (e.g., care_delivery)';
COMMENT ON COLUMN sessions.purpose_of_use IS 'Purpose limitation under GDPR';
COMMENT ON COLUMN audit_events.action IS 'Type of action performed (FETCH, RANK, SYNTHESIZE, etc.)';
COMMENT ON COLUMN resources.subject_hash IS 'Pseudonymized patient identifier';
COMMENT ON COLUMN temp_content.dek_id IS 'Data Encryption Key ID for envelope encryption';
COMMENT ON COLUMN temp_content.ciphertext IS 'AES-GCM encrypted content, unreadable without DEK';
