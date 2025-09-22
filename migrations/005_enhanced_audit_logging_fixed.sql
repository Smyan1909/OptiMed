-- Enhanced Audit Logging and Usage Metrics (Migration 005 - FIXED)
-- Migration 005: Add missing indexes and views only (tables created in migration 002)
-- Created: 2025-01-27
-- Purpose: Complete the audit setup with views and additional indexes

-- ============================================================================
-- SKIP TABLE CREATION - TABLES ALREADY EXIST FROM MIGRATION 002
-- ============================================================================

-- Migration 002 already created all these tables:
-- - system_usage_metrics
-- - session_analytics
-- - data_access_logs
-- - performance_metrics
-- - encryption_audit_log
-- - compliance_events
-- - gdpr_requests
-- - system_health_metrics
-- - data_lineage

-- This migration only adds missing indexes and useful views

-- ============================================================================
-- ENHANCED INDEXES (Only if tables exist)
-- ============================================================================

-- Additional indexes for system_usage_metrics
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'system_usage_metrics') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_system_usage_tenant ON system_usage_metrics(tenant_id)';
    END IF;
END $$;

-- Additional indexes for session_analytics
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'session_analytics') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_session_analytics_duration ON session_analytics(session_duration_minutes)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_session_analytics_requests ON session_analytics(total_requests)';
    END IF;
END $$;

-- Additional indexes for performance_metrics
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'performance_metrics') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_perf_endpoint ON performance_metrics(endpoint)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_perf_model ON performance_metrics(model_used)';
    END IF;
END $$;

-- Additional indexes for system_health_metrics
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'system_health_metrics') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_health_severity ON system_health_metrics(status)';
    END IF;
END $$;

-- ============================================================================
-- USEFUL VIEWS FOR REPORTING (Only if tables exist)
-- ============================================================================

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
        LEFT JOIN sessions s ON u.user_id = s.user_id
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
            DATE_TRUNC(''day'', event_timestamp) as event_date
        FROM compliance_events
        WHERE event_timestamp >= NOW() - INTERVAL ''30 days''
        GROUP BY compliance_framework, event_type, compliance_status, DATE_TRUNC(''day'', event_timestamp)
        ORDER BY event_date DESC';
    END IF;
END $$;

-- ============================================================================
-- TRIGGERS FOR AUTOMATIC UPDATES (Only if tables exist)
-- ============================================================================

-- Trigger to automatically update session analytics
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sessions') AND
       EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'session_analytics') AND
       EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN

        -- Create trigger function
        EXECUTE 'CREATE OR REPLACE FUNCTION update_session_analytics()
        RETURNS TRIGGER AS $trigger$
        DECLARE
            user_role_val VARCHAR(50);
        BEGIN
            -- Try to get role from users table
            SELECT role INTO user_role_val
            FROM users
            WHERE user_id = NEW.user_id
            LIMIT 1;

            INSERT INTO session_analytics (session_id, user_id)
            VALUES (NEW.session_id, NEW.user_id)
            ON CONFLICT (session_id) DO NOTHING;

            RETURN NEW;
        END;
        $trigger$ LANGUAGE plpgsql';

        -- Drop existing trigger if it exists
        EXECUTE 'DROP TRIGGER IF EXISTS session_analytics_trigger ON sessions';

        -- Create new trigger
        EXECUTE 'CREATE TRIGGER session_analytics_trigger
            AFTER INSERT ON sessions
            FOR EACH ROW
            EXECUTE FUNCTION update_session_analytics()';

    END IF;
END $$;

-- Trigger to update session duration when session ends
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sessions') AND
       EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'session_analytics') THEN

        -- Create duration update function
        EXECUTE 'CREATE OR REPLACE FUNCTION update_session_duration()
        RETURNS TRIGGER AS $trigger$
        BEGIN
            IF NEW.ended_at IS NOT NULL AND OLD.ended_at IS NULL THEN
                UPDATE session_analytics
                SET session_duration_minutes = EXTRACT(EPOCH FROM (NEW.ended_at - NEW.started_at)) / 60,
                    last_updated = NOW()
                WHERE session_id = NEW.session_id;
            END IF;
            RETURN NEW;
        END;
        $trigger$ LANGUAGE plpgsql';

        -- Drop existing trigger if it exists
        EXECUTE 'DROP TRIGGER IF EXISTS session_duration_trigger ON sessions';

        -- Create new trigger
        EXECUTE 'CREATE TRIGGER session_duration_trigger
            AFTER UPDATE ON sessions
            FOR EACH ROW
            EXECUTE FUNCTION update_session_duration()';

    END IF;
END $$;

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