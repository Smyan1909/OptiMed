-- Fix Existing Local Database Schema (Version 3)
-- Comprehensive cleanup to match production migration expectations

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

-- Reset all failed migrations
DELETE FROM migration_history WHERE status = 'failed';

-- Drop ALL tables that migration 002 will create
-- This ensures migration 002 can create them with the correct schema

DROP TABLE IF EXISTS gdpr_requests CASCADE;
DROP TABLE IF EXISTS system_health_metrics CASCADE;
DROP TABLE IF EXISTS data_lineage CASCADE;
DROP TABLE IF EXISTS compliance_events CASCADE;
DROP TABLE IF EXISTS encryption_audit_log CASCADE;
DROP TABLE IF EXISTS performance_metrics CASCADE;
DROP TABLE IF EXISTS data_access_logs CASCADE;
DROP TABLE IF EXISTS session_analytics CASCADE;
DROP TABLE IF EXISTS system_usage_metrics CASCADE;
DROP TABLE IF EXISTS audit_events CASCADE;

-- Drop duplicate "_gdpr_safe" tables (these shouldn't exist)
DROP TABLE IF EXISTS users_gdpr_safe CASCADE;
DROP TABLE IF EXISTS user_sessions_gdpr_safe CASCADE;
DROP TABLE IF EXISTS user_actions_gdpr_safe CASCADE;

-- Drop problematic views
DROP VIEW IF EXISTS user_activity_summary CASCADE;
DROP VIEW IF EXISTS session_overview CASCADE;

-- Drop deprecated/backup tables
DROP TABLE IF EXISTS embeddings_deprecated CASCADE;
DROP TABLE IF EXISTS embeddings_backup CASCADE;
DROP TABLE IF EXISTS embeddings_metadata CASCADE;
DROP TABLE IF EXISTS schema_migrations CASCADE;

-- Drop the hash_text function if it exists (migration 011 will recreate it)
DROP FUNCTION IF EXISTS hash_text(VARCHAR) CASCADE;
DROP FUNCTION IF EXISTS hash_text(TEXT) CASCADE;

COMMIT;

-- Success message
SELECT '✅ Database cleaned - ready for fresh migrations!' as status;
