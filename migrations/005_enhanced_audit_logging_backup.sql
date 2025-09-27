-- Enhanced Audit Logging and Usage Metrics
-- Migration 005: Add comprehensive audit trails and usage tracking
-- Created: 2025-01-27
-- Purpose: Enable detailed traceability and usage analytics while maintaining GDPR compliance

-- Note: Role creation requires CREATEROLE permission
-- RLS policies will use basic tenant/user isolation without specific roles

-- ============================================================================
-- 1. SYSTEM USAGE METRICS
-- ============================================================================

-- Most tables are already created by migration 002, so we only add missing indexes and views
-- Skip table creation if already exists from migration 002

-- Indexes for system_usage_metrics (if table exists)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'system_usage_metrics') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_system_usage_type_name ON system_usage_metrics(metric_type, metric_name)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_system_usage_recorded_at ON system_usage_metrics(recorded_at)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_system_usage_tenant ON system_usage_metrics(tenant_id)';
        -- Skip GIN index on JSONB for compatibility (can be added later if needed)
        -- EXECUTE 'CREATE INDEX IF NOT EXISTS idx_system_usage_dimensions ON system_usage_metrics USING GIN (dimensions)';
    END IF;
END $$;

-- ============================================================================
-- 2. ENHANCED SESSION TRACKING
-- ============================================================================

