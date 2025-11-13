-- Fix Existing Local Database Schema (Version 2)
-- Run with Python script to fix existing database

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

-- Reset all failed migrations so they can be retried
DELETE FROM migration_history WHERE status = 'failed';

-- Drop all existing analytics/audit tables to allow migration 002 to recreate them properly
DROP TABLE IF EXISTS session_analytics CASCADE;
DROP TABLE IF EXISTS data_access_logs CASCADE;
DROP TABLE IF EXISTS compliance_events CASCADE;
DROP TABLE IF EXISTS encryption_audit_log CASCADE;
DROP TABLE IF EXISTS data_lineage CASCADE;
DROP TABLE IF EXISTS system_usage_metrics CASCADE;
DROP TABLE IF EXISTS system_health_metrics CASCADE;
DROP TABLE IF EXISTS performance_metrics CASCADE;

-- Drop problemat views
DROP VIEW IF EXISTS user_activity_summary CASCADE;
DROP VIEW IF EXISTS session_overview CASCADE;

-- Keep core user tables if they exist (migration 002 will handle them with IF NOT EXISTS)
-- Keep other tables that migrations expect

COMMIT;

-- Success message
SELECT '✅ Database cleaned up - ready for migrations!' as status;
