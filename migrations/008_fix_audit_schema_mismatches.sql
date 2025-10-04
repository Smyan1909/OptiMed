-- Migration 008: Fix audit logging schema mismatches and foreign key constraints
-- Created: 2025-10-01
-- Purpose: Fix session_id foreign key constraints and data_lineage column mismatches

-- 1. Make session_id nullable in data_access_logs (allow logging without session context)
ALTER TABLE data_access_logs
ALTER COLUMN session_id DROP NOT NULL;

-- 2. Make session_id nullable in data_lineage (allow logging without session context)
ALTER TABLE data_lineage
ALTER COLUMN session_id DROP NOT NULL;

-- 3. Fix data_lineage column names to match audit repository code
-- Rename columns to match what the code expects
ALTER TABLE data_lineage
RENAME COLUMN source_type TO source_resource_id;

ALTER TABLE data_lineage
RENAME COLUMN destination_type TO destination_resource_id;

ALTER TABLE data_lineage
RENAME COLUMN processing_timestamp TO created_at;

-- 4. Replace transformation_applied (TEXT[]) with transformation_type (TEXT) and transformation_details (JSONB)
ALTER TABLE data_lineage
DROP COLUMN transformation_applied;

ALTER TABLE data_lineage
ADD COLUMN transformation_type TEXT;

ALTER TABLE data_lineage
ADD COLUMN transformation_details JSONB DEFAULT '{}';

-- 5. Rename data_quality_score to quality_score
ALTER TABLE data_lineage
RENAME COLUMN data_quality_score TO quality_score;

-- Add comments to document the changes
COMMENT ON COLUMN data_access_logs.session_id IS 'Session ID (nullable for system-level events or unauthenticated requests)';
COMMENT ON COLUMN data_lineage.session_id IS 'Session ID (nullable for system-level data flows)';
COMMENT ON COLUMN data_lineage.source_resource_id IS 'Source resource identifier or type';
COMMENT ON COLUMN data_lineage.destination_resource_id IS 'Destination resource identifier or type';
COMMENT ON COLUMN data_lineage.transformation_type IS 'Type of transformation applied (comma-separated list)';
COMMENT ON COLUMN data_lineage.transformation_details IS 'Detailed transformation metadata (JSONB)';
COMMENT ON COLUMN data_lineage.quality_score IS 'Data quality score (0-1)';

-- Log the completion of this migration
INSERT INTO system_usage_metrics (
    metric_type,
    metric_name,
    value,
    unit,
    dimensions
) VALUES (
    'migration',
    'fix_audit_schema_mismatches_completed',
    1,
    'count',
    ('{"migration_version": "008", "timestamp": "' || NOW()::text || '"}')::JSONB
);