-- Track detailed session analytics
CREATE TABLE IF NOT EXISTS session_analytics (
    session_id UUID PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_role VARCHAR(100),                     -- User's role during session
    session_duration_minutes INTEGER,           -- Total session duration
    total_requests INTEGER DEFAULT 0,           -- Number of requests made
    total_responses INTEGER DEFAULT 0,          -- Number of responses generated
    patient_contexts_accessed INTEGER DEFAULT 0, -- Number of different patients accessed
    web_searches_performed INTEGER DEFAULT 0,   -- Number of web searches
    diagnostic_requests INTEGER DEFAULT 0,      -- Number of diagnostic requests
    chat_requests INTEGER DEFAULT 0,           -- Number of chat requests
    image_uploads INTEGER DEFAULT 0,           -- Number of images uploaded
    journal_generations INTEGER DEFAULT 0,     -- Number of journal entries generated
    encryption_enabled BOOLEAN DEFAULT TRUE,   -- Whether encryption was used
    data_sources_accessed TEXT[],              -- List of data sources accessed
    performance_metrics JSONB DEFAULT '{}',    -- Response times, processing metrics
    error_count INTEGER DEFAULT 0,             -- Number of errors encountered
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 3. DETAILED AUDIT EVENTS (Enhanced)
-- ============================================================================

-- GDPR-COMPLIANT: Only add essential audit columns (no PHI, no IP addresses)
-- Check if audit_events table exists before modifying
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'audit_events') THEN
        -- Add GDPR-safe audit columns
        EXECUTE 'ALTER TABLE audit_events
                 ADD COLUMN IF NOT EXISTS user_id UUID,
                 ADD COLUMN IF NOT EXISTS patient_context_hash VARCHAR(255),  -- Hashed patient ID (no PHI)
                 ADD COLUMN IF NOT EXISTS data_source VARCHAR(100),
                 ADD COLUMN IF NOT EXISTS request_size_bytes INTEGER,
                 ADD COLUMN IF NOT EXISTS response_size_bytes INTEGER,
                 ADD COLUMN IF NOT EXISTS processing_time_ms INTEGER,
                 ADD COLUMN IF NOT EXISTS encryption_used BOOLEAN DEFAULT TRUE,  -- Default to encrypted
                 ADD COLUMN IF NOT EXISTS error_code VARCHAR(50),
                 ADD COLUMN IF NOT EXISTS compliance_flags TEXT[]';

        -- Create indexes for performance (avoid JSONB GIN index for now)
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_audit_events_user_id ON audit_events(user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_audit_events_patient_hash ON audit_events(patient_context_hash)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_audit_events_data_source ON audit_events(data_source)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_audit_events_processing_time ON audit_events(processing_time_ms)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_audit_events_encryption ON audit_events(encryption_used)';
    END IF;
END $$;

-- ============================================================================
-- 4. DATA ACCESS LOGGING
-- ============================================================================

-- GDPR-COMPLIANT data access audit trail (NO PHI stored)
CREATE TABLE IF NOT EXISTS data_access_logs (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE SET NULL,
    user_id UUID NOT NULL,
    access_type VARCHAR(100) NOT NULL,          -- 'read', 'write', 'delete', 'search'
    resource_type VARCHAR(100) NOT NULL,        -- 'patient_data', 'observation', 'image', etc.
    resource_count INTEGER DEFAULT 1,           -- Number of resources accessed (no IDs)
    data_source VARCHAR(100) NOT NULL,          -- Source system (EHR, database, etc.)
    access_method VARCHAR(100),                 -- API, direct, etc.
    field_categories TEXT[],                    -- Categories of fields (not specific field names)
    returned_count INTEGER,                     -- Number of records returned
    lawful_basis VARCHAR(100) NOT NULL,        -- GDPR lawful basis for processing
    purpose_of_use VARCHAR(200) NOT NULL,      -- Why data was accessed
    data_retention_days INTEGER DEFAULT 30,    -- Data retention policy applied
    encryption_method VARCHAR(100) DEFAULT 'aes-256-gcm', -- Encryption used
    access_granted BOOLEAN NOT NULL DEFAULT TRUE,
    denial_reason TEXT,                         -- If access denied, why (sanitized)
    access_duration_ms INTEGER,                -- Processing time
    privacy_impact_level VARCHAR(50) DEFAULT 'low', -- 'low', 'medium', 'high'
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- GDPR-safe indexes for data_access_logs
CREATE INDEX IF NOT EXISTS idx_data_access_user_id ON data_access_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_data_access_resource_type ON data_access_logs(resource_type);
CREATE INDEX IF NOT EXISTS idx_data_access_source ON data_access_logs(data_source);
CREATE INDEX IF NOT EXISTS idx_data_access_time ON data_access_logs(accessed_at);
CREATE INDEX IF NOT EXISTS idx_data_access_session ON data_access_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_data_access_purpose ON data_access_logs(purpose_of_use);
CREATE INDEX IF NOT EXISTS idx_data_access_privacy_level ON data_access_logs(privacy_impact_level);

-- ============================================================================
-- 5. PERFORMANCE METRICS
-- ============================================================================

-- Track system performance metrics
CREATE TABLE IF NOT EXISTS performance_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_category VARCHAR(100) NOT NULL,     -- 'latency', 'throughput', 'resource_usage'
    metric_name VARCHAR(200) NOT NULL,         -- Specific metric
    value DECIMAL(15,6) NOT NULL,              -- Metric value
    unit VARCHAR(50) NOT NULL,                 -- Unit of measurement
    endpoint VARCHAR(200),                     -- API endpoint if applicable
    user_id UUID,                              -- User context if applicable
    session_id UUID,                           -- Session context if applicable
    patient_context_size INTEGER,              -- Size of patient context processed
    model_used VARCHAR(100),                   -- AI model used
    processing_stage VARCHAR(100),             -- Which stage of processing
    additional_context JSONB DEFAULT '{}',    -- Additional performance context
    measured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for performance_metrics
CREATE INDEX IF NOT EXISTS idx_perf_category_name ON performance_metrics(metric_category, metric_name);
CREATE INDEX IF NOT EXISTS idx_perf_endpoint ON performance_metrics(endpoint);
CREATE INDEX IF NOT EXISTS idx_perf_measured_at ON performance_metrics(measured_at);
CREATE INDEX IF NOT EXISTS idx_perf_model ON performance_metrics(model_used);

-- ============================================================================
-- 6. ENCRYPTION AUDIT TRAIL
-- ============================================================================

-- Track all encryption operations for security auditing
CREATE TABLE IF NOT EXISTS encryption_audit_log (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE SET NULL,
    user_id UUID,
    operation_type VARCHAR(100) NOT NULL,      -- 'encrypt', 'decrypt', 'key_generate', 'key_rotate'
    data_type VARCHAR(100) NOT NULL,           -- 'patient_data', 'user_message', 'session_state'
    encryption_algorithm VARCHAR(100) NOT NULL, -- 'fernet', 'rsa-2048', 'aes-256-gcm'
    key_type VARCHAR(100) NOT NULL,            -- 'session_key', 'master_key', 'transport_key'
    key_identifier VARCHAR(255),               -- Key ID (not the actual key)
    data_size_bytes INTEGER,                   -- Size of data processed
    operation_duration_ms INTEGER,             -- Time taken for operation
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_details TEXT,                        -- Error message if failed
    client_info JSONB DEFAULT '{}',           -- Client information (browser, IP)
    compliance_context JSONB DEFAULT '{}',    -- GDPR/HIPAA context
    operation_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for encryption_audit_log
CREATE INDEX IF NOT EXISTS idx_encryption_operation ON encryption_audit_log(operation_type);
CREATE INDEX IF NOT EXISTS idx_encryption_data_type ON encryption_audit_log(data_type);
CREATE INDEX IF NOT EXISTS idx_encryption_algorithm ON encryption_audit_log(encryption_algorithm);
CREATE INDEX IF NOT EXISTS idx_encryption_performed_at ON encryption_audit_log(operation_timestamp);
CREATE INDEX IF NOT EXISTS idx_encryption_success ON encryption_audit_log(success);
CREATE INDEX IF NOT EXISTS idx_encryption_session ON encryption_audit_log(session_id);

-- ============================================================================
-- 7. COMPLIANCE TRACKING
-- ============================================================================

-- Track compliance-related events and decisions
CREATE TABLE IF NOT EXISTS compliance_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,          -- 'data_access', 'consent_given', 'data_deletion'
    compliance_framework VARCHAR(100) NOT NULL, -- 'GDPR', 'HIPAA', 'ISO27001'
    session_id UUID REFERENCES sessions(session_id) ON DELETE SET NULL,
    user_id UUID NOT NULL,
    patient_id VARCHAR(255),                   -- Hashed patient ID
    lawful_basis VARCHAR(200),                 -- Legal basis for processing
    consent_status VARCHAR(100),               -- 'given', 'withdrawn', 'pending'
    data_categories TEXT[],                    -- Categories of data involved
    processing_purposes TEXT[],                -- Purposes for processing
    retention_period_days INTEGER,            -- Data retention period
    data_minimization_applied BOOLEAN DEFAULT TRUE,
    anonymization_method VARCHAR(100),        -- If data was anonymized
    cross_border_transfer BOOLEAN DEFAULT FALSE,
    transfer_safeguards TEXT[],                -- Safeguards for international transfers
    individual_rights_exercised TEXT[],       -- Rights exercised (access, rectification, etc.)
    compliance_status VARCHAR(100) NOT NULL DEFAULT 'compliant',
    risk_assessment JSONB DEFAULT '{}',       -- Risk assessment details
    mitigation_measures TEXT[],               -- Measures taken to mitigate risks
    documentation_references TEXT[],          -- Links to supporting documentation
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for compliance_events
CREATE INDEX IF NOT EXISTS idx_compliance_event_type ON compliance_events(event_type);
CREATE INDEX IF NOT EXISTS idx_compliance_framework ON compliance_events(compliance_framework);
CREATE INDEX IF NOT EXISTS idx_compliance_user_id ON compliance_events(user_id);
CREATE INDEX IF NOT EXISTS idx_compliance_patient_id ON compliance_events(patient_id);
CREATE INDEX IF NOT EXISTS idx_compliance_status ON compliance_events(compliance_status);
CREATE INDEX IF NOT EXISTS idx_compliance_occurred_at ON compliance_events(occurred_at);

-- ============================================================================
-- 8. GDPR DATA SUBJECT REQUESTS
-- ============================================================================

-- GDPR Data Subject Rights Management (Privacy-by-Design)
CREATE TABLE IF NOT EXISTS gdpr_requests (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    subject_hash VARCHAR(255) NOT NULL,        -- Cryptographically hashed subject identifier
    request_type VARCHAR(100) NOT NULL,        -- 'access', 'rectification', 'erasure', 'portability'
    request_category VARCHAR(100),             -- Category of request for metrics
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,               -- When request was acknowledged
    processed_at TIMESTAMPTZ,                  -- When request was completed
    response_method VARCHAR(100),              -- 'secure_email', 'postal', 'in_person'
    data_categories_involved TEXT[],           -- Categories only (no specific data)
    systems_searched TEXT[],                   -- Systems searched for data
    data_found BOOLEAN,                        -- Whether relevant data was found
    data_provided BOOLEAN DEFAULT FALSE,      -- Whether data was provided to subject
    data_rectified BOOLEAN DEFAULT FALSE,     -- Whether data was corrected
    data_erased BOOLEAN DEFAULT FALSE,         -- Whether data was deleted
    processing_days INTEGER,                   -- Days taken to process
    compliance_deadline TIMESTAMPTZ,          -- Legal deadline for response (30 days)
    status VARCHAR(100) NOT NULL DEFAULT 'received', -- 'received', 'processing', 'completed', 'rejected'
    rejection_reason_category VARCHAR(100),   -- Category of rejection (no personal details)
    follow_up_required BOOLEAN DEFAULT FALSE,
    created_by_role VARCHAR(100),             -- Role, not individual (privacy)
    assigned_to_role VARCHAR(100),            -- Role, not individual (privacy)
    automated_processing BOOLEAN DEFAULT FALSE -- Whether processing was automated
);

-- GDPR-safe indexes for gdpr_requests
CREATE INDEX IF NOT EXISTS idx_gdpr_request_id ON gdpr_requests(request_id);
CREATE INDEX IF NOT EXISTS idx_gdpr_subject_hash ON gdpr_requests(subject_hash);
CREATE INDEX IF NOT EXISTS idx_gdpr_type ON gdpr_requests(request_type);
CREATE INDEX IF NOT EXISTS idx_gdpr_status ON gdpr_requests(status);
CREATE INDEX IF NOT EXISTS idx_gdpr_deadline ON gdpr_requests(compliance_deadline);
CREATE INDEX IF NOT EXISTS idx_gdpr_received_at ON gdpr_requests(received_at);
CREATE INDEX IF NOT EXISTS idx_gdpr_category ON gdpr_requests(request_category);

-- ============================================================================
-- 9. SYSTEM HEALTH AND MONITORING
-- ============================================================================

-- Track system health metrics for operational monitoring
CREATE TABLE IF NOT EXISTS system_health_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_name VARCHAR(200) NOT NULL,
    metric_value DECIMAL(15,6) NOT NULL,
    metric_unit VARCHAR(50) NOT NULL,
    component VARCHAR(100) NOT NULL,           -- 'database', 'encryption', 'api', 'ml_models'
    environment VARCHAR(50) NOT NULL,          -- 'production', 'staging', 'development'
    severity_level VARCHAR(50),                -- 'info', 'warning', 'error', 'critical'
    alert_threshold DECIMAL(15,6),             -- Threshold for alerting
    metadata JSONB DEFAULT '{}',               -- Additional metadata
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for system_health_metrics
CREATE INDEX IF NOT EXISTS idx_health_component ON system_health_metrics(component);
CREATE INDEX IF NOT EXISTS idx_health_name ON system_health_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_health_severity ON system_health_metrics(severity_level);
CREATE INDEX IF NOT EXISTS idx_health_recorded_at ON system_health_metrics(recorded_at);

-- ============================================================================
-- 10. DATA LINEAGE TRACKING
-- ============================================================================

-- Track data lineage for transparency and debugging
CREATE TABLE IF NOT EXISTS data_lineage (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
    source_system VARCHAR(100) NOT NULL,       -- Where data originated
    source_resource_id VARCHAR(255) NOT NULL,  -- ID in source system
    transformation_type VARCHAR(100),          -- 'chunking', 'embedding', 'encryption', 'anonymization'
    transformation_details JSONB DEFAULT '{}', -- Details of transformation
    destination_system VARCHAR(100),           -- Where data was sent/stored
    destination_resource_id VARCHAR(255),      -- ID in destination system
    data_hash BYTEA,                           -- Hash of data for integrity verification
    parent_lineage_id BIGINT REFERENCES data_lineage(id), -- Parent transformation
    processing_algorithm VARCHAR(100),         -- Algorithm/model used
    quality_score DECIMAL(5,4),               -- Data quality score (0-1)
    privacy_level VARCHAR(100),               -- 'public', 'internal', 'confidential', 'restricted'
    retention_policy VARCHAR(100),            -- Data retention policy applied
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ                   -- When this lineage record expires
);

-- Indexes for data_lineage
CREATE INDEX IF NOT EXISTS idx_lineage_session ON data_lineage(session_id);
CREATE INDEX IF NOT EXISTS idx_lineage_source ON data_lineage(source_system, source_resource_id);
CREATE INDEX IF NOT EXISTS idx_lineage_destination ON data_lineage(destination_system, destination_resource_id);
CREATE INDEX IF NOT EXISTS idx_lineage_parent ON data_lineage(parent_lineage_id);
CREATE INDEX IF NOT EXISTS idx_lineage_created_at ON data_lineage(created_at);

-- ============================================================================
-- 11. VIEWS FOR REPORTING
-- ============================================================================

-- Create useful views for reporting and analytics (handle table existence)

-- User activity summary view (safe with type casting)
DO $$
BEGIN
    -- Only create view if all required tables exist
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') AND
       EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sessions') AND
       EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'session_analytics') THEN

        EXECUTE 'CREATE OR REPLACE VIEW user_activity_summary AS
        SELECT
            u.user_id,
            u.username,
            u.role,
            COUNT(s.session_id) as total_sessions,
            COUNT(ae.id) as total_actions,
            AVG(sa.session_duration_minutes) as avg_session_duration,
            SUM(sa.total_requests) as total_requests,
            SUM(sa.patient_contexts_accessed) as total_patients_accessed,
            SUM(sa.web_searches_performed) as total_web_searches,
            MAX(s.started_at) as last_activity
        FROM users u
        LEFT JOIN sessions s ON u.user_id::UUID = s.user_id
        LEFT JOIN session_analytics sa ON s.session_id = sa.session_id
        LEFT JOIN audit_events ae ON s.session_id = ae.session_id
        WHERE s.started_at >= NOW() - INTERVAL ''30 days''
        GROUP BY u.user_id, u.username, u.role';

    END IF;
END $$;

-- System performance summary view (conditional creation)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'performance_metrics') THEN
        EXECUTE 'CREATE OR REPLACE VIEW system_performance_summary AS
        SELECT
            DATE_TRUNC(''hour'', measured_at) as hour,
            metric_category,
            metric_name,
            AVG(value) as avg_value,
            MIN(value) as min_value,
            MAX(value) as max_value,
            COUNT(*) as measurement_count
        FROM performance_metrics
        WHERE measured_at >= NOW() - INTERVAL ''24 hours''
        GROUP BY DATE_TRUNC(''hour'', measured_at), metric_category, metric_name
        ORDER BY hour DESC';
    END IF;
END $$;

-- Compliance status view (conditional creation)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'compliance_events') THEN
        EXECUTE 'CREATE OR REPLACE VIEW compliance_status_summary AS
        SELECT
            compliance_framework,
            event_type,
            compliance_status,
            COUNT(*) as event_count,
            DATE_TRUNC(''day'', occurred_at) as event_date
        FROM compliance_events
        WHERE occurred_at >= NOW() - INTERVAL ''30 days''
        GROUP BY compliance_framework, event_type, compliance_status, DATE_TRUNC(''day'', occurred_at)
        ORDER BY event_date DESC';
    END IF;
