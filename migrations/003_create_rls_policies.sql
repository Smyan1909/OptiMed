-- Migration 003: Create Row Level Security policies
-- This migration enables RLS and creates policies for tenant isolation

-- Enable Row Level Security on all tables
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE resource_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE temp_content ENABLE ROW LEVEL SECURITY;

-- Create RLS policies for tenant isolation

-- Sessions: Users can only access sessions within their tenant
CREATE POLICY tenant_isolation_sessions ON sessions
    FOR ALL TO authenticated_users
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Audit events: Users can only access audit events for sessions they can see
CREATE POLICY tenant_isolation_audit_events ON audit_events
    FOR ALL TO authenticated_users
    USING (session_id IN (
        SELECT session_id FROM sessions 
        WHERE tenant_id = current_setting('app.current_tenant_id')::uuid
    ));

-- Resources: Users can only access resources for patients in their tenant
-- This requires a function to check if a subject_hash belongs to the current tenant
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

CREATE POLICY tenant_isolation_resources ON resources
    FOR ALL TO authenticated_users
    USING (is_subject_in_tenant(subject_hash, current_setting('app.current_tenant_id')::uuid));

-- Resource codes: Inherit from resources
CREATE POLICY tenant_isolation_resource_codes ON resource_codes
    FOR ALL TO authenticated_users
    USING (resource_fk IN (
        SELECT id FROM resources r
        WHERE is_subject_in_tenant(r.subject_hash, current_setting('app.current_tenant_id')::uuid)
    ));

-- Evidence sets: Users can only access evidence for sessions they can see
CREATE POLICY tenant_isolation_evidence_sets ON evidence_sets
    FOR ALL TO authenticated_users
    USING (session_id IN (
        SELECT session_id FROM sessions 
        WHERE tenant_id = current_setting('app.current_tenant_id')::uuid
    ));

-- Model registry: Global read access for all authenticated users
CREATE POLICY global_read_model_registry ON model_registry
    FOR SELECT TO authenticated_users
    USING (true);

CREATE POLICY admin_write_model_registry ON model_registry
    FOR ALL TO admin_users
    USING (true);

-- Retrieval config: Users can only access configs they created or are shared
CREATE POLICY tenant_isolation_retrieval_config ON retrieval_config
    FOR ALL TO authenticated_users
    USING (id IN (
        SELECT DISTINCT r.id FROM retrieval_config r
        JOIN sessions s ON s.model_config_hash = r.config_hash
        WHERE s.tenant_id = current_setting('app.current_tenant_id')::uuid
    ));

-- Temp content: Users can only access their own session's temp content
CREATE POLICY tenant_isolation_temp_content ON temp_content
    FOR ALL TO authenticated_users
    USING (session_id IN (
        SELECT session_id FROM sessions 
        WHERE tenant_id = current_setting('app.current_tenant_id')::uuid
    ));

-- Create roles for the application
DO $$
BEGIN
    -- Create application roles if they don't exist
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated_users') THEN
        CREATE ROLE authenticated_users;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admin_users') THEN
        CREATE ROLE admin_users;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'system_service') THEN
        CREATE ROLE system_service;
    END IF;
END
$$;

-- Grant appropriate permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON sessions TO authenticated_users;
GRANT SELECT, INSERT ON audit_events TO authenticated_users;
GRANT SELECT, INSERT, UPDATE ON resources TO authenticated_users;
GRANT SELECT, INSERT, DELETE ON resource_codes TO authenticated_users;
GRANT SELECT, INSERT ON evidence_sets TO authenticated_users;
GRANT SELECT ON model_registry TO authenticated_users;
GRANT SELECT, INSERT, UPDATE ON retrieval_config TO authenticated_users;
GRANT SELECT, INSERT, UPDATE, DELETE ON temp_content TO authenticated_users;

-- Admin users get full access
GRANT ALL ON ALL TABLES IN SCHEMA public TO admin_users;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO admin_users;

-- System service gets full access for maintenance operations
GRANT ALL ON ALL TABLES IN SCHEMA public TO system_service;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO system_service;

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
    RETURN current_setting('app.current_tenant_id')::uuid;
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Add comments for documentation
COMMENT ON FUNCTION set_tenant_context(UUID) IS 'Set the current tenant context for RLS policies';
COMMENT ON FUNCTION get_current_tenant() IS 'Get the current tenant ID from session context';
COMMENT ON FUNCTION is_subject_in_tenant(BYTEA, UUID) IS 'Check if a subject hash belongs to a specific tenant';

-- Create audit trigger for sensitive operations
CREATE OR REPLACE FUNCTION audit_sensitive_operations()
RETURNS TRIGGER AS $$
BEGIN
    -- Log access to sensitive data
    IF TG_OP = 'SELECT' THEN
        INSERT INTO audit_events (session_id, action, resource_type, resource_id, outcome)
        VALUES (
            current_setting('app.current_session_id', true)::uuid,
            'ACCESS',
            TG_TABLE_NAME,
            COALESCE(NEW.id::text, OLD.id::text),
            'SUCCESS'
        );
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Apply audit trigger to sensitive tables
CREATE TRIGGER audit_resources_access
    AFTER SELECT ON resources
    FOR EACH ROW
    EXECUTE FUNCTION audit_sensitive_operations();

CREATE TRIGGER audit_sessions_access
    AFTER SELECT ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION audit_sensitive_operations();
