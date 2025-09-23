---
title: "GDPR Operational Guide"
version: "2.0.0"
last_updated: "2025-01-27"
owner: "OptiMed AI"
audiences: ["Operations", "DevOps", "Compliance", "Support"]
---

## Executive Summary

This operational guide provides step-by-step procedures for managing the GDPR-compliant OptiMed AI system, including deployment, monitoring, maintenance, and incident response.

## System Overview

The GDPR-compliant system consists of:
- **Frontend**: Next.js application with PHI-free UI
- **Backend**: FastAPI services with RAM-only embeddings
- **Database**: PostgreSQL with RLS and metadata-only storage
- **Cache**: Ephemeral encrypted cache with crypto-shredding
- **Monitoring**: Comprehensive audit and compliance monitoring

## Deployment Procedures

### Prerequisites

#### System Requirements
- **CPU**: 8+ cores for embedding processing
- **RAM**: 16GB+ for RAM-only embeddings
- **Storage**: 100GB+ for metadata and audit logs
- **Network**: High-bandwidth connection to EHR systems

#### Software Requirements
- **PostgreSQL**: 14+ with pgvector extension
- **Python**: 3.11+ with required packages
- **Node.js**: 18+ for frontend
- **Docker**: 24+ for containerization
- **Kubernetes**: 1.28+ for orchestration

#### Security Requirements
- **TLS**: All communications encrypted
- **KMS**: Key management system access
- **RBAC**: Role-based access control
- **Network**: VPC with private subnets

### Initial Deployment

#### 1. Database Setup
```bash
# Create database
createdb optimed_gdpr

# Run migrations
psql optimed_gdpr < migrations/002_create_gdpr_safe_schema.sql
psql optimed_gdpr < migrations/003_create_rls_policies.sql
psql optimed_gdpr < migrations/004_cleanup_phi_tables.sql

# Verify schema
psql optimed_gdpr -c "\dt"
psql optimed_gdpr -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public';"
```

#### 2. Environment Configuration
```bash
# Create environment file
cat > .env.gdpr << EOF
# GDPR Compliance
PERSIST_PHI=false
EPHEMERAL_CACHE_ENABLED=true
EPHEMERAL_CACHE_TTL_HOURS=24
SESSION_TTL_MINUTES=480

# Database
DATABASE_URL=postgresql://user:pass@localhost/optimed_gdpr
PGVECTOR_DSN=postgresql://user:pass@localhost/optimed_gdpr

# Security
KMS_KEK_ID=production_kek_2025
KMS_KEK_SECRET=your_secure_kek_secret
RLS_ENABLED=true

# Memory Management
MAX_MEMORY_MB=2048
EMBEDDING_DIM=1024
SIMILARITY_METRIC=cosine

# Audit
AUDIT_RETENTION_DAYS=2555
AUDIT_LOG_LEVEL=INFO

# Feature Flags
ENABLE_CRYPTO_SHREDDING=true
ENABLE_MEMORY_ZEROIZATION=true
ENABLE_PHI_DETECTION=true
EOF
```

#### 3. Application Deployment
```bash
# Build and deploy backend
docker build -f Dockerfile.backend -t optimed-backend:gdpr .
docker run -d --name optimed-backend \
  --env-file .env.gdpr \
  -p 8000:8000 \
  optimed-backend:gdpr

# Build and deploy frontend
cd src/optimed/apps/web
npm run build
docker build -t optimed-frontend:gdpr .
docker run -d --name optimed-frontend \
  -p 3000:3000 \
  optimed-frontend:gdpr
```

#### 4. Verification
```bash
# Check backend health
curl http://localhost:8000/health

# Check frontend
curl http://localhost:3000

# Verify no PHI in logs
docker logs optimed-backend | grep -i "phi\|patient\|john\|doe" || echo "No PHI detected"

# Check database for PHI
psql optimed_gdpr -c "
SELECT COUNT(*) FROM embeddings WHERE content IS NOT NULL;
SELECT COUNT(*) FROM users WHERE email LIKE '%@%';
"
```

### Rolling Deployment

