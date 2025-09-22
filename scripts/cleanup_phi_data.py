#!/usr/bin/env python3
"""
PHI Data Cleanup Script for GDPR Compliance

This script safely removes PHI data from the database while preserving
necessary metadata for audit and operational purposes.

WARNING: This script will permanently delete PHI data. Ensure you have:
1. Proper authorization
2. Database backups
3. Verified that the new GDPR-safe schema is working
4. Completed data migration to the new schema

Usage:
    python scripts/cleanup_phi_data.py [--dry-run] [--force] [--backup]
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import json
import asyncpg
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'phi_cleanup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PHICleanupService:
    """Service for safely cleaning up PHI data."""
    
    def __init__(self, dsn: str, dry_run: bool = True):
        self.dsn = dsn
        self.dry_run = dry_run
        self.pool: Optional[asyncpg.Pool] = None
        self.cleanup_stats: Dict[str, Any] = {
            "start_time": datetime.now(timezone.utc),
            "tables_processed": 0,
            "records_processed": 0,
            "records_deleted": 0,
            "errors": []
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.pool = await asyncpg.create_pool(self.dsn)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.pool:
            await self.pool.close()
    
    async def run_cleanup(self) -> Dict[str, Any]:
        """Run the complete PHI cleanup process."""
        logger.info(f"Starting PHI cleanup process (dry_run={self.dry_run})")
        
        try:
            # Step 1: Verify new schema exists
            await self._verify_new_schema()
            
            # Step 2: Create backup if requested
            if not self.dry_run:
                await self._create_backup()
            
            # Step 3: Clean up embeddings table
            await self._cleanup_embeddings_table()
            
            # Step 4: Clean up user data
            await self._cleanup_user_data()
            
            # Step 5: Clean up DICOM images
            await self._cleanup_dicom_images()
            
            # Step 6: Clean up generated images
            await self._cleanup_generated_images()
            
            # Step 7: Clean up EHR connections
            await self._cleanup_ehr_connections()
            
            # Step 8: Verify cleanup
            await self._verify_cleanup()
            
            self.cleanup_stats["end_time"] = datetime.now(timezone.utc)
            self.cleanup_stats["duration_seconds"] = (
                self.cleanup_stats["end_time"] - self.cleanup_stats["start_time"]
            ).total_seconds()
            
            logger.info("PHI cleanup completed successfully")
            return self.cleanup_stats
            
        except Exception as e:
            logger.error(f"PHI cleanup failed: {e}")
            self.cleanup_stats["errors"].append(str(e))
            raise
    
    async def _verify_new_schema(self):
        """Verify that the new GDPR-safe schema exists."""
        logger.info("Verifying new GDPR-safe schema...")
        
        async with self.pool.acquire() as conn:
            # Check for new tables
            required_tables = [
                "sessions", "audit_events", "resources", "resource_codes",
                "evidence_sets", "model_registry", "retrieval_config",
                "users_gdpr_safe", "embeddings_metadata"
            ]
            
            for table in required_tables:
                exists = await conn.fetchval(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = '{table}'
                    )
                """)
                
                if not exists:
                    raise RuntimeError(f"Required table '{table}' not found in new schema")
            
            logger.info("✅ New GDPR-safe schema verified")
    
    async def _create_backup(self):
        """Create backup of current data before cleanup."""
        logger.info("Creating backup of current data...")
        
        backup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(f"backups/phi_cleanup_{backup_timestamp}")
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Tables to backup
        tables_to_backup = [
            "embeddings", "users", "user_sessions", "user_actions",
            "dicom_images", "generated_images", "user_ehr_connections"
        ]
        
        async with self.pool.acquire() as conn:
            for table in tables_to_backup:
                try:
                    # Check if table exists
                    exists = await conn.fetchval(f"""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = '{table}'
                        )
                    """)
                    
                    if not exists:
                        logger.warning(f"Table '{table}' does not exist, skipping backup")
                        continue
                    
                    # Export table data
                    rows = await conn.fetch(f"SELECT * FROM {table}")
                    
                    if rows:
                        backup_file = backup_dir / f"{table}.json"
                        with open(backup_file, 'w') as f:
                            json.dump([dict(row) for row in rows], f, indent=2, default=str)
                        
                        logger.info(f"✅ Backed up {len(rows)} rows from {table}")
                    else:
                        logger.info(f"✅ Table {table} is empty, no backup needed")
                        
                except Exception as e:
                    logger.error(f"Failed to backup table {table}: {e}")
                    self.cleanup_stats["errors"].append(f"Backup failed for {table}: {e}")
        
        logger.info(f"✅ Backup completed in {backup_dir}")
    
    async def _cleanup_embeddings_table(self):
        """Clean up embeddings table by removing PHI content."""
        logger.info("Cleaning up embeddings table...")
        
        async with self.pool.acquire() as conn:
            # Count records before cleanup
            total_records = await conn.fetchval("SELECT COUNT(*) FROM embeddings")
            logger.info(f"Found {total_records} records in embeddings table")
            
            if self.dry_run:
                # In dry run, just count what would be affected
                content_records = await conn.fetchval("""
                    SELECT COUNT(*) FROM embeddings 
                    WHERE content IS NOT NULL AND content != ''
                """)
                logger.info(f"Would remove content from {content_records} records")
                self.cleanup_stats["records_processed"] += content_records
                return
            
            # Remove content column (this removes PHI)
            try:
                await conn.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS content")
                logger.info("✅ Removed content column from embeddings table")
                self.cleanup_stats["records_deleted"] += total_records
            except Exception as e:
                logger.error(f"Failed to remove content column: {e}")
                self.cleanup_stats["errors"].append(f"Failed to remove content column: {e}")
            
            # Remove embedding column (vectors are now RAM-only)
            try:
                await conn.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS embedding")
                logger.info("✅ Removed embedding column from embeddings table")
            except Exception as e:
                logger.error(f"Failed to remove embedding column: {e}")
                self.cleanup_stats["errors"].append(f"Failed to remove embedding column: {e}")
            
            self.cleanup_stats["records_processed"] += total_records
            self.cleanup_stats["tables_processed"] += 1
    
    async def _cleanup_user_data(self):
        """Clean up user data by pseudonymizing PII."""
        logger.info("Cleaning up user data...")
        
        async with self.pool.acquire() as conn:
            # Count users before cleanup
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            logger.info(f"Found {total_users} users to process")
            
            if self.dry_run:
                logger.info("Would pseudonymize user PII fields")
                self.cleanup_stats["records_processed"] += total_users
                return
            
            # Pseudonymize user data
            try:
                # Update emails, names, and phone numbers to hashed versions
                await conn.execute("""
                    UPDATE users SET
                        email = encode(digest(email || 'gdpr_salt', 'sha256'), 'hex'),
                        first_name = encode(digest(first_name || 'gdpr_salt', 'sha256'), 'hex'),
                        last_name = encode(digest(last_name || 'gdpr_salt', 'sha256'), 'hex'),
                        phone = CASE 
                            WHEN phone IS NOT NULL THEN encode(digest(phone || 'gdpr_salt', 'sha256'), 'hex')
                            ELSE NULL 
                        END,
                        updated_at = NOW()
                """)
                
                logger.info("✅ Pseudonymized user PII data")
                self.cleanup_stats["records_processed"] += total_users
                self.cleanup_stats["tables_processed"] += 1
                
            except Exception as e:
                logger.error(f"Failed to pseudonymize user data: {e}")
                self.cleanup_stats["errors"].append(f"Failed to pseudonymize user data: {e}")
    
    async def _cleanup_dicom_images(self):
        """Clean up DICOM images by removing patient names from metadata."""
        logger.info("Cleaning up DICOM images...")
        
        async with self.pool.acquire() as conn:
            # Count images before cleanup
            total_images = await conn.fetchval("SELECT COUNT(*) FROM dicom_images")
            logger.info(f"Found {total_images} DICOM images to process")
            
            if self.dry_run:
                # Count images with patient names
                images_with_names = await conn.fetchval("""
                    SELECT COUNT(*) FROM dicom_images 
                    WHERE metadata_json ? 'patient_name'
                """)
                logger.info(f"Would remove patient names from {images_with_names} images")
                self.cleanup_stats["records_processed"] += images_with_names
                return
            
            # Remove patient names from metadata
            try:
                await conn.execute("""
                    UPDATE dicom_images 
                    SET metadata_json = metadata_json - 'patient_name',
                        updated_at = NOW()
                    WHERE metadata_json ? 'patient_name'
                """)
                
                affected_rows = await conn.fetchval("""
                    SELECT COUNT(*) FROM dicom_images 
                    WHERE metadata_json ? 'patient_name'
                """)
                
                logger.info(f"✅ Removed patient names from {total_images - affected_rows} DICOM images")
                self.cleanup_stats["records_processed"] += total_images
                self.cleanup_stats["tables_processed"] += 1
                
            except Exception as e:
                logger.error(f"Failed to clean DICOM image metadata: {e}")
                self.cleanup_stats["errors"].append(f"Failed to clean DICOM metadata: {e}")
    
    async def _cleanup_generated_images(self):
        """Clean up generated images by flagging PHI content."""
        logger.info("Cleaning up generated images...")
        
        async with self.pool.acquire() as conn:
            # Count images before cleanup
            total_images = await conn.fetchval("SELECT COUNT(*) FROM generated_images")
            logger.info(f"Found {total_images} generated images to process")
            
            if self.dry_run:
                logger.info("Would flag prompts as PHI-redacted")
                self.cleanup_stats["records_processed"] += total_images
                return
            
            # Flag prompts as PHI-redacted
            try:
                await conn.execute("""
                    UPDATE generated_images 
                    SET 
                        phi_redacted = TRUE,
                        original_prompt_hash = encode(digest(prompt, 'sha256'), 'hex'),
                        prompt = '[PHI REDACTED]',
                        updated_at = NOW()
                    WHERE phi_redacted IS NULL OR phi_redacted = FALSE
                """)
                
                logger.info("✅ Flagged generated image prompts as PHI-redacted")
                self.cleanup_stats["records_processed"] += total_images
                self.cleanup_stats["tables_processed"] += 1
                
            except Exception as e:
                logger.error(f"Failed to clean generated images: {e}")
                self.cleanup_stats["errors"].append(f"Failed to clean generated images: {e}")
    
    async def _cleanup_ehr_connections(self):
        """Clean up EHR connections by pseudonymizing patient context."""
        logger.info("Cleaning up EHR connections...")
        
        async with self.pool.acquire() as conn:
            # Count connections before cleanup
            total_connections = await conn.fetchval("SELECT COUNT(*) FROM user_ehr_connections")
            logger.info(f"Found {total_connections} EHR connections to process")
            
            if self.dry_run:
                logger.info("Would pseudonymize patient context references")
                self.cleanup_stats["records_processed"] += total_connections
                return
            
            # Pseudonymize patient context
            try:
                await conn.execute("""
                    UPDATE user_ehr_connections 
                    SET 
                        patient_context = CASE 
                            WHEN patient_context IS NOT NULL 
                            THEN encode(digest(patient_context || 'gdpr_salt', 'sha256'), 'hex')
                            ELSE NULL 
                        END,
                        updated_at = NOW()
                """)
                
                logger.info("✅ Pseudonymized EHR connection patient contexts")
                self.cleanup_stats["records_processed"] += total_connections
                self.cleanup_stats["tables_processed"] += 1
                
            except Exception as e:
                logger.error(f"Failed to clean EHR connections: {e}")
                self.cleanup_stats["errors"].append(f"Failed to clean EHR connections: {e}")
    
    async def _verify_cleanup(self):
        """Verify that PHI cleanup was successful."""
        logger.info("Verifying PHI cleanup...")
        
        async with self.pool.acquire() as conn:
            # Check that no PHI content remains
            checks = [
                ("embeddings", "content", "SELECT COUNT(*) FROM embeddings WHERE content IS NOT NULL"),
                ("users", "email", "SELECT COUNT(*) FROM users WHERE email LIKE '%@%'"),
                ("dicom_images", "patient_name", "SELECT COUNT(*) FROM dicom_images WHERE metadata_json ? 'patient_name'"),
                ("generated_images", "phi_redacted", "SELECT COUNT(*) FROM generated_images WHERE phi_redacted = FALSE")
            ]
            
            for table, field, query in checks:
                try:
                    count = await conn.fetchval(query)
                    if count > 0:
                        logger.warning(f"⚠️  Found {count} records in {table}.{field} that may contain PHI")
                        self.cleanup_stats["errors"].append(f"PHI may remain in {table}.{field}: {count} records")
                    else:
                        logger.info(f"✅ Verified no PHI in {table}.{field}")
                except Exception as e:
                    logger.error(f"Failed to verify {table}.{field}: {e}")
                    self.cleanup_stats["errors"].append(f"Verification failed for {table}.{field}: {e}")
        
        logger.info("✅ PHI cleanup verification completed")
    
    def print_summary(self):
        """Print cleanup summary."""
        stats = self.cleanup_stats
        
        print("\n" + "="*60)
        print("PHI CLEANUP SUMMARY")
        print("="*60)
        print(f"Start Time: {stats['start_time']}")
        print(f"End Time: {stats['end_time']}")
        print(f"Duration: {stats.get('duration_seconds', 0):.2f} seconds")
        print(f"Tables Processed: {stats['tables_processed']}")
        print(f"Records Processed: {stats['records_processed']}")
        print(f"Records Deleted/Modified: {stats['records_deleted']}")
        print(f"Errors: {len(stats['errors'])}")
        
        if stats['errors']:
            print("\nERRORS:")
            for error in stats['errors']:
                print(f"  - {error}")
        
        print("="*60)

