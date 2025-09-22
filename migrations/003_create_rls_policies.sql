-- Migration 003: Create Row Level Security policies
-- This migration enables RLS and creates policies for tenant isolation

-- Note: Role creation requires CREATEROLE permission
-- RLS policies will use basic tenant/user isolation without specific roles

-- NOTE: RLS is currently DISABLED for backend compatibility
-- Enable Row Level Security when application adds session variable support
-- ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE resource_codes ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE evidence_sets ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE model_registry ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE retrieval_config ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE temp_content ENABLE ROW LEVEL SECURITY;

-- NOTE: RLS policies are currently DISABLED for backend compatibility
-- Uncomment when enabling RLS

-- RLS utility function (can be created even without RLS enabled)
CREATE OR REPLACE FUNCTION is_subject_in_tenant(subject_hash BYTEA, tenant_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    -- In a real implementation, you'd have a mapping table or function
    -- that maps subject_hash to tenant_id. For now, we'll implement
    -- a basic check that ensures tenant isolation.
    RETURN EXISTS (
        SELECT 1 FROM sessions s
        WHERE s.subject_hash = is_subject_in_tenant.subject_hash
        AND s.tenant_id = is_subject_in_tenant.tenant_id
        LIMIT 1
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- RLS Policies (commented out - uncomment when enabling RLS)
-- CREATE POLICY tenant_isolation_sessions ON sessions
--     FOR ALL
--     USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- CREATE POLICY tenant_isolation_audit_events ON audit_events
--     FOR ALL
--     USING (session_id IN (
--         SELECT session_id FROM sessions
--         WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
--     ));

-- CREATE POLICY tenant_isolation_resources ON resources
--     FOR ALL
--     USING (is_subject_in_tenant(subject_hash, current_setting('app.current_tenant_id', true)::uuid));

-- CREATE POLICY tenant_isolation_resource_codes ON resource_codes
--     FOR ALL
--     USING (resource_fk IN (
--         SELECT id FROM resources r
--         WHERE is_subject_in_tenant(r.subject_hash, current_setting('app.current_tenant_id', true)::uuid)
--     ));

-- CREATE POLICY tenant_isolation_evidence_sets ON evidence_sets
--     FOR ALL
--     USING (session_id IN (
--         SELECT session_id FROM sessions
--         WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
--     ));

-- CREATE POLICY global_read_model_registry ON model_registry
--     FOR SELECT
--     USING (true);

-- CREATE POLICY tenant_isolation_retrieval_config ON retrieval_config
--     FOR ALL
--     USING (id IN (
--         SELECT DISTINCT r.id FROM retrieval_config r
--         JOIN sessions s ON s.model_config_hash = r.config_hash
--         WHERE s.tenant_id = current_setting('app.current_tenant_id', true)::uuid
--     ));

-- CREATE POLICY tenant_isolation_temp_content ON temp_content
--     FOR ALL
--     USING (session_id IN (
--         SELECT session_id FROM sessions
--         WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
--     ));

-- Note: Permission grants removed due to role creation restrictions
-- Application will handle access control at the connection level

-- Create indexes for RLS performance
CREATE INDEX IF NOT EXISTS ix_sessions_tenant_subject ON sessions(tenant_id, subject_hash);
CREATE INDEX IF NOT EXISTS ix_resources_subject_hash ON resources(subject_hash);

-- Create function to set tenant context
CREATE OR REPLACE FUNCTION set_tenant_context(tenant_uuid UUID)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_tenant_id', tenant_uuid::text, false);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create function to get current tenant
CREATE OR REPLACE FUNCTION get_current_tenant()
RETURNS UUID AS $$
BEGIN
    RETURN current_setting('app.current_tenant_id', true)::uuid;
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Add comments for documentation
COMMENT ON FUNCTION set_tenant_context(UUID) IS 'Set the current tenant context for RLS policies';
COMMENT ON FUNCTION get_current_tenant() IS 'Get the current tenant ID from session context';
COMMENT ON FUNCTION is_subject_in_tenant(BYTEA, UUID) IS 'Check if a subject hash belongs to a specific tenant';

-- PostgreSQL doesn't support AFTER SELECT triggers
-- Audit logging will be handled at the application level instead
-- This section is removed as it's not supported by PostgreSQL
