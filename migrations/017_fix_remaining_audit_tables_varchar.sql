-- Migration 017: Fix remaining audit tables to use VARCHAR session_id
-- Fixes: audit_events, data_access_logs, encryption_audit_log, compliance_events, data_lineage
-- Issue: Shutdown fails when finalizing UUID sessions because audit logging tries to insert
--        UUID session IDs into tables that still expect UUID type with foreign key constraints

-- Step 1: Drop RLS policies that depend on session_id
DROP POLICY IF EXISTS tenant_isolation_audit_events ON audit_events;
DROP POLICY IF EXISTS tenant_isolation_temp_content ON temp_content;

-- Step 2: Fix audit_events.session_id
DO $$
DECLARE
    constraint_name_var TEXT;
BEGIN
    -- Only alter if column is currently UUID type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'audit_events'
        AND column_name = 'session_id'
        AND data_type = 'uuid'
    ) THEN
        -- Drop all constraints on session_id column
        FOR constraint_name_var IN
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'audit_events'
            AND ccu.column_name = 'session_id'
        LOOP
            EXECUTE format('ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS %I', constraint_name_var);
        END LOOP;

        -- Change session_id from UUID to VARCHAR(255)
        ALTER TABLE audit_events
        ALTER COLUMN session_id TYPE VARCHAR(255) USING session_id::TEXT;

        -- Make it nullable
        ALTER TABLE audit_events
        ALTER COLUMN session_id DROP NOT NULL;

        COMMENT ON COLUMN audit_events.session_id IS
        'Session ID (VARCHAR to support both UUID auth sessions and chat session formats)';
    END IF;
END $$;

-- Step 3: Fix data_access_logs.session_id
DO $$
DECLARE
    constraint_name_var TEXT;
BEGIN
    -- Only alter if column is currently UUID type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_access_logs'
        AND column_name = 'session_id'
        AND data_type = 'uuid'
    ) THEN
        -- Drop all constraints on session_id column
        FOR constraint_name_var IN
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'data_access_logs'
            AND ccu.column_name = 'session_id'
        LOOP
            EXECUTE format('ALTER TABLE data_access_logs DROP CONSTRAINT IF EXISTS %I', constraint_name_var);
        END LOOP;

        -- Change session_id from UUID to VARCHAR(255)
        ALTER TABLE data_access_logs
        ALTER COLUMN session_id TYPE VARCHAR(255) USING session_id::TEXT;

        -- Make it nullable
        ALTER TABLE data_access_logs
        ALTER COLUMN session_id DROP NOT NULL;

        COMMENT ON COLUMN data_access_logs.session_id IS
        'Session ID (VARCHAR to support both UUID auth sessions and chat session formats)';
    END IF;
END $$;

-- Step 4: Fix encryption_audit_log.session_id
DO $$
DECLARE
    constraint_name_var TEXT;
BEGIN
    -- Only alter if column is currently UUID type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'encryption_audit_log'
        AND column_name = 'session_id'
        AND data_type = 'uuid'
    ) THEN
        -- Drop all constraints on session_id column
        FOR constraint_name_var IN
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'encryption_audit_log'
            AND ccu.column_name = 'session_id'
        LOOP
            EXECUTE format('ALTER TABLE encryption_audit_log DROP CONSTRAINT IF EXISTS %I', constraint_name_var);
        END LOOP;

        -- Change session_id from UUID to VARCHAR(255)
        ALTER TABLE encryption_audit_log
        ALTER COLUMN session_id TYPE VARCHAR(255) USING session_id::TEXT;

        -- Make it nullable
        ALTER TABLE encryption_audit_log
        ALTER COLUMN session_id DROP NOT NULL;

        COMMENT ON COLUMN encryption_audit_log.session_id IS
        'Session ID (VARCHAR to support both UUID auth sessions and chat session formats)';
    END IF;
END $$;

-- Step 5: Fix compliance_events.session_id
DO $$
DECLARE
    constraint_name_var TEXT;
