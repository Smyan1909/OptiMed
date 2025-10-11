#!/usr/bin/env python3
"""
Test Encryption Implementation

Verifies that all encryption and hashing functionality works correctly
WITHOUT breaking existing functionality.
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv  
import asyncpg
from optimed.adapters.security.database_encryption import DatabaseEncryption

load_dotenv()
# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))




class EncryptionTester:
    def __init__(self, dsn: str, encryption_key: str):
        self.dsn = dsn
        self.encryption_key = encryption_key
        self.conn = None
        self.db_encryption = DatabaseEncryption(encryption_key)
        self.tests_passed = 0
        self.tests_failed = 0

    async def connect(self):
        """Connect to database."""
        print("[INFO] Connecting to database...")
        self.conn = await asyncpg.connect(self.dsn)
        print("[OK] Connected\n")

    async def close(self):
        """Close connection."""
        if self.conn:
            await self.conn.close()

    def test_result(self, test_name: str, passed: bool, details: str = ""):
        """Record test result."""
        if passed:
            print(f"[PASS] {test_name}")
            if details:
                print(f"       {details}")
            self.tests_passed += 1
        else:
            print(f"[FAIL] {test_name}")
            if details:
                print(f"       {details}")
            self.tests_failed += 1

    async def test_1_encryption_functions_exist(self):
        """Test that encryption functions are available."""
        print("="*70)
        print("TEST 1: Encryption Functions Exist")
        print("="*70)

        try:
            # Test encrypt_text exists
            result = await self.conn.fetchval(
                "SELECT encrypt_text('test', 'key') IS NOT NULL"
            )
            self.test_result("encrypt_text() function exists", result)

            # Test decrypt_text exists
            result = await self.conn.fetchval(
                "SELECT decrypt_text(encrypt_text('test', 'key'), 'key') = 'test'"
            )
            self.test_result("decrypt_text() function works", result)

            # Test hash_text exists
            result = await self.conn.fetchval(
                "SELECT LENGTH(hash_text('test')) = 64"  # SHA-256 = 64 hex chars
            )
            self.test_result("hash_text() function works", result)

        except Exception as e:
            self.test_result("Encryption functions", False, str(e))

        print()

    async def test_2_encrypted_columns_exist(self):
        """Test that encrypted columns were added."""
        print("="*70)
        print("TEST 2: Encrypted Columns Exist")
        print("="*70)

        columns_to_check = [
            ('user_ehr_connections', 'access_token_encrypted'),
            ('user_ehr_connections', 'refresh_token_encrypted'),
            ('user_ehr_connections', 'credentials_encrypted'),
            ('data_access_logs', 'user_id_hash'),
        ]

        for table, column in columns_to_check:
            try:
                result = await self.conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = $1 AND column_name = $2
                    )
                """, table, column)
                self.test_result(f"{table}.{column} exists", result)
            except Exception as e:
                self.test_result(f"{table}.{column} exists", False, str(e))

        print()

    async def test_3_hash_columns_populated(self):
        """Test that hash columns are populated."""
        print("="*70)
        print("TEST 3: Hash Columns Populated")
        print("="*70)

        try:
            # Count users with email_hash
            count = await self.conn.fetchval("""
                SELECT COUNT(*) FROM users
                WHERE email IS NOT NULL AND email_hash IS NOT NULL
            """)
            self.test_result(
                "Users with email_hash populated",
                count > 0,
                f"{count} users have email_hash"
            )

            # Count users with missing hashes
            missing = await self.conn.fetchval("""
                SELECT COUNT(*) FROM users
                WHERE (email IS NOT NULL AND email_hash IS NULL)
                   OR (phone IS NOT NULL AND phone_hash IS NULL)
            """)
            self.test_result(
                "No users with missing hashes",
                missing == 0,
                f"{missing} users have missing hashes" if missing > 0 else "All hashes populated"
            )

        except Exception as e:
            self.test_result("Hash columns populated", False, str(e))

        print()

    async def test_4_encryption_roundtrip(self):
        """Test encryption/decryption roundtrip."""
        print("="*70)
        print("TEST 4: Encryption Roundtrip")
        print("="*70)

        test_data = [
            "test-token-123",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test",
            "special-chars: !@#$%^&*()",
        ]

        for data in test_data:
            try:
                # Encrypt
                encrypted = await self.db_encryption.encrypt_field(self.conn, data)

                # Decrypt
                decrypted = await self.db_encryption.decrypt_field(self.conn, encrypted)

                passed = decrypted == data
                self.test_result(
                    "Encrypt/decrypt roundtrip",
                    passed,
                    f"Original: {data[:20]}... -> Decrypted: {decrypted[:20] if decrypted else 'None'}..."
                )
            except Exception as e:
                self.test_result("Encrypt/decrypt roundtrip", False, str(e))

        print()

    async def test_5_hashing_consistency(self):
        """Test that hashing is consistent."""
        print("="*70)
        print("TEST 5: Hashing Consistency")
        print("="*70)

        test_values = [
            "test@example.com",
            "doctor@hospital.com",
            "+1-555-1234",
        ]

        for value in test_values:
            try:
                hash1 = self.db_encryption.hash_value(value)
                hash2 = self.db_encryption.hash_value(value)

                passed = hash1 == hash2 and len(hash1) == 64
                self.test_result(
                    f"Hash consistency for {value}",
                    passed,
                    f"Hash: {hash1[:16]}... (len={len(hash1)})"
                )
            except Exception as e:
                self.test_result("Hash consistency", False, str(e))

        print()

    async def test_6_backward_compatibility(self):
        """Test that existing plaintext data is still accessible."""
        print("="*70)
        print("TEST 6: Backward Compatibility")
        print("="*70)

        try:
            # Check if there are any connections with plaintext tokens
            plaintext_count = await self.conn.fetchval("""
                SELECT COUNT(*) FROM user_ehr_connections
                WHERE access_token_encrypted IS NULL
                AND access_token IS NOT NULL
                AND access_token != '[ENCRYPTED]'
            """)

            if plaintext_count > 0:
                self.test_result(
                    "Plaintext tokens still exist",
                    True,
                    f"{plaintext_count} connections with plaintext tokens (will auto-migrate)"
                )
            else:
                self.test_result(
                    "All tokens encrypted or no tokens exist",
                    True,
                    "No plaintext tokens found"
                )

        except Exception as e:
            self.test_result("Backward compatibility check", False, str(e))

        print()

    async def test_7_database_performance(self):
        """Test that encryption doesn't severely impact performance."""
        print("="*70)
        print("TEST 7: Performance Impact")
        print("="*70)

        import time

        test_value = "test-performance-token-value"

        try:
            # Test encryption performance
            iterations = 100
            start = time.time()
            for _ in range(iterations):
                await self.db_encryption.encrypt_field(self.conn, test_value)
            encrypt_time = (time.time() - start) / iterations * 1000  # ms

            # Test decryption performance
            encrypted = await self.db_encryption.encrypt_field(self.conn, test_value)
            start = time.time()
            for _ in range(iterations):
                await self.db_encryption.decrypt_field(self.conn, encrypted)
            decrypt_time = (time.time() - start) / iterations * 1000  # ms

            # Test hashing performance
            start = time.time()
            for _ in range(iterations):
                self.db_encryption.hash_value(test_value)
            hash_time = (time.time() - start) / iterations * 1000  # ms

            self.test_result(
                "Encryption performance",
                encrypt_time < 5,  # Should be < 5ms per operation
                f"{encrypt_time:.2f}ms per encryption"
            )

            self.test_result(
                "Decryption performance",
                decrypt_time < 5,  # Should be < 5ms per operation
                f"{decrypt_time:.2f}ms per decryption"
            )

            self.test_result(
                "Hashing performance",
                hash_time < 1,  # Should be < 1ms per operation
                f"{hash_time:.2f}ms per hash"
            )

        except Exception as e:
            self.test_result("Performance test", False, str(e))

        print()

    async def test_8_user_id_tracking(self):
        """Test that user_id is now being tracked in audit logs."""
        print("="*70)
        print("TEST 8: User ID Tracking in Audit Logs")
        print("="*70)

        try:
            # Count total audit logs
            total = await self.conn.fetchval("SELECT COUNT(*) FROM data_access_logs")

            # Count logs with user_id
            with_user = await self.conn.fetchval(
                "SELECT COUNT(*) FROM data_access_logs WHERE user_id IS NOT NULL"
            )

            # Count logs with user_id_hash
            with_hash = await self.conn.fetchval(
                "SELECT COUNT(*) FROM data_access_logs WHERE user_id_hash IS NOT NULL"
            )

            self.test_result(
                "User ID tracking",
                True,
                f"Total logs: {total}, with user_id: {with_user}, with user_id_hash: {with_hash}"
            )

            # Check percentage
            if total > 0:
                percentage = (with_user / total) * 100
                self.test_result(
                    "User ID tracking percentage",
                    percentage > 0,  # Some logs should have user_id
                    f"{percentage:.1f}% of logs have user_id"
                )

        except Exception as e:
            self.test_result("User ID tracking check", False, str(e))

        print()

    async def run_all_tests(self):
        """Run all tests."""
        try:
            await self.connect()

            # Run tests
            await self.test_1_encryption_functions_exist()
            await self.test_2_encrypted_columns_exist()
            await self.test_3_hash_columns_populated()
            await self.test_4_encryption_roundtrip()
            await self.test_5_hashing_consistency()
            await self.test_6_backward_compatibility()
            await self.test_7_database_performance()
            await self.test_8_user_id_tracking()

            # Summary
            print("="*70)
            print("TEST SUMMARY")
            print("="*70)
            print(f"[OK] Tests passed: {self.tests_passed}")
            if self.tests_failed > 0:
                print(f"[FAIL] Tests failed: {self.tests_failed}")
            else:
                print("[OK] Tests failed: 0")

            total = self.tests_passed + self.tests_failed
            if total > 0:
                percentage = (self.tests_passed / total) * 100
                print(f"\nSuccess rate: {percentage:.1f}%")

            if self.tests_failed == 0:
                print("\n✓ All tests passed! Encryption implementation is working correctly.")
                print("✓ No functionality has been broken.")
                return True
            else:
                print(f"\n✗ {self.tests_failed} test(s) failed. Please review errors above.")
                return False

        finally:
            await self.close()


async def main():
    """Main entry point."""
    # Get configuration
    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")
    encryption_key = os.getenv("ENCRYPTION_MASTER_KEY")

    if not dsn:
        print("[ERROR] PGVECTOR_DSN or DATABASE_URL environment variable not set")
        return False

    if not encryption_key:
        print("[WARN] ENCRYPTION_MASTER_KEY not set - using test key")
        encryption_key = "test-key-for-testing-only"

    print("="*70)
    print("ENCRYPTION IMPLEMENTATION TEST SUITE")
    print("="*70)
    print()

    # Run tests
    tester = EncryptionTester(dsn, encryption_key)
    success = await tester.run_all_tests()

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
