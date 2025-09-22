#!/usr/bin/env python3
"""
Environment Setup Script for OptiMed
Generates encryption keys and sets up environment variables.
"""
import os
import secrets
import base64
from pathlib import Path
from cryptography.fernet import Fernet

def generate_encryption_keys():
    """Generate secure encryption keys."""
    print("🔐 Generating encryption keys...")
    
    # Generate master encryption key
    master_key = Fernet.generate_key()
    print(f"ENCRYPTION_MASTER_KEY={master_key.decode()}")
    
    # Generate hash salt
    salt = base64.b64encode(secrets.token_bytes(32)).decode()
    print(f"HASH_SALT={salt}")
    
    return master_key.decode(), salt

def create_env_file():
    """Create .env file with secure defaults."""
    print("📝 Creating .env file...")
    
    master_key, salt = generate_encryption_keys()
    
    env_content = f"""# OptiMed Environment Configuration
# Generated automatically - keep this file secure!

# Database Configuration
PGVECTOR_DSN=postgresql://optimed_user:your_password@localhost:5432/optimed_db
DATABASE_URL=postgresql://optimed_user:your_password@localhost:5432/optimed_db

# Encryption Configuration (AUTO-GENERATED - DO NOT CHANGE)
ENCRYPTION_MASTER_KEY={master_key}
HASH_SALT={salt}

# Session Management
SESSION_TTL_MINUTES=60
CLEANUP_INTERVAL_MINUTES=5

# GDPR Compliance - End-to-End Encryption Enabled
PERSIST_PHI=false
EPHEMERAL_CACHE_ENABLED=false
ENCRYPT_API_RESPONSES=true

# CORS Configuration
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# Development Settings
DEBUG=true
LOG_LEVEL=INFO

# Security Settings
REQUIRE_SSL=false
ENABLE_RATE_LIMITING=true
MAX_REQUESTS_PER_MINUTE=100

# KMS Configuration (Optional - for production)
# KMS_ENDPOINT=https://your-kms-endpoint.com
# KMS_ACCESS_KEY=your-kms-access-key
# KMS_SECRET_KEY=your-kms-secret-key
"""
    
    env_path = Path(".env")
    if env_path.exists():
        backup_path = Path(".env.backup")
        print(f"⚠️ .env already exists, creating backup at {backup_path}")
        env_path.rename(backup_path)
    
    env_path.write_text(env_content)
    print("✅ Created .env file with secure encryption keys")
    print("🔒 IMPORTANT: Keep your .env file secure and never commit it to version control!")

def verify_environment():
    """Verify environment setup."""
    print("\n🔍 Verifying environment setup...")
    
    required_vars = [
        "PGVECTOR_DSN",
        "ENCRYPTION_MASTER_KEY", 
        "HASH_SALT"
    ]
    
    from dotenv import load_dotenv
    load_dotenv()
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        return False
    
    print("✅ All required environment variables are set")
    
    # Test encryption key
    try:
        from cryptography.fernet import Fernet
        key = os.getenv("ENCRYPTION_MASTER_KEY")
        Fernet(key.encode())
        print("✅ Encryption key is valid")
    except Exception as e:
        print(f"❌ Invalid encryption key: {e}")
        return False
    
    return True

def print_setup_instructions():
    """Print next steps for setup."""
    print("\n🎯 Next Steps:")
    print("=" * 50)
    print("1. Update your database credentials in .env file")
    print("2. Install PostgreSQL with pgvector extension")
    print("3. Run migrations: python scripts/run_migrations.py")
    print("4. Install dependencies: pip install -r requirements.txt")
    print("5. Start the application:")
    print("   - Backend: cd src/optimed/apps/api_gateway && python -m uvicorn main:app --reload")
    print("   - Frontend: cd src/optimed/apps/web && npm install && npm run dev")
    print("\n🔐 Security Features Enabled:")
    print("✅ End-to-end encryption for all API communications")
    print("✅ Session-specific encryption keys")
    print("✅ PHI redaction in all logs")
    print("✅ GDPR-compliant data storage")
    print("✅ Automatic session cleanup")

if __name__ == "__main__":
    print("🚀 OptiMed Environment Setup")
    print("=" * 50)
    
    try:
        create_env_file()
        
        if verify_environment():
            print_setup_instructions()
        else:
            print("❌ Environment setup incomplete")
            
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        import traceback
        traceback.print_exc()
