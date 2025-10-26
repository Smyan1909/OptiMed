-- Migration 006: Add HSA ID and SITHS metadata to users table
-- This migration adds support for SITHS NetID Enterprise authentication
-- HSA ID is used as a whitelist for authorized users

-- Add hsa_id column for SITHS authentication
-- HSA ID format: typically "SE" + 12 digits (e.g., "SE123456789012")
ALTER TABLE users
ADD COLUMN IF NOT EXISTS hsa_id VARCHAR(255) UNIQUE;

-- Add SITHS metadata column for additional certificate information
-- Stores: organization, organizational unit, certificate serial, etc.
ALTER TABLE users
ADD COLUMN IF NOT EXISTS siths_metadata JSONB DEFAULT '{}';

-- Add index on hsa_id for fast lookups during authentication
CREATE INDEX IF NOT EXISTS idx_users_hsa_id ON users(hsa_id);

-- Add comments for documentation
COMMENT ON COLUMN users.hsa_id IS 'HSA ID from SITHS certificate - used for authentication whitelist';
COMMENT ON COLUMN users.siths_metadata IS 'Additional SITHS certificate metadata (organization, certificate info, etc.)';

-- Note: Existing users will have NULL hsa_id
-- Use scripts/manage_hsa_ids.py to populate HSA IDs for authorized users
