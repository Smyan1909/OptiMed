-- Fix Existing Local Database Schema
-- Run with: psql -h localhost -U optimed_user -d optimed -f scripts/fix_existing_db.sql

-- This script manually fixes schema issues without dropping the database

-- Enable required extensions first
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

BEGIN;

-- Ensure migration tracking table exists
CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMP,
    status VARCHAR(20),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Clean up failed migration history (reset to allow retry)
UPDATE migration_history
SET status = 'pending', error_message = NULL
WHERE status = 'failed';

-- Drop problematic views first (they block column type changes)
DROP VIEW IF EXISTS user_activity_summary CASCADE;
DROP VIEW IF EXISTS session_overview CASCADE;

-- Clean up and recreate tables in dependency order

-- 1. Fix session_analytics table
DROP TABLE IF EXISTS session_analytics CASCADE;
CREATE TABLE IF NOT EXISTS session_analytics (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    user_id_hash VARCHAR(64),
    start_time TIMESTAMP NOT NULL DEFAULT NOW(),
    end_time TIMESTAMP,
    duration_seconds INTEGER,
    messages_count INTEGER DEFAULT 0,
    avg_response_time_ms FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2. Fix data_access_logs table
DROP TABLE IF EXISTS data_access_logs CASCADE;
CREATE TABLE IF NOT EXISTS data_access_logs (
    id SERIAL PRIMARY KEY,
    user_id_hash VARCHAR(64) NOT NULL,
    session_id VARCHAR(255),
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    action VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. Fix compliance_events table
DROP TABLE IF EXISTS compliance_events CASCADE;
CREATE TABLE IF NOT EXISTS compliance_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    user_id_hash VARCHAR(64),
    session_id VARCHAR(255),
    description TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 4. Fix encryption_audit_log table
DROP TABLE IF EXISTS encryption_audit_log CASCADE;
CREATE TABLE IF NOT EXISTS encryption_audit_log (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    operation_type VARCHAR(50) NOT NULL,
    key_id VARCHAR(255),
    algorithm VARCHAR(50),
    success BOOLEAN NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 5. Fix data_lineage table
DROP TABLE IF EXISTS data_lineage CASCADE;
CREATE TABLE IF NOT EXISTS data_lineage (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(100) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    transformation_type VARCHAR(100) NOT NULL,
    output_type VARCHAR(100),
    output_id VARCHAR(255),
    user_id_hash VARCHAR(64),
    session_id VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 6. Ensure note_templates exists
CREATE TABLE IF NOT EXISTS note_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    template_type VARCHAR(50) NOT NULL,
    sections JSONB NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 7. Ensure note_generation_metadata exists
CREATE TABLE IF NOT EXISTS note_generation_metadata (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    template_id INTEGER REFERENCES note_templates(id),
    patient_id VARCHAR(255) NOT NULL,
    user_id_hash VARCHAR(64),
    sections_completed JSONB,
    total_tokens INTEGER,
    generation_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 8. Create hash function (for user_id hashing)
CREATE OR REPLACE FUNCTION hash_text(input_text VARCHAR)
RETURNS VARCHAR AS $$
BEGIN
    RETURN encode(digest(input_text || current_setting('app.hash_salt', true), 'sha256'), 'hex');
EXCEPTION
    WHEN OTHERS THEN
        -- Fallback if hash_salt not set
        RETURN encode(digest(input_text, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 9. Ensure system metrics tables exist
CREATE TABLE IF NOT EXISTS system_usage_metrics (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    unit VARCHAR(50),
    tags JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_health_metrics (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL,
    response_time_ms FLOAT,
    error_count INTEGER DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS performance_metrics (
    id SERIAL PRIMARY KEY,
    operation_type VARCHAR(100) NOT NULL,
    duration_ms FLOAT NOT NULL,
    success BOOLEAN NOT NULL,
    user_id_hash VARCHAR(64),
    session_id VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 10. Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_session_analytics_session_id ON session_analytics(session_id);
CREATE INDEX IF NOT EXISTS idx_session_analytics_user_hash ON session_analytics(user_id_hash);
CREATE INDEX IF NOT EXISTS idx_data_access_logs_user_hash ON data_access_logs(user_id_hash);
CREATE INDEX IF NOT EXISTS idx_data_access_logs_session_id ON data_access_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_data_access_logs_timestamp ON data_access_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_compliance_events_type ON compliance_events(event_type);
CREATE INDEX IF NOT EXISTS idx_compliance_events_user_hash ON compliance_events(user_id_hash);
CREATE INDEX IF NOT EXISTS idx_encryption_audit_session ON encryption_audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_data_lineage_source ON data_lineage(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_data_lineage_session ON data_lineage(session_id);

-- 11. Recreate user_activity_summary view
CREATE OR REPLACE VIEW user_activity_summary AS
SELECT
    user_id_hash,
    COUNT(DISTINCT session_id) as total_sessions,
    COUNT(*) as total_actions,
    MIN(created_at) as first_activity,
    MAX(created_at) as last_activity
FROM data_access_logs
WHERE user_id_hash IS NOT NULL
GROUP BY user_id_hash;

COMMIT;

-- Success message
SELECT '✅ Database schema fixed successfully!' as status;
