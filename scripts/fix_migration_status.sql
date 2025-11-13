-- Fix migration status for already-applied migrations
-- Run this to mark failed migrations as successful when objects already exist

-- Mark migration 003 as successful
UPDATE schema_migrations
SET
    success = TRUE,
    applied_at = NOW(),
    error_message = NULL
WHERE migration_name = '003_create_rls_policies';

-- Mark migration 006 as successful
UPDATE schema_migrations
SET
    success = TRUE,
    applied_at = NOW(),
    error_message = NULL
WHERE migration_name = '006_create_note_templates_and_audit';

-- Verify the fix
SELECT
    migration_name,
    success,
    applied_at,
    error_message
FROM schema_migrations
WHERE migration_name IN ('003_create_rls_policies', '006_create_note_templates_and_audit')
ORDER BY migration_name;
