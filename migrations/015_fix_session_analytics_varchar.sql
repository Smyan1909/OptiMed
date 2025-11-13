-- Migration 015: Fix session_analytics to use VARCHAR instead of UUID
-- This allows tracking analytics for both UUID sessions (auth) and VARCHAR sessions (chat)

-- Step 1: Drop the foreign key constraint to sessions table
ALTER TABLE session_analytics
DROP CONSTRAINT IF EXISTS session_analytics_session_id_fkey;

-- Step 2: Backup existing data (if any)
CREATE TEMP TABLE session_analytics_backup AS
SELECT * FROM session_analytics;

-- Step 3: Drop and recreate session_analytics table with VARCHAR session_id
DROP TABLE IF EXISTS session_analytics CASCADE;

CREATE TABLE session_analytics (
    session_id VARCHAR(255) PRIMARY KEY,  -- Changed from UUID to VARCHAR
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

-- Step 4: Restore backed up data (convert UUID to VARCHAR)
INSERT INTO session_analytics
SELECT
    session_id::VARCHAR,  -- Convert UUID to VARCHAR
    user_id,
    total_requests,
    total_responses,
    patient_contexts_accessed,
    web_searches_performed,
    diagnostic_requests,
    chat_requests,
    image_uploads,
    journal_generations,
    error_count,
    session_duration_minutes,
    performance_metrics,
    data_sources_accessed,
    started_at,
    last_updated
FROM session_analytics_backup
ON CONFLICT (session_id) DO NOTHING;

-- Step 5: Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_session_analytics_user_id
ON session_analytics(user_id);

CREATE INDEX IF NOT EXISTS idx_session_analytics_started_at
ON session_analytics(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_analytics_last_updated
ON session_analytics(last_updated DESC);

-- Step 6: Add comments
COMMENT ON TABLE session_analytics IS
'Analytics tracking for all session types (UUID auth sessions and VARCHAR chat sessions)';

COMMENT ON COLUMN session_analytics.session_id IS
'Session identifier - supports both UUID format (auth sessions) and VARCHAR format (chat sessions like chat_general_xxx)';
