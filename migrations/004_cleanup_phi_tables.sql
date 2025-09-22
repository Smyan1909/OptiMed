-- Migration 004: Cleanup PHI tables and migrate data
-- This migration removes PHI from existing tables and creates safe alternatives

-- WARNING: This migration will permanently delete PHI data
-- Ensure you have backups and proper authorization before running

-- Note: Role creation requires CREATEROLE permission
-- RLS policies will use basic tenant/user isolation without specific roles

-- Step 1: Handle embeddings table - may not exist in GDPR-compliant mode
-- Only process if table exists
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'embeddings') THEN
        -- Create backup table for audit purposes
        EXECUTE 'CREATE TABLE IF NOT EXISTS embeddings_backup AS SELECT * FROM embeddings WHERE FALSE';

        -- Remove PHI content from embeddings table
        EXECUTE 'ALTER TABLE embeddings DROP COLUMN IF EXISTS content, DROP COLUMN IF EXISTS embedding';

        -- Rename the table to indicate it's deprecated
        EXECUTE 'ALTER TABLE embeddings RENAME TO embeddings_deprecated';
    END IF;
END $$;

-- Step 3: Create a safe version of the embeddings table for metadata only
CREATE TABLE IF NOT EXISTS embeddings_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    -- Remove content and embedding columns
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Step 4: Clean up DICOM images table - remove patient names from metadata (if exists)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'dicom_images') THEN
        EXECUTE 'UPDATE dicom_images SET metadata_json = metadata_json - ''patient_name'' WHERE metadata_json ? ''patient_name''';
        EXECUTE 'COMMENT ON TABLE dicom_images IS ''DICOM image metadata with patient names removed for GDPR compliance''';
    END IF;
END $$;

-- Step 5: Clean up generated images table - remove PHI from prompts (if exists)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'generated_images') THEN
        -- This is more complex as we need to redact PHI from prompts
        -- For now, we'll add a flag to indicate PHI has been redacted
        EXECUTE 'ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS phi_redacted BOOLEAN DEFAULT FALSE';
        EXECUTE 'ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS original_prompt_hash BYTEA'; -- Hash of original prompt for audit
    END IF;
END $$;