END $$;

-- ============================================================================
-- 12. ROW LEVEL SECURITY POLICIES
-- ============================================================================

-- NOTE: RLS is currently DISABLED for backend compatibility
-- Enable when application adds session variable support

-- RLS Policies (disabled for now - uncomment when enabling RLS)
-- CREATE POLICY tenant_isolation_system_usage ON system_usage_metrics
--     FOR ALL
--     USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);

-- CREATE POLICY user_data_access_logs ON data_access_logs
--     FOR ALL
--     USING (user_id = current_setting('app.current_user_id', true)::UUID);

-- CREATE POLICY user_encryption_audit ON encryption_audit_log
--     FOR ALL
--     USING (user_id = current_setting('app.current_user_id', true)::UUID);

-- CREATE POLICY compliance_access ON compliance_events
--     FOR ALL
--     USING (user_id = current_setting('app.current_user_id', true)::UUID);

-- ============================================================================
-- 13. TRIGGERS FOR AUTOMATIC UPDATES
-- ============================================================================

-- Trigger to automatically update session analytics
CREATE OR REPLACE FUNCTION update_session_analytics()
RETURNS TRIGGER AS $$
DECLARE
    user_role_val VARCHAR(50);
BEGIN
    -- Try to get role from users table (handles both original and GDPR-safe tables)
    SELECT role INTO user_role_val
    FROM users
    WHERE user_id = NEW.user_id::VARCHAR
    LIMIT 1;

    -- If not found in users table, try users_gdpr_safe
    IF user_role_val IS NULL THEN
        SELECT role INTO user_role_val
        FROM users_gdpr_safe
        WHERE user_id = NEW.user_id::VARCHAR
        LIMIT 1;
    END IF;

    INSERT INTO session_analytics (session_id, user_role)
    VALUES (NEW.session_id, COALESCE(user_role_val, 'unknown'))
    ON CONFLICT (session_id) DO NOTHING;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER session_analytics_trigger
    AFTER INSERT ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_session_analytics();