#### Zero-Downtime Deployment
```bash
#!/bin/bash
# rolling_deploy.sh

set -e

OLD_BACKEND="optimed-backend"
NEW_BACKEND="optimed-backend-new"
HEALTH_CHECK_URL="http://localhost:8000/health"

# Build new image
docker build -f Dockerfile.backend -t $NEW_BACKEND:latest .

# Start new backend
docker run -d --name $NEW_BACKEND \
  --env-file .env.gdpr \
  -p 8001:8000 \
  $NEW_BACKEND:latest

# Wait for health check
echo "Waiting for new backend to be healthy..."
for i in {1..30}; do
  if curl -f $HEALTH_CHECK_URL >/dev/null 2>&1; then
    echo "New backend is healthy"
    break
  fi
  sleep 2
done

# Update load balancer to point to new backend
# (Implementation depends on your load balancer)

# Stop old backend
docker stop $OLD_BACKEND
docker rm $OLD_BACKEND

# Rename new backend
docker rename $NEW_BACKEND $OLD_BACKEND

echo "Rolling deployment completed"
```

## Monitoring and Alerting

### Health Checks

#### Application Health
```python
# health_check.py
import requests
import sys

def check_backend_health():
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            health_data = response.json()
            return health_data.get("status") == "healthy"
    except Exception as e:
        print(f"Backend health check failed: {e}")
    return False

def check_database_health():
    try:
        # Check database connectivity and basic queries
        # Implementation depends on your database setup
        pass
    except Exception as e:
        print(f"Database health check failed: {e}")
    return False

def main():
    backend_healthy = check_backend_health()
    database_healthy = check_database_health()
    
    if backend_healthy and database_healthy:
        print("All systems healthy")
        sys.exit(0)
    else:
        print("Health check failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

#### Memory Monitoring
```bash
#!/bin/bash
# memory_monitor.sh

MEMORY_THRESHOLD=80  # Percentage
LOG_FILE="/var/log/optimed/memory_monitor.log"

