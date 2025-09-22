-- Migration 002: Create GDPR-safe schema
-- This migration creates the new GDPR-compliant schema while preserving existing tables
-- Run this migration before deprecating the old schema

-- Enable required extensions (conditional for Azure PostgreSQL)
-- Note: Extensions must be allow-listed first via Azure portal or CLI
DO $$
BEGIN
    -- Try to create pgcrypto extension (needed for cryptographic functions)
    BEGIN
        CREATE EXTENSION IF NOT EXISTS "pgcrypto";
        RAISE NOTICE 'pgcrypto extension enabled successfully';
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'pgcrypto extension not available. Some cryptographic functions may not work. Error: %', SQLERRM;
    END;

    -- Try to create vector extension (needed for similarity search)
    BEGIN
        CREATE EXTENSION IF NOT EXISTS "vector";
        RAISE NOTICE 'vector extension enabled successfully';
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'vector extension not available. Vector similarity search will not work. Error: %', SQLERRM;
    END;
END $$;

-- A) Sessions & audit
CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_hash BYTEA NOT NULL,          -- salted hash of patient id
    user_id VARCHAR(255) NOT NULL,
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
    UNIQUE(subject_hash, server_alias, resource_type, resource_id, version_id)
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
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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

-- E) User management tables (required by migration script and backend)
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(255) PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(255) NOT NULL,
    last_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    department VARCHAR(255),
    license_number VARCHAR(255),
    phone VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_sessions (
    session_id VARCHAR(255) PRIMARY KEY, -- Backend expects VARCHAR session_id
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    login_time TIMESTAMP WITH TIME ZONE NOT NULL,
    last_activity TIMESTAMP WITH TIME ZONE NOT NULL,
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_actions (
    action_id VARCHAR(255) PRIMARY KEY, -- Backend expects VARCHAR action_id
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    action_type VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    description TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for user management
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON user_sessions(is_active);
CREATE INDEX IF NOT EXISTS idx_actions_user_id ON user_actions(user_id);
CREATE INDEX IF NOT EXISTS idx_actions_type ON user_actions(action_type);
CREATE INDEX IF NOT EXISTS idx_actions_created_at ON user_actions(created_at);

-- Comments for user management tables
COMMENT ON TABLE users IS 'User accounts for the application';
COMMENT ON TABLE user_sessions IS 'User session management with token-based authentication';
COMMENT ON TABLE user_actions IS 'User action audit trail linked to sessions';

-- F) Analytics and audit tables (required by user repository)
CREATE TABLE IF NOT EXISTS system_usage_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value INT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'count',
    dimensions JSONB DEFAULT '{}',
    tenant_id UUID,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_analytics (
    session_id UUID PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    total_requests INT DEFAULT 0,
    total_responses INT DEFAULT 0,
    patient_contexts_accessed INT DEFAULT 0,
    web_searches_performed INT DEFAULT 0,
    diagnostic_requests INT DEFAULT 0,
    chat_requests INT DEFAULT 0,
    image_uploads INT DEFAULT 0,
    journal_generations INT DEFAULT 0,
    error_count INT DEFAULT 0,
    session_duration_minutes REAL,
    performance_metrics JSONB DEFAULT '{}',
    data_sources_accessed TEXT[],
    started_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS data_access_logs (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    access_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_identifier TEXT,
    resource_count INT DEFAULT 1,
    data_source TEXT NOT NULL DEFAULT 'application',
    lawful_basis TEXT NOT NULL DEFAULT 'legitimate_interest',
    purpose_of_use TEXT NOT NULL DEFAULT 'healthcare_delivery',
    access_method TEXT,
    requested_fields TEXT[],
    returned_count INT,
    filter_criteria JSONB DEFAULT '{}',
    data_retention_days INT,
    encryption_method TEXT,
    access_duration_ms INT,
    privacy_impact_level TEXT DEFAULT 'low',
    access_granted BOOLEAN DEFAULT true,
    accessed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS performance_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_category TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    endpoint TEXT,
    user_id VARCHAR(255),
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    patient_context_size INT,
    model_used TEXT,
    processing_stage TEXT,
    additional_context JSONB DEFAULT '{}',
    measured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS encryption_audit_log (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255),
    operation_type TEXT NOT NULL,
    data_type TEXT NOT NULL,
    encryption_algorithm TEXT NOT NULL,
    key_type TEXT NOT NULL,
    key_identifier TEXT,
    data_size_bytes BIGINT,
    operation_duration_ms INT,
    success BOOLEAN DEFAULT true,
    error_details TEXT,
    client_info JSONB DEFAULT '{}',
    compliance_context JSONB DEFAULT '{}',
    operation_timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compliance_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    compliance_framework TEXT NOT NULL,
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    patient_id TEXT,
    lawful_basis TEXT,
    consent_status TEXT,
    data_categories TEXT[],
    processing_purposes TEXT[],
    retention_period_days INT,
    data_minimization_applied BOOLEAN DEFAULT true,
    anonymization_method TEXT,
    cross_border_transfer BOOLEAN DEFAULT false,
    transfer_safeguards TEXT[],
    individual_rights_exercised TEXT[],
    compliance_status TEXT DEFAULT 'compliant',
    risk_assessment JSONB DEFAULT '{}',
    mitigation_measures TEXT[],
    event_timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gdpr_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_type TEXT NOT NULL, -- access, rectification, erasure, portability, etc.
    data_subject_id TEXT NOT NULL, -- pseudonymized
    request_date TIMESTAMPTZ DEFAULT NOW(),
    completion_date TIMESTAMPTZ,
    status TEXT DEFAULT 'pending', -- pending, in_progress, completed, rejected
    requested_data_categories TEXT[],
    fulfillment_method TEXT,
    verification_method TEXT,
    response_format TEXT DEFAULT 'json',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_health_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_unit TEXT DEFAULT 'count',
    component TEXT NOT NULL,
    status TEXT DEFAULT 'normal', -- normal, warning, critical
    dimensions JSONB DEFAULT '{}',
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS data_lineage (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    data_flow_id UUID DEFAULT gen_random_uuid(),
    source_system TEXT NOT NULL,
    source_type TEXT NOT NULL,
    destination_system TEXT NOT NULL,
    destination_type TEXT NOT NULL,
    transformation_applied TEXT[],
    data_quality_score REAL,
    processing_timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for analytics tables
CREATE INDEX IF NOT EXISTS ix_system_usage_metrics_type ON system_usage_metrics(metric_type, metric_name);
CREATE INDEX IF NOT EXISTS ix_system_usage_metrics_recorded_at ON system_usage_metrics(recorded_at);
CREATE INDEX IF NOT EXISTS ix_session_analytics_user_id ON session_analytics(user_id);
CREATE INDEX IF NOT EXISTS ix_session_analytics_started_at ON session_analytics(started_at);
CREATE INDEX IF NOT EXISTS ix_data_access_logs_user_id ON data_access_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_data_access_logs_accessed_at ON data_access_logs(accessed_at);
CREATE INDEX IF NOT EXISTS ix_performance_metrics_category ON performance_metrics(metric_category, metric_name);
CREATE INDEX IF NOT EXISTS ix_performance_metrics_measured_at ON performance_metrics(measured_at);
CREATE INDEX IF NOT EXISTS ix_encryption_audit_log_operation_type ON encryption_audit_log(operation_type);
CREATE INDEX IF NOT EXISTS ix_encryption_audit_log_timestamp ON encryption_audit_log(operation_timestamp);
CREATE INDEX IF NOT EXISTS ix_compliance_events_event_type ON compliance_events(event_type);
CREATE INDEX IF NOT EXISTS ix_compliance_events_timestamp ON compliance_events(event_timestamp);
CREATE INDEX IF NOT EXISTS ix_gdpr_requests_status ON gdpr_requests(status);
CREATE INDEX IF NOT EXISTS ix_gdpr_requests_request_date ON gdpr_requests(request_date);
CREATE INDEX IF NOT EXISTS ix_system_health_metrics_component ON system_health_metrics(component);
CREATE INDEX IF NOT EXISTS ix_system_health_metrics_recorded_at ON system_health_metrics(recorded_at);
CREATE INDEX IF NOT EXISTS ix_data_lineage_session_id ON data_lineage(session_id);
CREATE INDEX IF NOT EXISTS ix_data_lineage_processing_timestamp ON data_lineage(processing_timestamp);

-- Comments for analytics tables
COMMENT ON TABLE system_usage_metrics IS 'System-wide usage metrics for analytics and monitoring';
COMMENT ON TABLE session_analytics IS 'Session-specific analytics and performance metrics';
COMMENT ON TABLE data_access_logs IS 'GDPR-compliant data access logging for audit trails';
COMMENT ON TABLE performance_metrics IS 'Application performance metrics for monitoring';
COMMENT ON TABLE encryption_audit_log IS 'Encryption operations audit log for security compliance';
COMMENT ON TABLE compliance_events IS 'Regulatory compliance events and actions';
COMMENT ON TABLE gdpr_requests IS 'GDPR data subject rights requests tracking';
COMMENT ON TABLE system_health_metrics IS 'System health and infrastructure monitoring';
COMMENT ON TABLE data_lineage IS 'Data transformation and flow tracking for compliance';

-- G) Application-specific tables (required by repository implementations)

-- Generated images table (from image_generation repository)
CREATE TABLE IF NOT EXISTS generated_images (
    generation_id UUID PRIMARY KEY,
    image_data BYTEA NOT NULL,
    image_format VARCHAR(10) NOT NULL DEFAULT 'png',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    prompt TEXT NOT NULL,
    model_info JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- GDPR compliance additions
    phi_redacted BOOLEAN DEFAULT FALSE,
    original_prompt_hash BYTEA
);

-- DICOM images table (from dicom repository)
CREATE TABLE IF NOT EXISTS dicom_images (
    image_id TEXT PRIMARY KEY,
    patient_id TEXT, -- Note: will be pseudonymized in GDPR mode
    user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    metadata_json JSONB NOT NULL,
    dimensions_json JSONB NOT NULL,
    window_level_json JSONB NOT NULL,
    status TEXT NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE,
    storage_path TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- EHR connection tables (from EHR connection repository)
CREATE TABLE IF NOT EXISTS ehr_login_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    connection_id VARCHAR(255) UNIQUE NOT NULL,
    fhir_server_url TEXT NOT NULL,
    client_id VARCHAR(255) NOT NULL,
    scope TEXT NOT NULL,
    state VARCHAR(255) NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '1 hour')
);

CREATE TABLE IF NOT EXISTS user_ehr_connections (
    connection_id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    provider_type VARCHAR(100) NOT NULL,
    fhir_server_url TEXT NOT NULL,
    client_id VARCHAR(255) NOT NULL,
    credentials JSONB DEFAULT '{}',
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMP WITH TIME ZONE,
    scope TEXT,
    patient_context JSONB, -- Will be pseudonymized in GDPR mode
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for application tables
-- Use btree indexes for JSONB text extraction instead of GIN without operator class
CREATE INDEX IF NOT EXISTS idx_generated_images_user_id ON generated_images ((metadata->>'user_id'));
CREATE INDEX IF NOT EXISTS idx_generated_images_patient_id ON generated_images ((metadata->>'patient_id'));
CREATE INDEX IF NOT EXISTS idx_generated_images_session_id ON generated_images ((metadata->>'session_id'));
CREATE INDEX IF NOT EXISTS idx_generated_images_created_at ON generated_images (created_at);
-- Use GIN index for full-text search with proper tsvector
CREATE INDEX IF NOT EXISTS idx_generated_images_prompt_fts ON generated_images USING GIN (to_tsvector('english', prompt));

CREATE INDEX IF NOT EXISTS idx_dicom_images_user_id ON dicom_images(user_id);
CREATE INDEX IF NOT EXISTS idx_dicom_images_patient_id ON dicom_images(patient_id);
CREATE INDEX IF NOT EXISTS idx_dicom_images_status ON dicom_images(status);
CREATE INDEX IF NOT EXISTS idx_dicom_images_uploaded_at ON dicom_images(uploaded_at);

CREATE INDEX IF NOT EXISTS idx_ehr_connections_user_id ON user_ehr_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_ehr_connections_provider_type ON user_ehr_connections(provider_type);
CREATE INDEX IF NOT EXISTS idx_ehr_connections_active ON user_ehr_connections(is_active);
CREATE INDEX IF NOT EXISTS idx_ehr_login_sessions_expires ON ehr_login_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_ehr_login_sessions_connection ON ehr_login_sessions(connection_id);

-- Comments for application tables
COMMENT ON TABLE generated_images IS 'AI-generated images with prompt tracking and GDPR compliance';
COMMENT ON TABLE dicom_images IS 'DICOM medical images metadata with GDPR-safe patient handling';
COMMENT ON TABLE ehr_login_sessions IS 'Temporary EHR OAuth login sessions';
COMMENT ON TABLE user_ehr_connections IS 'User EHR system connections with credential management';
