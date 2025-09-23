# Backend RLS Setup Guide

## Current Status
Row Level Security (RLS) policies are **DISABLED** in the database migrations to maintain compatibility with your existing backend.

## Migration Status
- ✅ **Tables Created**: All new audit and analytics tables are created
- ✅ **Indexes Added**: Performance indexes are in place
- ⏸️ **RLS Disabled**: RLS policies exist but are not enabled
- ✅ **Backend Compatible**: Current application will work without changes

## When to Enable RLS (Optional Future Enhancement)

To enable Row Level Security for enhanced data isolation:

### 1. Update Database Connection Initialization

Add session variable setup to `PGUserRepository._init_connection()`:

```python
async def _init_connection(self, conn: asyncpg.Connection):
    """Initialize database connection with required extensions and schemas."""
    # Set default session variables for RLS
    await conn.execute("SELECT set_config('app.current_tenant_id', $1, false)", 'default-tenant')
    await conn.execute("SELECT set_config('app.current_user_id', $1, false)", 'system-user')

    # Ensure tables exist
    await self._ensure_tables(conn)
```

### 2. Set Session Context Per Request

Update your API endpoints to set user context:

```python
async def set_user_context(conn: asyncpg.Connection, user_id: str, tenant_id: str = None):
    """Set user context for RLS policies."""
    await conn.execute("SELECT set_config('app.current_user_id', $1, false)", user_id)
    if tenant_id:
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, false)", tenant_id)
```

### 3. Enable RLS in Database

Run these commands to enable RLS:

```sql
-- Enable RLS on core tables
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_usage_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_access_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE encryption_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_events ENABLE ROW LEVEL SECURITY;
```

## Current Database Features Available

Without RLS enabled, you still get:

- ✅ Enhanced audit logging tables
- ✅ System usage metrics tracking
- ✅ Encryption audit trails
- ✅ GDPR compliance event tracking
- ✅ Data lineage tracking
- ✅ Performance metrics collection
- ✅ All existing functionality preserved

## Next Steps

1. **Test the migrations** - They should now run without errors
2. **Use new audit tables** - Start logging to the new tables via your existing user repository
3. **Consider RLS later** - Enable RLS when you want enhanced data isolation (optional)