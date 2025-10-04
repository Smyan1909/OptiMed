-- Migration 007: Fix audit logging user_id nullable constraint
-- Created: 2025-10-01
-- Purpose: Allow NULL user_id in data_access_logs for system-level audit events

-- Make user_id nullable in data_access_logs
ALTER TABLE data_access_logs
ALTER COLUMN user_id DROP NOT NULL;

-- Add comment to document the change
COMMENT ON COLUMN data_access_logs.user_id IS 'User ID (nullable for system-level events or unauthenticated requests)';

-- Log the completion of this migration
INSERT INTO system_usage_metrics (
    metric_type,
    metric_name,
    value,
    unit,
    dimensions
) VALUES (
    'migration',
    'fix_audit_user_id_nullable_completed',
    1,
    'count',
    ('{"migration_version": "007", "timestamp": "' || NOW()::text || '"}')::JSONB
);
