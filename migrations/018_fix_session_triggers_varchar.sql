-- Migration 018: Fix trigger functions to handle VARCHAR session_id in session_analytics
-- Issue: Triggers update_session_analytics() and update_session_duration() compare
--        UUID (from sessions table) with VARCHAR (from session_analytics table)
--        causing "operator does not exist: character varying = uuid" errors

-- Step 1: Update update_session_analytics() trigger function
CREATE OR REPLACE FUNCTION update_session_analytics()
RETURNS TRIGGER AS $trigger$
DECLARE
    user_role_val VARCHAR(50);
BEGIN
    -- Try to get role from users table
    SELECT role INTO user_role_val
    FROM users
    WHERE user_id = NEW.user_id
    LIMIT 1;

    -- Insert into session_analytics with explicit UUID to VARCHAR cast
    INSERT INTO session_analytics (session_id, user_id)
    VALUES (NEW.session_id::TEXT, NEW.user_id)  -- Cast UUID to TEXT/VARCHAR
    ON CONFLICT (session_id) DO NOTHING;

    RETURN NEW;
END;
$trigger$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_session_analytics() IS
'Trigger function to create session_analytics entry on session INSERT - casts UUID session_id to VARCHAR';

-- Step 2: Update update_session_duration() trigger function
CREATE OR REPLACE FUNCTION update_session_duration()
RETURNS TRIGGER AS $trigger$
BEGIN
    IF NEW.ended_at IS NOT NULL AND OLD.ended_at IS NULL THEN
        -- Update session_analytics with explicit UUID to VARCHAR cast
        UPDATE session_analytics
        SET session_duration_minutes = EXTRACT(EPOCH FROM (NEW.ended_at - NEW.started_at)) / 60,
            last_updated = NOW()
        WHERE session_id = NEW.session_id::TEXT;  -- Cast UUID to TEXT/VARCHAR
    END IF;
    RETURN NEW;
END;
$trigger$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_session_duration() IS
'Trigger function to update session duration when session ends - casts UUID session_id to VARCHAR';