async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="PHI Data Cleanup Script for GDPR Compliance")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Perform a dry run without making changes")
    parser.add_argument("--force", action="store_true",
                       help="Force cleanup without confirmation prompts")
    parser.add_argument("--backup", action="store_true",
                       help="Create backup before cleanup")
    parser.add_argument("--dsn", type=str,
                       help="Database connection string")
    
    args = parser.parse_args()
    
    # Get database DSN
    dsn = args.dsn or os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")
    if not dsn:
        logger.error("No database DSN provided. Use --dsn or set PGVECTOR_DSN environment variable.")
        sys.exit(1)
    
    # Confirmation prompt
    if not args.force and not args.dry_run:
        print("\n" + "!"*60)
        print("WARNING: This will permanently delete PHI data from your database!")
        print("Make sure you have:")
        print("1. Database backups")
        print("2. Verified the new GDPR schema is working")
        print("3. Proper authorization")
        print("!"*60)
        
        response = input("\nAre you sure you want to continue? Type 'YES' to confirm: ")
        if response != "YES":
            print("Cleanup cancelled.")
            sys.exit(0)
    
    # Run cleanup
    try:
        async with PHICleanupService(dsn, dry_run=args.dry_run) as cleanup_service:
            stats = await cleanup_service.run_cleanup()
            cleanup_service.print_summary()
            
            if stats["errors"]:
                logger.error(f"Cleanup completed with {len(stats['errors'])} errors")
                sys.exit(1)
            else:
                logger.info("PHI cleanup completed successfully!")
                sys.exit(0)
                
    except Exception as e:
        logger.error(f"PHI cleanup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
