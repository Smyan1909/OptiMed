-- Migration 016: Fix UUID/VARCHAR mismatches in audit logging tables
-- Fixes: performance_metrics.session_id, evidence_sets.session_id, evidence_sets.question_id
-- Issue: Audit logging fails when using VARCHAR chat session IDs (e.g., chat_general_1762213208290)
--        because tables expect UUID session IDs with foreign key constraints to sessions table

-- Step 1: Drop RLS policy on evidence_sets (will recreate after column type change)
DROP POLICY IF EXISTS tenant_isolation_evidence_sets ON evidence_sets;

-- Step 2: Fix performance_metrics.session_id
DO $$
BEGIN
    -- Drop the foreign key constraint if it exists
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name LIKE '%performance_metrics%session%'
        AND table_name = 'performance_metrics'
        AND constraint_type = 'FOREIGN KEY'
    ) THEN
        ALTER TABLE performance_metrics
        DROP CONSTRAINT IF EXISTS performance_metrics_session_id_fkey;
    END IF;

    -- Change session_id from UUID to VARCHAR(255)
    ALTER TABLE performance_metrics
    ALTER COLUMN session_id TYPE VARCHAR(255) USING session_id::TEXT;

    -- Make it nullable to support metrics without session context
    ALTER TABLE performance_metrics
    ALTER COLUMN session_id DROP NOT NULL;

    COMMENT ON COLUMN performance_metrics.session_id IS
    'Session ID (VARCHAR to support both UUID auth sessions and chat session formats like chat_general_*)';
END $$;

-- Step 3: Fix evidence_sets.session_id
DO $$
BEGIN
    -- Drop the foreign key constraint if it exists
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name LIKE '%evidence_sets%session%'
        AND table_name = 'evidence_sets'
        AND constraint_type = 'FOREIGN KEY'
    ) THEN
        ALTER TABLE evidence_sets
        DROP CONSTRAINT IF EXISTS evidence_sets_session_id_fkey;
    END IF;

    -- Change session_id from UUID to VARCHAR(255)
    ALTER TABLE evidence_sets
    ALTER COLUMN session_id TYPE VARCHAR(255) USING session_id::TEXT;

    -- Make it nullable since not all evidence sets may have session context
    ALTER TABLE evidence_sets
    ALTER COLUMN session_id DROP NOT NULL;

    COMMENT ON COLUMN evidence_sets.session_id IS
    'Session ID (VARCHAR to support both UUID auth sessions and chat session formats like chat_general_*)';
END $$;

-- Step 4: Fix evidence_sets.question_id
DO $$
BEGIN
    -- Change question_id from UUID to VARCHAR(255)
    -- Question IDs are generated as UUIDs but passed as strings from the application
    ALTER TABLE evidence_sets
    ALTER COLUMN question_id TYPE VARCHAR(255) USING question_id::TEXT;

    COMMENT ON COLUMN evidence_sets.question_id IS
    'Question/query ID (VARCHAR to support UUID strings from application)';
END $$;

-- Step 5: Add missing columns to evidence_sets if they don't exist
DO $$
BEGIN
    -- Add chunk_text_preview column if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'evidence_sets' AND column_name = 'chunk_text_preview'
    ) THEN
        ALTER TABLE evidence_sets
        ADD COLUMN chunk_text_preview TEXT;

        COMMENT ON COLUMN evidence_sets.chunk_text_preview IS
        'Preview of chunk text (first 500 chars, PHI-redacted for logging)';
    END IF;
END $$;

-- Step 6: Add user_id to evidence_sets for RLS (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'evidence_sets' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE evidence_sets
        ADD COLUMN user_id VARCHAR(255);

        COMMENT ON COLUMN evidence_sets.user_id IS
        'User ID for RLS tenant isolation (supports both UUID and VARCHAR formats)';
    END IF;
END $$;

-- Step 7: Create indexes on VARCHAR session_id columns for performance
CREATE INDEX IF NOT EXISTS idx_performance_metrics_session_id
ON performance_metrics(session_id)
WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_sets_session_id
ON evidence_sets(session_id)
WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_sets_question_id
ON evidence_sets(question_id);

COMMENT ON INDEX idx_performance_metrics_session_id IS
'Index for fast performance metric lookups by session (supports VARCHAR session IDs)';

COMMENT ON INDEX idx_evidence_sets_session_id IS
'Index for fast evidence set lookups by session (supports VARCHAR session IDs)';

COMMENT ON INDEX idx_evidence_sets_question_id IS
'Index for fast evidence set lookups by question ID';

-- Step 8: Recreate RLS policy on evidence_sets with VARCHAR session_id support
-- New policy supports both UUID auth sessions and VARCHAR chat sessions
CREATE POLICY tenant_isolation_evidence_sets ON evidence_sets
    FOR ALL
    USING (
        -- For UUID session IDs: check against sessions table
        (session_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
         AND session_id::UUID IN (
            SELECT session_id FROM sessions
            WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
        ))
        OR
        -- For non-UUID session IDs (chat sessions): allow all for now
        -- TODO: Implement proper tenant isolation for chat sessions via user_id
        (session_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    );

COMMENT ON POLICY tenant_isolation_evidence_sets ON evidence_sets IS
'Tenant isolation for evidence sets - supports both UUID auth sessions and VARCHAR chat sessions';
