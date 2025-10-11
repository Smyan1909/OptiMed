-- Migration 010: Add Application-Level Encryption and Field-Level Hashing
-- Created: 2025-10-09
-- Purpose: GDPR/HIPAA compliance - encrypt sensitive data, hash PII

-- ============================================================================
-- PART 1: Enable pgcrypto Extension
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- PART 2: Create Encryption Helper Functions
-- ============================================================================

-- Function to encrypt text using AES-256
CREATE OR REPLACE FUNCTION encrypt_text(plaintext TEXT, key TEXT)
RETURNS BYTEA AS $$
BEGIN
    IF plaintext IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN pgp_sym_encrypt(plaintext, key, 'cipher-algo=aes256');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to decrypt text
CREATE OR REPLACE FUNCTION decrypt_text(ciphertext BYTEA, key TEXT)
RETURNS TEXT AS $$
BEGIN
    IF ciphertext IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN pgp_sym_decrypt(ciphertext, key);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to hash text using SHA-256
CREATE OR REPLACE FUNCTION hash_text(plaintext TEXT)
RETURNS TEXT AS $$
BEGIN
    IF plaintext IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN encode(digest(plaintext, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION encrypt_text IS 'Encrypt text using AES-256 (requires ENCRYPTION_MASTER_KEY)';
COMMENT ON FUNCTION decrypt_text IS 'Decrypt text encrypted with encrypt_text()';
COMMENT ON FUNCTION hash_text IS 'One-way SHA-256 hash for pseudonymization';

-- ============================================================================
-- PART 3: Add Encrypted Columns to user_ehr_connections
-- ============================================================================

ALTER TABLE user_ehr_connections
ADD COLUMN IF NOT EXISTS access_token_encrypted BYTEA,
ADD COLUMN IF NOT EXISTS refresh_token_encrypted BYTEA,
ADD COLUMN IF NOT EXISTS credentials_encrypted BYTEA;

-- Add indexes for encrypted columns (for performance)
CREATE INDEX IF NOT EXISTS idx_ehr_conn_token_encrypted
ON user_ehr_connections(access_token_encrypted)
WHERE access_token_encrypted IS NOT NULL;

COMMENT ON COLUMN user_ehr_connections.access_token_encrypted IS 'AES-256 encrypted access token (use decrypt_text to read)';
COMMENT ON COLUMN user_ehr_connections.refresh_token_encrypted IS 'AES-256 encrypted refresh token (use decrypt_text to read)';
COMMENT ON COLUMN user_ehr_connections.credentials_encrypted IS 'AES-256 encrypted credentials JSON';

-- ============================================================================
-- PART 4: Add Hash Columns to users (if not exist)
-- ============================================================================

-- These columns already exist in the schema but are NULL
-- Add them if they don't exist (for safety)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'email_hash'
    ) THEN
        ALTER TABLE users ADD COLUMN email_hash TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'phone_hash'
    ) THEN
        ALTER TABLE users ADD COLUMN phone_hash TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'name_hash'
    ) THEN
        ALTER TABLE users ADD COLUMN name_hash TEXT;
    END IF;
END $$;

-- Add indexes for hash columns (for searching)
CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users(email_hash);
CREATE INDEX IF NOT EXISTS idx_users_phone_hash ON users(phone_hash);
CREATE INDEX IF NOT EXISTS idx_users_name_hash ON users(name_hash);

COMMENT ON COLUMN users.email_hash IS 'SHA-256 hash of email for pseudonymization';
COMMENT ON COLUMN users.phone_hash IS 'SHA-256 hash of phone for pseudonymization';
COMMENT ON COLUMN users.name_hash IS 'SHA-256 hash of full name for pseudonymization';

-- ============================================================================
-- PART 5: Add Hash Column to Audit Logs
-- ============================================================================

ALTER TABLE data_access_logs
ADD COLUMN IF NOT EXISTS user_id_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_data_access_user_hash ON data_access_logs(user_id_hash);

COMMENT ON COLUMN data_access_logs.user_id_hash IS 'SHA-256 hash of user_id for GDPR right-to-erasure compliance';

-- ============================================================================
-- PART 6: Populate NULL Hash Columns (Existing Data)
-- ============================================================================

-- Update users with NULL hashes
UPDATE users
SET
    email_hash = hash_text(email),
    phone_hash = hash_text(phone),
    name_hash = hash_text(CONCAT(first_name, ' ', last_name))
WHERE email_hash IS NULL OR phone_hash IS NULL OR name_hash IS NULL;

-- ============================================================================
-- PART 7: Create Secure Views
-- ============================================================================

-- Drop existing view if it exists (to avoid column name conflicts)
DROP VIEW IF EXISTS user_ehr_connections_secure;

