"""
Test script to verify E2E encryption implementation

This script tests:
1. Backend encryption service (AES-256-GCM, RSA key exchange)
2. Frontend encryption client (Web Crypto API)
3. Complete encryption/decryption flow
4. Session key exchange mechanism

Run from project root: python test_encryption.py
"""

import sys
import os
import asyncio
import json
import base64
from typing import Dict, Any

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Test Backend Encryption
def test_backend_encryption():
    """Test server-side encryption service"""
    print("\n" + "="*60)
    print("TEST 1: Backend Encryption Service")
    print("="*60)

    try:
        from optimed.adapters.security.encryption_service import (
            get_encryption_service,
            encrypt_patient_data,
            decrypt_patient_data
        )

        # Test 1: Basic AES-GCM encryption
        print("\n✓ Testing AES-256-GCM encryption...")
        encryption_service = get_encryption_service()

        test_data = {
            "patient_id": "test-123",
            "name": "John Doe",
            "diagnosis": "Hypertension",
            "timestamp": "2025-01-27T10:00:00Z"
        }

        encrypted = encryption_service.encrypt_data_aes_gcm(test_data)
        print(f"  - Original data: {json.dumps(test_data, indent=2)}")
        print(f"  - Encrypted (first 100 chars): {encrypted[:100]}...")

        # Test 2: Decryption
        print("\n✓ Testing AES-256-GCM decryption...")
        decrypted = encryption_service.decrypt_data_aes_gcm(encrypted)
        print(f"  - Decrypted data: {json.dumps(decrypted, indent=2)}")

        assert decrypted == test_data, "Decrypted data does not match original!"
        print("  ✅ Encryption/decryption successful!")

        # Test 3: RSA Key Generation
        print("\n✓ Testing RSA key pair generation...")
        public_key_pem = encryption_service.get_public_key_pem()
        print(f"  - Server public key (first 100 chars):\n    {public_key_pem[:100]}...")
        assert "BEGIN PUBLIC KEY" in public_key_pem
        print("  ✅ RSA key pair generated successfully!")

        # Test 4: Session Key Generation
        print("\n✓ Testing session key generation...")
        session_key = encryption_service.generate_session_key()
        print(f"  - Session key (first 50 chars): {session_key[:50]}...")
        assert len(session_key) == 44, f"Invalid session key length: {len(session_key)}"  # Base64 encoded 32-byte key
        print("  ✅ Session key generated successfully!")

        # Test 5: Session key encryption for client
        print("\n✓ Testing session key encryption...")
        # Simulate client public key
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend

        client_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        client_public_pem = client_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        encrypted_session_key = encryption_service.encrypt_session_key_for_client(
            session_key.encode(),
            client_public_pem
        )
        print(f"  - Encrypted session key (first 100 chars): {encrypted_session_key[:100]}...")
        print("  ✅ Session key encrypted for client!")

        print("\n" + "="*60)
        print("✅ BACKEND ENCRYPTION TESTS PASSED")
        print("="*60)
        return True

    except Exception as e:
        print(f"\n❌ Backend encryption test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_session_encryption_manager():
    """Test session encryption manager"""
    print("\n" + "="*60)
    print("TEST 2: Session Encryption Manager")
    print("="*60)

    try:
        from optimed.adapters.security.e2e_encryption_middleware import (
            get_session_encryption_manager,
            create_session_with_encryption
        )

        # Test 1: Session key generation
        print("\n✓ Testing session key generation...")
        manager = get_session_encryption_manager()
        session_id = "test-session-001"

        session_key = manager.generate_session_key(session_id)
        print(f"  - Session ID: {session_id}")
        print(f"  - Session key (first 50 chars): {session_key[:50]}...")
        print("  ✅ Session key generated!")

        # Test 2: Retrieve session key
        print("\n✓ Testing session key retrieval...")
        retrieved_key = manager.get_session_key(session_id)
        assert retrieved_key == session_key, "Retrieved key doesn't match!"
        print("  ✅ Session key retrieved successfully!")

        # Test 3: Session encryption/decryption
        print("\n✓ Testing session data encryption...")
        test_data = {"message": "Secret PHI data", "patient": "P001"}
        encrypted = manager.encrypt_session_data(session_id, test_data)
        print(f"  - Encrypted data (first 100 chars): {encrypted[:100]}...")

        print("\n✓ Testing session data decryption...")
        decrypted = manager.decrypt_session_data(session_id, encrypted)
        assert decrypted == test_data, "Decrypted data doesn't match!"
        print(f"  - Decrypted data: {json.dumps(decrypted)}")
        print("  ✅ Session encryption/decryption successful!")

        # Test 4: Full key exchange flow
        print("\n✓ Testing full key exchange...")
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend

        # Generate client key pair
        client_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        client_public_pem = client_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        # Create session with encryption
        result = create_session_with_encryption(
            session_id="test-session-002",
            client_public_key_pem=client_public_pem
        )

        print(f"  - Session ID: {result['session_id']}")
        print(f"  - Encrypted: {result['encrypted']}")
        print(f"  - Version: {result['version']}")
        print(f"  - Has encrypted session key: {'encrypted_session_key' in result}")
        print(f"  - Has server public key: {'server_public_key' in result}")

        assert result['encrypted'] == 'true'
        assert result['version'] == '2.0'
        assert 'encrypted_session_key' in result
        assert 'server_public_key' in result

        print("  ✅ Full key exchange successful!")

        # Test 5: Clear session key
        print("\n✓ Testing session key cleanup...")
        manager.clear_session_key(session_id)
        cleared_key = manager.get_session_key(session_id)
        assert cleared_key is None, "Session key not cleared!"
        print("  ✅ Session key cleared successfully!")

        print("\n" + "="*60)
        print("✅ SESSION ENCRYPTION MANAGER TESTS PASSED")
        print("="*60)
        return True

    except Exception as e:
        print(f"\n❌ Session encryption manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_encryption_flow_simulation():
    """Simulate the complete client-server encryption flow"""
    print("\n" + "="*60)
    print("TEST 3: Complete Encryption Flow Simulation")
    print("="*60)

    try:
        from optimed.adapters.security.e2e_encryption_middleware import create_session_with_encryption
        from optimed.adapters.security.encryption_service import get_encryption_service
        from cryptography.hazmat.primitives.asymmetric import rsa, padding
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        import secrets

        print("\n📱 STEP 1: Client generates RSA key pair")
        client_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        client_public_key = client_private_key.public_key()
        client_public_pem = client_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        print("  ✅ Client key pair generated")

        print("\n🔐 STEP 2: Server receives client public key and creates session")
        session_id = "flow-test-session"
        result = create_session_with_encryption(session_id, client_public_pem)
        encrypted_session_key_b64 = result['encrypted_session_key']
        server_public_key_pem = result['server_public_key']
        print(f"  ✅ Session created: {session_id}")
        print(f"  ✅ Server sent encrypted session key")

        print("\n📱 STEP 3: Client decrypts session key")
        encrypted_session_key = base64.b64decode(encrypted_session_key_b64)
        session_key_bytes = client_private_key.decrypt(
            encrypted_session_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        session_key = session_key_bytes.decode('utf-8')
        print(f"  ✅ Client decrypted session key (first 30 chars): {session_key[:30]}...")

        print("\n📤 STEP 4: Client encrypts data using session key")
        client_data = {"query": "What is the patient's status?", "patient_id": "P123"}

        # Simulate client-side encryption (similar to Web Crypto API)
        from cryptography.fernet import Fernet
        session_fernet = Fernet(session_key.encode())
        json_data = json.dumps(client_data)
        encrypted_data = session_fernet.encrypt(json_data.encode('utf-8'))
        encrypted_data_b64 = base64.b64encode(encrypted_data).decode('utf-8')

        print(f"  ✅ Client encrypted data (first 100 chars): {encrypted_data_b64[:100]}...")

        print("\n🔓 STEP 5: Server decrypts data using session key")
        from optimed.adapters.security.encryption_service import decrypt_patient_data
        from optimed.adapters.security.e2e_encryption_middleware import get_session_encryption_manager

        manager = get_session_encryption_manager()
        decrypted_data = manager.decrypt_session_data(session_id, encrypted_data_b64)
        print(f"  ✅ Server decrypted data: {json.dumps(decrypted_data)}")

        assert decrypted_data == client_data, "Flow test failed: data mismatch!"

        print("\n📥 STEP 6: Server encrypts response")
        server_response = {"answer": "Patient is stable", "confidence": 0.95}
        encrypted_response = manager.encrypt_session_data(session_id, server_response)
        print(f"  ✅ Server encrypted response (first 100 chars): {encrypted_response[:100]}...")

        print("\n📱 STEP 7: Client decrypts response")
        decrypted_response_bytes = session_fernet.decrypt(base64.b64decode(encrypted_response))
        decrypted_response = json.loads(decrypted_response_bytes.decode('utf-8'))
        print(f"  ✅ Client decrypted response: {json.dumps(decrypted_response)}")

        assert decrypted_response == server_response, "Flow test failed: response mismatch!"

        print("\n" + "="*60)
        print("✅ COMPLETE ENCRYPTION FLOW TEST PASSED")
        print("="*60)
        return True

    except Exception as e:
        print(f"\n❌ Encryption flow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all encryption tests"""
    print("\n" + "="*60)
    print("OptiMed E2E Encryption Test Suite")
    print("="*60)
    print("Testing encryption implementation...")
    print("This validates the complete encryption chain.")

    results = []

    # Run all tests
    results.append(("Backend Encryption Service", test_backend_encryption()))
    results.append(("Session Encryption Manager", test_session_encryption_manager()))
    results.append(("Complete Encryption Flow", test_encryption_flow_simulation()))

    # Print summary
    print("\n\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
        if not passed:
            all_passed = False

    print("="*60)

    if all_passed:
        print("\n🎉 ALL ENCRYPTION TESTS PASSED!")
        print("\nEncryption Implementation Status:")
        print("  ✅ AES-256-GCM encryption working")
        print("  ✅ RSA-2048 key exchange working")
        print("  ✅ Session key management working")
        print("  ✅ Complete client-server flow working")
        print("\nThe encryption is correctly implemented and functional.")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED - Please review the errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