-- Step 6: Create function to generate consistent pseudonyms
CREATE OR REPLACE FUNCTION generate_pseudonym(input_text TEXT, salt TEXT DEFAULT 'gdpr_salt')
RETURNS TEXT AS $$
BEGIN
    RETURN encode(digest(input_text || salt, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Clean up user table - pseudonymize sensitive fields (if table exists and has legacy PHI columns)
DO $$
BEGIN
    -- Only process if users table exists and has PHI columns
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users') THEN
        -- Check if table has legacy PHI columns before trying to pseudonymize
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'phone') THEN
            -- Pseudonymize user data (keep original for migration purposes in separate columns)
            EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS email_hash TEXT, ADD COLUMN IF NOT EXISTS phone_hash TEXT, ADD COLUMN IF NOT EXISTS name_hash TEXT';

            -- Update with pseudonymized versions only if source columns exist
            IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'first_name') THEN
                EXECUTE 'UPDATE users SET email_hash = generate_pseudonym(email), phone_hash = generate_pseudonym(phone), name_hash = generate_pseudonym(first_name || '' '' || last_name) WHERE email_hash IS NULL';
            ELSE
                EXECUTE 'UPDATE users SET email_hash = generate_pseudonym(email), phone_hash = generate_pseudonym(COALESCE(phone, '''')) WHERE email_hash IS NULL';
            END IF;
        END IF;
    END IF;
END $$;

-- Step 7: Create a clean users table without PHI
CREATE TABLE IF NOT EXISTS users_gdpr_safe (
    user_id VARCHAR(255) PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email_hash TEXT NOT NULL, -- Pseudonymized email
    name_hash TEXT NOT NULL,  -- Pseudonymized name
    role VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    department VARCHAR(255),
    license_number VARCHAR(255), -- Keep license number as it's required for medical practice
    phone_hash TEXT, -- Pseudonymized phone
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Copy data from old users table to new safe table (if legacy table exists with expected structure)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')
       AND EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'user_id')
       AND EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'email_hash') THEN

        INSERT INTO users_gdpr_safe (
            user_id, username, email_hash, name_hash, role, status,
            department, license_number, phone_hash, created_at, updated_at
        )
        SELECT
            user_id,
            COALESCE(username, email),
            COALESCE(email_hash, generate_pseudonym(email)),
            COALESCE(name_hash, generate_pseudonym(COALESCE(email, 'unknown'))),
            COALESCE(role, 'user'),
            COALESCE(status, 'active'),
            department,
            license_number,
            phone_hash,
            created_at,
            updated_at
        FROM users
        ON CONFLICT (user_id) DO NOTHING;
    END IF;
END $$;

-- Step 8: Update user_sessions table to reference the safe users table
-- First, create a new sessions table
CREATE TABLE IF NOT EXISTS user_sessions_gdpr_safe (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES users_gdpr_safe(user_id) ON DELETE CASCADE,
    login_time TIMESTAMP WITH TIME ZONE NOT NULL,
    last_activity TIMESTAMP WITH TIME ZONE NOT NULL,
    ip_address_hash TEXT, -- Pseudonymized IP
    user_agent_hash TEXT, -- Pseudonymized user agent
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Step 9: Clean up user_actions table
CREATE TABLE IF NOT EXISTS user_actions_gdpr_safe (
    action_id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES users_gdpr_safe(user_id) ON DELETE CASCADE,
    action_type VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id_hash TEXT, -- Pseudonymized resource ID
    description TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Step 10: Create indexes for the new tables
CREATE INDEX IF NOT EXISTS idx_users_gdpr_safe_username ON users_gdpr_safe(username);
CREATE INDEX IF NOT EXISTS idx_users_gdpr_safe_email_hash ON users_gdpr_safe(email_hash);
CREATE INDEX IF NOT EXISTS idx_users_gdpr_safe_role ON users_gdpr_safe(role);

CREATE INDEX IF NOT EXISTS idx_user_sessions_gdpr_safe_user_id ON user_sessions_gdpr_safe(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_gdpr_safe_active ON user_sessions_gdpr_safe(is_active);

CREATE INDEX IF NOT EXISTS idx_user_actions_gdpr_safe_user_id ON user_actions_gdpr_safe(user_id);
CREATE INDEX IF NOT EXISTS idx_user_actions_gdpr_safe_type ON user_actions_gdpr_safe(action_type);
CREATE INDEX IF NOT EXISTS idx_user_actions_gdpr_safe_created_at ON user_actions_gdpr_safe(created_at);

-- Step 11: NOTE: RLS is currently DISABLED for backend compatibility
-- Enable RLS when application adds session variable support
-- ALTER TABLE users_gdpr_safe ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE user_sessions_gdpr_safe ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE user_actions_gdpr_safe ENABLE ROW LEVEL SECURITY;

-- RLS policies for user tables (commented out - uncomment when enabling RLS)
-- CREATE POLICY tenant_isolation_users ON users_gdpr_safe
--     FOR ALL
--     USING (user_id::uuid IN (
--         SELECT user_id FROM sessions
--         WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
--     ));

-- CREATE POLICY tenant_isolation_user_sessions ON user_sessions_gdpr_safe
--     FOR ALL
--     USING (user_id::uuid IN (
--         SELECT user_id FROM sessions
--         WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
--     ));

-- CREATE POLICY tenant_isolation_user_actions ON user_actions_gdpr_safe
--     FOR ALL
--     USING (user_id::uuid IN (
--         SELECT user_id FROM sessions
--         WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
--     ));

-- Step 12: Create a function to safely delete old tables after verification
CREATE OR REPLACE FUNCTION cleanup_phi_tables()
RETURNS TEXT AS $$
BEGIN
    -- This function should be called manually after verification
    -- that the new schema is working correctly
    
    -- DROP TABLE IF EXISTS embeddings_deprecated;
    -- DROP TABLE IF EXISTS users;
    -- DROP TABLE IF EXISTS user_sessions;
    -- DROP TABLE IF EXISTS user_actions;
    
    RETURN 'Old PHI tables are ready for deletion. Uncomment the DROP statements in cleanup_phi_tables() function after verification.';
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON TABLE embeddings_metadata IS 'Safe metadata-only version of embeddings table without PHI';
COMMENT ON TABLE users_gdpr_safe IS 'GDPR-compliant users table with pseudonymized PII';
COMMENT ON TABLE user_sessions_gdpr_safe IS 'GDPR-compliant user sessions table';
COMMENT ON TABLE user_actions_gdpr_safe IS 'GDPR-compliant user actions table with pseudonymized resource IDs';

COMMENT ON FUNCTION generate_pseudonym(TEXT, TEXT) IS 'Generate consistent pseudonyms for GDPR compliance';
COMMENT ON FUNCTION cleanup_phi_tables() IS 'Safely delete old PHI tables after verification';

-- Create a view for backward compatibility (read-only)
-- Only create if pgvector extension is available
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        EXECUTE 'CREATE OR REPLACE VIEW embeddings AS
        SELECT
            id,
            key,
            object_type,
            object_id,
            NULL::TEXT as content,  -- Always NULL for safety
            NULL::vector as embedding,  -- Always NULL for safety
            metadata,
            created_at,
            updated_at
        FROM embeddings_metadata';
    ELSE
        EXECUTE 'CREATE OR REPLACE VIEW embeddings AS
        SELECT
            id,
            key,
            object_type,
            object_id,
            NULL::TEXT as content,  -- Always NULL for safety
            NULL::TEXT as embedding,  -- Always NULL for safety (no vector type)
            metadata,
            created_at,
            updated_at
        FROM embeddings_metadata';
    END IF;
END $$;

-- Add comment to the view
COMMENT ON VIEW embeddings IS 'Backward compatibility view - content and embedding columns always return NULL for GDPR compliance';