check_memory_usage() {
    # Get memory usage from application metrics
    MEMORY_USAGE=$(curl -s http://localhost:8000/metrics/memory | jq '.usage_percentage')
    
    if [ "$MEMORY_USAGE" -gt "$MEMORY_THRESHOLD" ]; then
        echo "$(date): Memory usage ${MEMORY_USAGE}% exceeds threshold ${MEMORY_THRESHOLD}%" >> $LOG_FILE
        
        # Trigger memory cleanup
        curl -X POST http://localhost:8000/admin/cleanup-memory
        
        # Alert operations team
        echo "Memory usage critical: ${MEMORY_USAGE}%" | mail -s "Optimed Memory Alert" ops@optimed.ai
    fi
}

check_memory_usage
```

### Audit Monitoring

#### Audit Log Analysis
```python
# audit_monitor.py
import asyncio
import asyncpg
from datetime import datetime, timedelta

async def analyze_audit_logs():
    dsn = "postgresql://user:pass@localhost/optimed_gdpr"
    
    async with asyncpg.create_pool(dsn) as pool:
        async with pool.acquire() as conn:
            # Check for unusual access patterns
            unusual_access = await conn.fetch("""
                SELECT session_id, COUNT(*) as access_count
                FROM audit_events 
                WHERE occurred_at > NOW() - INTERVAL '1 hour'
                GROUP BY session_id
                HAVING COUNT(*) > 100
            """)
            
            if unusual_access:
                print(f"Unusual access detected: {len(unusual_access)} sessions")
                for session in unusual_access:
                    print(f"Session {session['session_id']}: {session['access_count']} accesses")
            
            # Check for failed operations
            failed_ops = await conn.fetch("""
                SELECT action, COUNT(*) as failure_count
                FROM audit_events 
                WHERE outcome LIKE '%FAIL%' 
                AND occurred_at > NOW() - INTERVAL '1 hour'
                GROUP BY action
            """)
            
            if failed_ops:
                print("Failed operations detected:")
                for failure in failed_ops:
                    print(f"{failure['action']}: {failure['failure_count']} failures")

if __name__ == "__main__":
    asyncio.run(analyze_audit_logs())
```

### Compliance Monitoring

#### PHI Detection
```python
# phi_detector.py
import re
import asyncio
import asyncpg

PHI_PATTERNS = [
    r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # Names
    r'\b\d{3}-\d{2}-\d{4}\b',        # SSN
    r'\b\d{3}\.\d{3}\.\d{4}\b',      # Phone
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
    r'\b(?:diabetes|hypertension|cancer|depression)\b',       # Medical conditions
]

async def scan_for_phi():
    dsn = "postgresql://user:pass@localhost/optimed_gdpr"
    
    async with asyncpg.create_pool(dsn) as pool:
        async with pool.acquire() as conn:
            # Check all text columns for PHI
            tables_to_check = [
                ("embeddings_metadata", "metadata"),
                ("audit_events", "outcome"),
                ("resources", "etag"),
            ]
            
            for table, column in tables_to_check:
                rows = await conn.fetch(f"SELECT {column} FROM {table}")
                
                for row in rows:
                    text_value = str(row[column])
                    
                    for pattern in PHI_PATTERNS:
                        if re.search(pattern, text_value, re.IGNORECASE):
                            print(f"Potential PHI detected in {table}.{column}: {text_value[:50]}...")
                            # Log and alert
                            break

if __name__ == "__main__":
    asyncio.run(scan_for_phi())
```

## Maintenance Procedures

### Daily Tasks

#### Memory Cleanup
```bash
#!/bin/bash
# daily_cleanup.sh

# Clean up expired cache entries
curl -X POST http://localhost:8000/admin/cleanup-expired-cache

# Clean up expired sessions
curl -X POST http://localhost:8000/admin/cleanup-expired-sessions

# Check memory usage
MEMORY_USAGE=$(curl -s http://localhost:8000/metrics/memory | jq '.usage_percentage')
echo "Memory usage: ${MEMORY_USAGE}%"

# Clean up old audit logs if needed
psql optimed_gdpr -c "
DELETE FROM audit_events 
WHERE occurred_at < NOW() - INTERVAL '7 years';
"
```

#### Health Check Report
```bash
#!/bin/bash
# daily_health_report.sh

REPORT_FILE="/var/log/optimed/daily_health_$(date +%Y%m%d).txt"

{
    echo "=== Daily Health Report $(date) ==="
    echo
    
    echo "=== Application Status ==="
    curl -s http://localhost:8000/health | jq '.'
    echo
    
    echo "=== Memory Usage ==="
    curl -s http://localhost:8000/metrics/memory | jq '.'
    echo
    
    echo "=== Database Stats ==="
    psql optimed_gdpr -c "
    SELECT 
        schemaname,
        tablename,
        n_tup_ins as inserts,
        n_tup_upd as updates,
        n_tup_del as deletes
    FROM pg_stat_user_tables 
    ORDER BY schemaname, tablename;
    "
    echo
    
    echo "=== Audit Events (Last 24h) ==="
    psql optimed_gdpr -c "
    SELECT 
        action,
        COUNT(*) as count,
        COUNT(*) FILTER (WHERE outcome LIKE '%FAIL%') as failures
    FROM audit_events 
    WHERE occurred_at > NOW() - INTERVAL '24 hours'
    GROUP BY action
    ORDER BY count DESC;
    "
    
} > $REPORT_FILE

# Send report to operations team
mail -s "Daily Health Report" ops@optimed.ai < $REPORT_FILE
```

### Weekly Tasks

#### Security Audit
```bash
#!/bin/bash
# weekly_security_audit.sh

# Check for PHI in database
python scripts/phi_detector.py

# Verify RLS policies are active
psql optimed_gdpr -c "
SELECT schemaname, tablename, rowsecurity 
FROM pg_tables 
WHERE schemaname = 'public';
"

# Check for unusual access patterns
python scripts/audit_monitor.py

# Verify crypto-shredding is working
curl -X POST http://localhost:8000/admin/test-crypto-shredding

# Check key rotation status
curl -s http://localhost:8000/admin/key-status | jq '.'
```

#### Performance Analysis
```bash
#!/bin/bash
# weekly_performance_analysis.sh

# Database performance
psql optimed_gdpr -c "
SELECT 
    query,
    calls,
    total_time,
    mean_time,
    rows
FROM pg_stat_statements 
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY total_time DESC 
LIMIT 10;
"

# Memory usage trends
curl -s http://localhost:8000/metrics/memory/history | jq '.'

# Cache hit rates
curl -s http://localhost:8000/metrics/cache | jq '.'
```

### Monthly Tasks

#### Compliance Review
```bash
#!/bin/bash
# monthly_compliance_review.sh

# Generate compliance report
python scripts/generate_compliance_report.py

# Review audit logs for anomalies
python scripts/audit_analysis.py --period monthly

# Test data subject rights
python scripts/test_data_subject_rights.py

# Verify backup integrity
python scripts/verify_backup_integrity.py
```

## Incident Response

### PHI Breach Response

#### Immediate Response (0-1 hours)
1. **Assess the breach**
   ```bash
   # Check logs for potential PHI exposure
   grep -r "PHI\|patient\|john\|doe" /var/log/optimed/
   
   # Check database for unauthorized access
   psql optimed_gdpr -c "
   SELECT * FROM audit_events 
   WHERE outcome LIKE '%UNAUTHORIZED%' 
   AND occurred_at > NOW() - INTERVAL '1 hour';
   "
   ```

2. **Contain the breach**
   ```bash
   # Crypto-shred all active sessions
   curl -X POST http://localhost:8000/admin/crypto-shred-all-sessions
   
   # Disable affected services
   docker stop optimed-backend
   
   # Isolate database
   # (Implementation depends on your infrastructure)
   ```

3. **Document the incident**
   ```bash
   # Create incident report
   cat > /var/log/incidents/incident_$(date +%Y%m%d_%H%M%S).txt << EOF
   Incident: Potential PHI Breach
   Time: $(date)
   Severity: HIGH
   Status: INVESTIGATING
   
   Actions Taken:
   - Crypto-shredded all active sessions
   - Stopped affected services
   - Initiated investigation
   
   Next Steps:
   - Complete forensic analysis
   - Notify stakeholders
   - Implement additional safeguards
   EOF
   ```

#### Investigation (1-24 hours)
1. **Forensic analysis**
   ```bash
   # Export all audit logs
   psql optimed_gdpr -c "
   COPY (
     SELECT * FROM audit_events 
     WHERE occurred_at > NOW() - INTERVAL '24 hours'
   ) TO '/tmp/audit_export_$(date +%Y%m%d).csv' WITH CSV HEADER;
   "
   
   # Check system logs
   journalctl -u optimed-backend --since "24 hours ago" > /tmp/system_logs_$(date +%Y%m%d).txt
   
   # Analyze network traffic
   # (Implementation depends on your monitoring setup)
   ```

2. **Impact assessment**
   ```bash
   # Count potentially affected records
   psql optimed_gdpr -c "
   SELECT COUNT(*) as potentially_affected_sessions
   FROM sessions 
   WHERE started_at > NOW() - INTERVAL '24 hours';
   "
   
   # Check for data exfiltration
   # (Implementation depends on your monitoring setup)
   ```

#### Recovery (24-72 hours)
1. **System restoration**
   ```bash
   # Restore from clean backup if necessary
   # (Implementation depends on your backup strategy)
   
   # Restart services with additional monitoring
   docker start optimed-backend
   
   # Verify system integrity
   curl http://localhost:8000/health
   ```

2. **Enhanced monitoring**
   ```bash
   # Enable additional audit logging
   curl -X POST http://localhost:8000/admin/enable-enhanced-auditing
   
   # Increase PHI detection sensitivity
   curl -X POST http://localhost:8000/admin/increase-phi-detection
   ```

### System Failure Response

#### Database Failure
```bash
#!/bin/bash
# database_failure_response.sh

# Check database status
pg_isready -h localhost -p 5432

if [ $? -ne 0 ]; then
    echo "Database is down, initiating recovery..."
    
    # Start database service
    systemctl start postgresql
    
    # Wait for database to be ready
    for i in {1..30}; do
        if pg_isready -h localhost -p 5432; then
            echo "Database is ready"
            break
        fi
        sleep 2
    done
    
    # Verify schema integrity
    psql optimed_gdpr -c "\dt"
    
    # Restart application services
    docker restart optimed-backend
fi
```

#### Memory Exhaustion
```bash
#!/bin/bash
# memory_exhaustion_response.sh

# Check memory usage
MEMORY_USAGE=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')

if [ "$MEMORY_USAGE" -gt 90 ]; then
    echo "Memory usage critical: ${MEMORY_USAGE}%"
    
    # Emergency memory cleanup
    curl -X POST http://localhost:8000/admin/emergency-memory-cleanup
    
    # Clear system caches
    echo 3 > /proc/sys/vm/drop_caches
    
    # Restart application if necessary
    if [ "$MEMORY_USAGE" -gt 95 ]; then
        docker restart optimed-backend
    fi
fi
```

## Backup and Recovery

### Backup Procedures

#### Database Backup
```bash
#!/bin/bash
# backup_database.sh

BACKUP_DIR="/var/backups/optimed"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/optimed_gdpr_$DATE.sql"

# Create backup directory
mkdir -p $BACKUP_DIR

# Create database backup
pg_dump optimed_gdpr > $BACKUP_FILE

# Compress backup
gzip $BACKUP_FILE

# Verify backup integrity
gunzip -t $BACKUP_FILE.gz

# Remove old backups (keep 30 days)
find $BACKUP_DIR -name "optimed_gdpr_*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_FILE.gz"
```

#### Configuration Backup
```bash
#!/bin/bash
# backup_config.sh

CONFIG_DIR="/var/backups/optimed/config"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $CONFIG_DIR

# Backup configuration files
tar -czf $CONFIG_DIR/config_$DATE.tar.gz \
    /etc/optimed/ \
    /opt/optimed/config/ \
    /home/optimed/.env*

echo "Configuration backup completed: $CONFIG_DIR/config_$DATE.tar.gz"
```

### Recovery Procedures

#### Database Recovery
```bash
#!/bin/bash
# restore_database.sh

BACKUP_FILE=$1

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup_file>"
    exit 1
fi

# Stop application
docker stop optimed-backend

# Drop and recreate database
psql -c "DROP DATABASE IF EXISTS optimed_gdpr;"
psql -c "CREATE DATABASE optimed_gdpr;"

# Restore from backup
gunzip -c $BACKUP_FILE | psql optimed_gdpr

# Verify restoration
psql optimed_gdpr -c "\dt"

# Restart application
docker start optimed-backend

echo "Database recovery completed"
```

## Performance Tuning

### Database Optimization
```sql
-- Analyze table statistics
ANALYZE;

-- Update table statistics
UPDATE pg_stat_user_tables SET n_tup_ins = 0, n_tup_upd = 0, n_tup_del = 0;

-- Check for missing indexes
SELECT 
    schemaname,
    tablename,
    attname,
    n_distinct,
    correlation
FROM pg_stats 
WHERE schemaname = 'public' 
AND n_distinct > 100
AND correlation < 0.1;
```

### Memory Optimization
```python
# memory_tuning.py
import psutil
import requests

def optimize_memory_usage():
    # Get current memory usage
    memory = psutil.virtual_memory()
    print(f"Current memory usage: {memory.percent}%")
    
    # Adjust embedding cache size based on available memory
    if memory.percent > 80:
        # Reduce cache size
        requests.post("http://localhost:8000/admin/set-cache-size", 
                     json={"max_memory_mb": 512})
    elif memory.percent < 50:
        # Increase cache size
        requests.post("http://localhost:8000/admin/set-cache-size", 
                     json={"max_memory_mb": 2048})

if __name__ == "__main__":
    optimize_memory_usage()
```

## Troubleshooting Guide

### Common Issues

#### High Memory Usage
**Symptoms**: Slow response times, memory warnings
**Causes**: Too many embeddings in RAM, memory leaks
**Solutions**:
```bash
# Check memory usage
curl -s http://localhost:8000/metrics/memory | jq '.'

# Force memory cleanup
curl -X POST http://localhost:8000/admin/cleanup-memory

# Restart if necessary
docker restart optimed-backend
```

#### Database Connection Issues
**Symptoms**: Connection timeouts, query failures
**Causes**: Connection pool exhaustion, database overload
**Solutions**:
```bash
# Check database connections
psql optimed_gdpr -c "SELECT count(*) FROM pg_stat_activity;"

# Check connection pool
curl -s http://localhost:8000/metrics/database | jq '.'

# Restart database if necessary
systemctl restart postgresql
```

#### Crypto-Shredding Failures
**Symptoms**: DEK deletion failures, cache corruption
**Causes**: KMS connectivity issues, cache corruption
**Solutions**:
```bash
# Check KMS connectivity
curl -s http://localhost:8000/admin/kms-status

# Clear corrupted cache
curl -X POST http://localhost:8000/admin/clear-cache

# Test crypto-shredding
curl -X POST http://localhost:8000/admin/test-crypto-shredding
```

### Diagnostic Commands

#### System Health Check
```bash
#!/bin/bash
# system_health_check.sh

echo "=== System Health Check ==="
echo

echo "=== Application Status ==="
curl -s http://localhost:8000/health | jq '.'
echo

echo "=== Memory Usage ==="
free -h
echo

echo "=== Disk Usage ==="
df -h
echo

echo "=== Database Status ==="
pg_isready -h localhost -p 5432
echo

echo "=== Recent Errors ==="
journalctl -u optimed-backend --since "1 hour ago" | grep -i error | tail -10
echo

echo "=== Audit Events (Last Hour) ==="
psql optimed_gdpr -c "
SELECT action, COUNT(*) as count
FROM audit_events 
WHERE occurred_at > NOW() - INTERVAL '1 hour'
GROUP BY action
ORDER BY count DESC;
"
```

This operational guide provides comprehensive procedures for managing the GDPR-compliant OptiMed AI system. Regular review and updates of these procedures ensure continued compliance and optimal system performance.
