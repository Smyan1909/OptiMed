-- Migration 014: Add missing columns to fix runtime errors
-- Fixes: is_active column, audit logging columns, audit_events columns

-- 1. Add missing columns to audit_events table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'audit_events' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE audit_events
        ADD COLUMN user_id VARCHAR(255);

        COMMENT ON COLUMN audit_events.user_id IS
        'User ID who performed the action (VARCHAR for compatibility)';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'audit_events' AND column_name = 'metadata'
    ) THEN
        ALTER TABLE audit_events
        ADD COLUMN metadata JSONB DEFAULT '{}';

        COMMENT ON COLUMN audit_events.metadata IS
        'Additional metadata about the event (PHI redacted)';
    END IF;
END $$;

-- 2. Add is_active column to sessions table (for session timeout checks)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'sessions' AND column_name = 'is_active'
    ) THEN
        ALTER TABLE sessions
        ADD COLUMN is_active BOOLEAN DEFAULT TRUE;

        COMMENT ON COLUMN sessions.is_active IS
        'Whether the session is currently active (for timeout checks)';
    END IF;
END $$;

-- 3. Also add to user_sessions for consistency
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'user_sessions' AND column_name = 'is_active'
    ) THEN
        ALTER TABLE user_sessions
        ADD COLUMN is_active BOOLEAN DEFAULT TRUE;

        COMMENT ON COLUMN user_sessions.is_active IS
        'Whether the session is currently active (for timeout checks)';
    END IF;
END $$;

-- 4. Add missing audit columns if they don't exist
DO $$
BEGIN
    -- Add event_category to data_access_logs if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_access_logs' AND column_name = 'event_category'
    ) THEN
        ALTER TABLE data_access_logs
        ADD COLUMN event_category VARCHAR(100);
    END IF;

    -- Add query_type to data_access_logs if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_access_logs' AND column_name = 'query_type'
    ) THEN
        ALTER TABLE data_access_logs
        ADD COLUMN query_type VARCHAR(100);
    END IF;

    -- Add model_name to data_access_logs if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_access_logs' AND column_name = 'model_name'
    ) THEN
        ALTER TABLE data_access_logs
        ADD COLUMN model_name VARCHAR(100);
    END IF;

    -- Add completion_tokens to data_access_logs if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_access_logs' AND column_name = 'completion_tokens'
    ) THEN
        ALTER TABLE data_access_logs
        ADD COLUMN completion_tokens INTEGER;
    END IF;

    -- Add prompt_tokens to data_access_logs if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_access_logs' AND column_name = 'prompt_tokens'
    ) THEN
        ALTER TABLE data_access_logs
        ADD COLUMN prompt_tokens INTEGER;
    END IF;

    -- Add total_tokens to data_access_logs if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_access_logs' AND column_name = 'total_tokens'
    ) THEN
        ALTER TABLE data_access_logs
        ADD COLUMN total_tokens INTEGER;
    END IF;
END $$;

-- 5. Update existing active sessions to have is_active = true
UPDATE user_sessions
SET is_active = TRUE
WHERE last_activity > NOW() - INTERVAL '24 hours';

UPDATE sessions
SET is_active = TRUE
WHERE started_at > NOW() - INTERVAL '24 hours' AND ended_at IS NULL;

-- 6. Create indexes on is_active for faster session timeout queries
CREATE INDEX IF NOT EXISTS idx_user_sessions_is_active
ON user_sessions(is_active, last_activity)
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_sessions_is_active
ON sessions(is_active, started_at)
WHERE is_active = TRUE;

COMMENT ON INDEX idx_user_sessions_is_active IS
'Index for fast session timeout queries on active user sessions';

COMMENT ON INDEX idx_sessions_is_active IS
'Index for fast session timeout queries on active auth sessions';