BEGIN
    -- Only alter if column is currently UUID type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'compliance_events'
        AND column_name = 'session_id'
        AND data_type = 'uuid'
    ) THEN
        -- Drop all constraints on session_id column
        FOR constraint_name_var IN
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'compliance_events'
            AND ccu.column_name = 'session_id'
        LOOP
            EXECUTE format('ALTER TABLE compliance_events DROP CONSTRAINT IF EXISTS %I', constraint_name_var);
        END LOOP;

        -- Change session_id from UUID to VARCHAR(255)
        ALTER TABLE compliance_events
        ALTER COLUMN session_id TYPE VARCHAR(255) USING session_id::TEXT;

        -- Make it nullable
        ALTER TABLE compliance_events
        ALTER COLUMN session_id DROP NOT NULL;

        COMMENT ON COLUMN compliance_events.session_id IS
        'Session ID (VARCHAR to support both UUID auth sessions and chat session formats)';
    END IF;
END $$;

-- Step 6: Fix data_lineage.session_id
DO $$
DECLARE
    constraint_name_var TEXT;
BEGIN
    -- Only alter if column is currently UUID type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_lineage'
        AND column_name = 'session_id'
        AND data_type = 'uuid'
    ) THEN
        -- Drop all constraints on session_id column
        FOR constraint_name_var IN
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'data_lineage'
            AND ccu.column_name = 'session_id'
        LOOP
            EXECUTE format('ALTER TABLE data_lineage DROP CONSTRAINT IF EXISTS %I', constraint_name_var);
        END LOOP;

        -- Change session_id from UUID to VARCHAR(255)
        ALTER TABLE data_lineage
        ALTER COLUMN session_id TYPE VARCHAR(255) USING session_id::TEXT;

        -- Make it nullable
        ALTER TABLE data_lineage
        ALTER COLUMN session_id DROP NOT NULL;

        COMMENT ON COLUMN data_lineage.session_id IS
        'Session ID (VARCHAR to support both UUID auth sessions and chat session formats)';
    END IF;
END $$;

-- Step 7: Fix temp_content.session_id (if it exists)
DO $$
DECLARE
    constraint_name_var TEXT;
BEGIN
    -- Only alter if table exists and column is currently UUID type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'temp_content'
        AND column_name = 'session_id'
        AND data_type = 'uuid'
    ) THEN
        -- Drop all constraints on session_id column
        FOR constraint_name_var IN
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'temp_content'
            AND ccu.column_name = 'session_id'
        LOOP
            EXECUTE format('ALTER TABLE temp_content DROP CONSTRAINT IF EXISTS %I', constraint_name_var);
        END LOOP;

        -- Change session_id from UUID to VARCHAR(255)
        ALTER TABLE temp_content
        ALTER COLUMN session_id TYPE VARCHAR(255) USING session_id::TEXT;

        -- Make it nullable
        ALTER TABLE temp_content
        ALTER COLUMN session_id DROP NOT NULL;

        COMMENT ON COLUMN temp_content.session_id IS
        'Session ID (VARCHAR to support both UUID auth sessions and chat session formats)';
    END IF;
END $$;

-- Step 8: Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_audit_events_session_id
ON audit_events(session_id)
WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_data_access_logs_session_id
ON data_access_logs(session_id)
WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_encryption_audit_log_session_id
ON encryption_audit_log(session_id)
WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_compliance_events_session_id
ON compliance_events(session_id)
WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_data_lineage_session_id
ON data_lineage(session_id)
WHERE session_id IS NOT NULL;

-- Step 9: Recreate RLS policies with VARCHAR session_id support
CREATE POLICY tenant_isolation_audit_events ON audit_events
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
        (session_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    );

CREATE POLICY tenant_isolation_temp_content ON temp_content
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
        (session_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    );

COMMENT ON POLICY tenant_isolation_audit_events ON audit_events IS
'Tenant isolation for audit events - supports both UUID auth sessions and VARCHAR chat sessions';

COMMENT ON POLICY tenant_isolation_temp_content ON temp_content IS
'Tenant isolation for temp content - supports both UUID auth sessions and VARCHAR chat sessions';
