# SITHS NetID Enterprise Setup Guide

This guide explains how to set up and configure SITHS NetID Enterprise authentication for OptiMed using GrandID's API.

## Table of Contents

- [Prerequisites](#prerequisites)
- [GrandID API Setup](#grandid-api-setup)
- [Environment Configuration](#environment-configuration)
- [Database Setup](#database-setup)
- [HSA ID Whitelist Management](#hsa-id-whitelist-management)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before setting up SITHS authentication, you need:

1. **SITHS Card**: A valid SITHS card with an HSA ID
2. **Card Reader**: A USB card reader connected to your computer
3. **GrandID Account**: Access to GrandID's NetID Enterprise service
4. **API Credentials**: API key and Service key from GrandID

### Obtaining GrandID Credentials

1. Contact GrandID support: info@e-identitet.se or call +46 18 481 19 00
2. Request access to NetID Enterprise API
3. Obtain your:
   - API Key
   - Service Key
   - Test/Production base URLs

Documentation: https://docs.grandid.com/netID_enterprise

## GrandID API Setup

### Test Environment

For testing, use the GrandID test server:

```bash
GRANDID_BASE_URL=https://client.test.grandid.com
```

### Production Environment

For production, use the GrandID production server:

```bash
GRANDID_BASE_URL=https://client.grandid.com
```

**Important**: Update the API implementation in `src/optimed/adapters/siths_grandid/auth_provider.py` with the exact API endpoints and parameters from GrandID documentation.

## Environment Configuration

Add the following environment variables to your `.env` file:

```bash
# SITHS NetID Enterprise (GrandID) Configuration
GRANDID_API_KEY=your-grandid-api-key
GRANDID_SERVICE_KEY=your-grandid-service-key
GRANDID_BASE_URL=https://client.test.grandid.com  # or production URL
```

### Azure Deployment

For Azure Container Apps, set environment variables via Azure Portal or CLI:

```bash
az containerapp update \
  --name optimed-api-sweden \
  --resource-group optimed-sweden-rg \
  --set-env-vars \
    GRANDID_API_KEY=secretref:grandid-api-key \
    GRANDID_SERVICE_KEY=secretref:grandid-service-key \
    GRANDID_BASE_URL=https://client.grandid.com
```

Store sensitive keys in Azure Key Vault and reference them as secrets.

## Database Setup

### Run Migration

Apply the HSA ID migration to add the required database fields:

```bash
python scripts/run_migrations.py
```

This creates:
- `hsa_id` column in `users` table (UNIQUE)
- `siths_metadata` column for certificate information
- Index on `hsa_id` for fast lookups

### Verify Migration

```sql
\d users

-- Should show:
-- hsa_id          | character varying(255) |
-- siths_metadata  | jsonb                  | default '{}'::jsonb
```

## HSA ID Whitelist Management

SITHS authentication uses a **whitelist approach**: users can only login if their HSA ID has been pre-approved and added to the database by an administrator.

### Management Script

Use the `manage_hsa_ids.py` script to manage HSA IDs:

#### Add HSA ID to Existing User

```bash
python scripts/manage_hsa_ids.py add --username doctor1 --hsa-id SE123456789012
```

or

```bash
python scripts/manage_hsa_ids.py add --email doctor1@hospital.se --hsa-id SE123456789012
```

#### Create New User with HSA ID

```bash
python scripts/manage_hsa_ids.py create \
  --hsa-id SE9876543210 \
  --email new.doctor@hospital.se \
  --first-name "Anna" \
  --last-name "Andersson" \
  --role doctor \
  --department "Cardiology"
```

#### List All Users and HSA IDs

```bash
python scripts/manage_hsa_ids.py list
```

Output:

```
====================================================================================================
Username             HSA ID               Name                      Email
====================================================================================================
doctor1              SE123456789012       John Doe                  doctor1@hospital.se
doctor2              (not set)            Jane Smith                doctor2@hospital.se
====================================================================================================
Total users: 2
Users with HSA ID: 1
```

#### Remove HSA ID (Revoke Access)

```bash
python scripts/manage_hsa_ids.py remove --username doctor1
```

#### Bulk Import from CSV

Create a CSV file (`hsa_ids.csv`):

```csv
username,hsa_id,email,first_name,last_name,role,department
doctor1,SE123456789012,doctor1@hospital.se,John,Doe,doctor,Cardiology
doctor2,SE987654321098,doctor2@hospital.se,Jane,Smith,doctor,Neurology
```

Import:

```bash
python scripts/manage_hsa_ids.py import --csv hsa_ids.csv
```

## Authentication Flow

### User Experience

1. User navigates to `/login`
2. Clicks "SITHS NetID" tab
3. Clicks "Login with SITHS Card" button
4. System initiates authentication via GrandID API
5. User receives prompt to insert SITHS card and authenticate
6. Frontend polls authentication status every 2 seconds
7. Upon success:
   - System extracts HSA ID from SITHS certificate
   - Checks if HSA ID exists in database
   - If authorized: creates session and redirects to `/chat`
   - If not authorized: shows "Access denied" error

### Backend Flow

```python
# 1. Initiate authentication
POST /auth/siths-login
  → Returns orderRef, autoStartToken, qrStartToken

# 2. Poll authentication status
GET /auth/siths-status/{orderRef}
  → Returns status: "pending" | "complete" | "failed"

# 3. On complete:
  - Extract HSA ID from certificate
  - Lookup user: SELECT * FROM users WHERE hsa_id = ?
  - If found: Update user info, create session, return user + session_id
  - If not found: Return 403 "Access denied - HSA ID not authorized"
```

### HSA ID Extraction

The system extracts the following from the SITHS certificate:

- **HSA ID**: Unique identifier (e.g., "SE123456789012")
- **Given Name**: User's first name
- **Surname**: User's last name
- **Email**: User's email address
- **Organization**: Healthcare organization
- **Organizational Unit**: Department/unit
- **Certificate Serial**: Certificate serial number

This information is stored in the `siths_metadata` JSONB field.

## Testing

### Test with SITHS Card

1. **Add test user to whitelist**:
   ```bash
   python scripts/manage_hsa_ids.py add --username testuser --hsa-id SE000000000000
   ```

2. **Start backend**:
   ```bash
   python -m uvicorn optimed.apps.api_gateway.main:app --reload
   ```

3. **Start frontend**:
   ```bash
   cd src/optimed/apps/web
   npm run dev
   ```

4. **Navigate to login page**: http://localhost:3000/login

5. **Click "SITHS NetID" tab**

6. **Click "Login with SITHS Card"**

7. **Insert SITHS card and authenticate**

8. **Verify**:
   - Authentication succeeds
   - User info updated from certificate
   - Session created
   - Redirected to `/chat`

### Test Access Denial

1. **Remove HSA ID from database**:
   ```bash
   python scripts/manage_hsa_ids.py remove --username testuser
   ```

2. **Attempt SITHS login**

3. **Verify**:
   - Authentication with GrandID succeeds
   - System returns "Access denied" error
   - No session created

## Troubleshooting

### Issue: "SITHS authentication not configured"

**Cause**: Missing environment variables

**Solution**:
```bash
# Check environment variables are set
echo $GRANDID_API_KEY
echo $GRANDID_SERVICE_KEY
echo $GRANDID_BASE_URL

# If missing, add to .env file
```

### Issue: "Failed to initiate SITHS login"

**Cause**: Invalid API credentials or unreachable GrandID server

**Solution**:
1. Verify API key and service key are correct
2. Check network connectivity to GrandID server
3. Review GrandID API documentation for endpoint changes
4. Check backend logs for detailed error:
   ```bash
   docker logs -f optimed-api-sweden
   ```

### Issue: "No valid HSA ID found in SITHS certificate"

**Cause**: HSA ID field mapping incorrect in `auth_provider.py`

**Solution**:
1. Review GrandID API response structure
2. Update `_extract_user_info()` method in `auth_provider.py`
3. Check which field contains the HSA ID:
   - `hsaId`
   - `serialNumber`
   - `employeeNumber`
   - Or custom field

### Issue: "Access denied - HSA ID not authorized"

**Cause**: User's HSA ID not in database whitelist

**Solution**:
```bash
# Add HSA ID to whitelist
python scripts/manage_hsa_ids.py add --email user@hospital.se --hsa-id SE123456789012
```

### Issue: "Authentication stuck on pending"

**Cause**:
- User hasn't completed authentication
- Card reader not working
- GrandID session expired

**Solution**:
1. Ensure SITHS card is properly inserted
2. Check card reader is connected and drivers installed
3. Try canceling and starting authentication again
4. Check GrandID session timeout settings

## Security Considerations

### Whitelist-Based Access Control

- **Pre-authorization required**: Only users with pre-approved HSA IDs can login
- **Admin-controlled**: Only administrators can add/remove HSA IDs
- **Audit trail**: All login attempts logged in `user_actions` table

### GDPR Compliance

- **HSA ID storage**: Stored in database for access control
- **Certificate metadata**: Stored in `siths_metadata` for audit purposes
- **No PHI in logs**: HSA IDs sanitized in application logs
- **Right to erasure**: Remove user record to revoke all access

### Production Recommendations

1. **Use Azure Managed Identity** instead of API keys where possible
2. **Store secrets in Azure Key Vault**
3. **Enable Azure Monitor alerts** for failed authentication attempts
4. **Regular HSA ID audit**: Review whitelist quarterly
5. **Certificate expiry monitoring**: Track SITHS certificate expiration dates

## Additional Resources

- [GrandID Documentation](https://docs.grandid.com/netID_enterprise)
- [SITHS Information](https://www.inera.se/tjanster/siths/)
- [Azure Key Vault Setup](../operations/azure_ai_foundry_setup.md)
- [GDPR Compliance Architecture](../architecture/gdpr_compliant_architecture.md)

## Support

For issues related to:
- **GrandID API**: Contact info@e-identitet.se or +46 18 481 19 00
- **SITHS Cards**: Contact your healthcare organization's IT support
- **OptiMed SITHS Integration**: Review logs and raise issue in project repository
