-- Migration 009: Drop foreign key constraints from audit tables
-- Created: 2025-10-01
-- Purpose: Remove session_id foreign key constraints that prevent audit logging

-- First, find and drop all foreign key constraints on data_access_logs.session_id
DO $$
DECLARE
    constraint_rec RECORD;
BEGIN
    -- Find constraints on data_access_logs
    FOR constraint_rec IN
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = 'data_access_logs'
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name LIKE '%session%'
    LOOP
        EXECUTE format('ALTER TABLE data_access_logs DROP CONSTRAINT IF EXISTS %I', constraint_rec.constraint_name);
        RAISE NOTICE 'Dropped constraint: %', constraint_rec.constraint_name;
    END LOOP;
END $$;

-- Drop foreign key constraints on data_lineage.session_id
DO $$
DECLARE
    constraint_rec RECORD;
BEGIN
    -- Find constraints on data_lineage
    FOR constraint_rec IN
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = 'data_lineage'
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name LIKE '%session%'
    LOOP
        EXECUTE format('ALTER TABLE data_lineage DROP CONSTRAINT IF EXISTS %I', constraint_rec.constraint_name);
        RAISE NOTICE 'Dropped constraint: %', constraint_rec.constraint_name;
    END LOOP;
END $$;

-- Add comments
COMMENT ON COLUMN data_access_logs.session_id IS 'Session ID (no foreign key constraint - allows audit logging without session table entries)';
COMMENT ON COLUMN data_lineage.session_id IS 'Session ID (no foreign key constraint - allows audit logging without session table entries)';

-- Log the completion of this migration
INSERT INTO system_usage_metrics (
    metric_type,
    metric_name,
    value,
    unit,
    dimensions
) VALUES (
    'migration',
    'drop_audit_foreign_keys_completed',
    1,
    'count',
    ('{"migration_version": "009", "timestamp": "' || NOW()::text || '"}')::JSONB
);
