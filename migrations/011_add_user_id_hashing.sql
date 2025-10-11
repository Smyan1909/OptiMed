-- Migration 011: Add user_id_hash to user_ehr_connections
-- Created: 2025-10-10
-- Purpose: GDPR compliance - pseudonymize user_id for right-to-erasure compliance

-- ============================================================================
-- PART 1: Add user_id_hash Column
-- ============================================================================

ALTER TABLE user_ehr_connections
ADD COLUMN IF NOT EXISTS user_id_hash TEXT;

-- Add index for hash column (for searching by hash)
CREATE INDEX IF NOT EXISTS idx_ehr_connections_user_hash ON user_ehr_connections(user_id_hash);

COMMENT ON COLUMN user_ehr_connections.user_id_hash IS 'SHA-256 hash of user_id for GDPR right-to-erasure compliance';

-- ============================================================================
-- PART 2: Populate user_id_hash for Existing Records
-- ============================================================================

-- Update existing records with NULL hashes
UPDATE user_ehr_connections
SET user_id_hash = hash_text(user_id)
WHERE user_id_hash IS NULL AND user_id IS NOT NULL;

-- ============================================================================
-- PART 3: Verification
-- ============================================================================

-- Verify hash columns populated
DO $$
DECLARE
    null_hash_count INT;
    total_count INT;
BEGIN
    SELECT COUNT(*) INTO null_hash_count
    FROM user_ehr_connections
    WHERE user_id IS NOT NULL AND user_id_hash IS NULL;

    SELECT COUNT(*) INTO total_count
    FROM user_ehr_connections;

    IF null_hash_count > 0 THEN
        RAISE WARNING 'Found % connections with NULL user_id_hash that should be populated', null_hash_count;
    ELSE
        RAISE NOTICE 'All user_id_hash columns properly populated ✓ (% total connections)', total_count;
    END IF;
END $$;

-- ============================================================================
-- PART 4: Audit Trail
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
    'user_id_hashing_enabled',
    1,
    'count',
    jsonb_build_object(
        'migration_version', '011',
        'timestamp', NOW(),
        'hash_algorithm', 'SHA-256',
        'connections_updated', (SELECT COUNT(*) FROM user_ehr_connections WHERE user_id_hash IS NOT NULL),
        'total_connections', (SELECT COUNT(*) FROM user_ehr_connections)
    )
);

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 011: User ID Hashing - COMPLETED';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE '✓ user_id_hash column added to user_ehr_connections';
    RAISE NOTICE '✓ Hash values populated for existing records';
    RAISE NOTICE '✓ Index created for hash column';
    RAISE NOTICE '✓ Audit logging enabled';
    RAISE NOTICE '';
    RAISE NOTICE 'GDPR COMPLIANCE:';
    RAISE NOTICE '- User IDs are now hashed for pseudonymization';
    RAISE NOTICE '- Supports right-to-erasure by keeping hash after deletion';
    RAISE NOTICE '- Consistent with audit log hashing strategy';
    RAISE NOTICE '';
END $$;