-- Trigger to update session duration when session ends
CREATE OR REPLACE FUNCTION update_session_duration()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.ended_at IS NOT NULL AND OLD.ended_at IS NULL THEN
        UPDATE session_analytics
        SET session_duration_minutes = EXTRACT(EPOCH FROM (NEW.ended_at - NEW.started_at)) / 60,
            last_updated = NOW()
        WHERE session_id = NEW.session_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER session_duration_trigger
    AFTER UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_session_duration();

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

-- Log the completion of this migration (only if table exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'system_usage_metrics') THEN
        INSERT INTO system_usage_metrics (
            metric_type,
            metric_name,
            value,
            unit,
            dimensions
        ) VALUES (
            'migration',
            'enhanced_audit_logging_completed',
            1,
            'count',
            ('{"migration_version": "005", "timestamp": "' || NOW()::text || '"}')::JSONB
        );
    END IF;
END $$;

COMMENT ON TABLE system_usage_metrics IS 'Tracks detailed system usage patterns for analytics and capacity planning';
COMMENT ON TABLE session_analytics IS 'Provides comprehensive session-level analytics while maintaining privacy';
COMMENT ON TABLE data_access_logs IS 'Logs all data access for GDPR compliance and security auditing';
COMMENT ON TABLE performance_metrics IS 'Tracks system performance metrics for monitoring and optimization';
COMMENT ON TABLE encryption_audit_log IS 'Audits all encryption operations for security compliance';
COMMENT ON TABLE compliance_events IS 'Tracks compliance-related events and decisions';
COMMENT ON TABLE gdpr_requests IS 'Manages GDPR data subject requests and responses';
COMMENT ON TABLE system_health_metrics IS 'Monitors system health for operational alerting';
COMMENT ON TABLE data_lineage IS 'Tracks data transformations for transparency and debugging';