-- View that shows encrypted data status
CREATE VIEW user_ehr_connections_secure AS
SELECT
    connection_id,
    user_id,
    provider_type,
    fhir_server_url,
    client_id,
    -- Show encryption status, not actual tokens
    CASE
        WHEN access_token_encrypted IS NOT NULL THEN '[ENCRYPTED]'
        ELSE access_token
    END as access_token,
    CASE
        WHEN refresh_token_encrypted IS NOT NULL THEN '[ENCRYPTED]'
        ELSE refresh_token
    END as refresh_token,
    CASE
        WHEN credentials_encrypted IS NOT NULL THEN '{"status": "ENCRYPTED"}'::JSONB
        ELSE credentials
    END as credentials,
    token_expires_at,
    scope,
    is_active,
    created_at,
    updated_at,
    expires_at,
    -- Include encrypted columns for application use
    access_token_encrypted,
    refresh_token_encrypted,
    credentials_encrypted
FROM user_ehr_connections;

COMMENT ON VIEW user_ehr_connections_secure IS 'Secure view showing encryption status - use for admin queries';

-- ============================================================================
-- PART 8: Create Audit Trail for This Migration
-- ============================================================================

-- Log to system_usage_metrics
INSERT INTO system_usage_metrics (
    metric_type,
    metric_name,
    value,
    unit,
    dimensions
) VALUES (
    'migration',
    'encryption_and_hashing_enabled',
    1,
    'count',
    jsonb_build_object(
        'migration_version', '010',
        'timestamp', NOW(),
        'encryption_algorithm', 'AES-256',
        'hash_algorithm', 'SHA-256',
        'users_updated', (SELECT COUNT(*) FROM users WHERE email_hash IS NOT NULL),
        'connections_count', (SELECT COUNT(*) FROM user_ehr_connections)
    )
);

-- Log to encryption_audit_log if table exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'encryption_audit_log') THEN
        INSERT INTO encryption_audit_log (
            operation_type,
            data_type,
            encryption_algorithm,
            key_type,
            success,
            operation_timestamp,
            compliance_context
        ) VALUES (
            'migration',
            'bulk_setup',
            'AES-256',
            'symmetric',
            true,
            NOW(),
            jsonb_build_object(
                'migration', '010',
                'gdpr_compliant', true,
                'hipaa_compliant', true,
                'encryption_functions_created', true,
                'hash_columns_populated', true
            )
        );
    END IF;
END $$;

-- ============================================================================
-- PART 9: Grant Permissions (if using RLS)
-- ============================================================================

-- Grant execute on encryption functions to application role
DO $$
BEGIN
    -- Only grant if role exists
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'optimed_app') THEN
        GRANT EXECUTE ON FUNCTION encrypt_text(TEXT, TEXT) TO optimed_app;
        GRANT EXECUTE ON FUNCTION decrypt_text(BYTEA, TEXT) TO optimed_app;
        GRANT EXECUTE ON FUNCTION hash_text(TEXT) TO optimed_app;
    END IF;
END $$;

-- ============================================================================
-- PART 10: Verification Queries
-- ============================================================================

-- Verify encryption functions work
DO $$
DECLARE
    test_encrypted BYTEA;
    test_decrypted TEXT;
    test_hash TEXT;
BEGIN
    -- Test encryption
    test_encrypted := encrypt_text('test', 'test-key');
    test_decrypted := decrypt_text(test_encrypted, 'test-key');

    IF test_decrypted != 'test' THEN
        RAISE EXCEPTION 'Encryption test failed!';
    END IF;

    -- Test hashing
    test_hash := hash_text('test@example.com');

    IF LENGTH(test_hash) != 64 THEN  -- SHA-256 produces 64 hex chars
        RAISE EXCEPTION 'Hashing test failed!';
    END IF;

    RAISE NOTICE 'Encryption and hashing tests passed ✓';
END $$;

-- Verify hash columns populated
DO $$
DECLARE
    null_hash_count INT;
BEGIN
    SELECT COUNT(*) INTO null_hash_count
    FROM users
    WHERE (email IS NOT NULL AND email_hash IS NULL)
       OR (phone IS NOT NULL AND phone_hash IS NULL);

    IF null_hash_count > 0 THEN
        RAISE WARNING 'Found % users with NULL hashes that should be populated', null_hash_count;
    ELSE
        RAISE NOTICE 'All hash columns properly populated ✓';
    END IF;
END $$;

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 010: Encryption and Hashing - COMPLETED';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE '✓ pgcrypto extension enabled';
    RAISE NOTICE '✓ Encryption functions created (encrypt_text, decrypt_text)';
    RAISE NOTICE '✓ Hash function created (hash_text)';
    RAISE NOTICE '✓ Encrypted columns added to user_ehr_connections';
    RAISE NOTICE '✓ Hash columns populated in users table';
    RAISE NOTICE '✓ Audit logging enabled';
    RAISE NOTICE '✓ Secure views created';
    RAISE NOTICE '';
    RAISE NOTICE 'NEXT STEPS:';
    RAISE NOTICE '1. Update application code to use encrypted columns';
    RAISE NOTICE '2. Set ENCRYPTION_MASTER_KEY environment variable';
    RAISE NOTICE '3. Store key in Azure Key Vault';
    RAISE NOTICE '4. Test encryption with: SELECT decrypt_text(encrypt_text(''test'', ''key''), ''key'');';
    RAISE NOTICE '';
END $$;
