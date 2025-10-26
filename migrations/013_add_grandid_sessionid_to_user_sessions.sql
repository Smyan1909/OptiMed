-- Migration 013: Add grandid_sessionid to user_sessions table
-- This field stores the GrandID session ID for SITHS-authenticated users
-- to enable proper logout from the GrandID API

-- Add grandid_sessionid column to user_sessions table
ALTER TABLE user_sessions
ADD COLUMN IF NOT EXISTS grandid_sessionid TEXT;

-- Add index for faster lookups by grandid_sessionid
CREATE INDEX IF NOT EXISTS idx_user_sessions_grandid_sessionid
ON user_sessions(grandid_sessionid);

-- Add comment explaining the column
COMMENT ON COLUMN user_sessions.grandid_sessionid IS
'GrandID session ID for SITHS-authenticated users. Used to call GrandID logout API when user logs out.';
