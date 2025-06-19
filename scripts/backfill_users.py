import asyncio
import uuid
from optimed.core.domain import User, UserRole, UserStatus
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
import os
from dotenv import load_dotenv

async def init_sample_users():
    """Create sample users for testing."""
    load_dotenv()
    
    user_dsn = os.getenv("PGVECTOR_DSN")
    user_repo = PGUserRepository(dsn=user_dsn)
    
    sample_users = [
        User(
            user_id=str(uuid.uuid4()),
            username="dr.smith",
            email="smith@hospital.com",
            first_name="John",
            last_name="Smith",
            role=UserRole.DOCTOR,
            status=UserStatus.ACTIVE,
            department="Emergency",
            license_number="MD123456"
        ),
        User(
            user_id=str(uuid.uuid4()),
            username="nurse.johnson",
            email="johnson@hospital.com",
            first_name="Sarah",
            last_name="Johnson",
            role=UserRole.NURSE,
            status=UserStatus.ACTIVE,
            department="ICU"
        ),
        User(
            user_id=str(uuid.uuid4()),
            username="admin",
            email="admin@hospital.com",
            first_name="Admin",
            last_name="User",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
            department="IT"
        )
    ]
    
    for user in sample_users:
        try:
            await user_repo.create_user(user)
            print(f"Created user: {user.username} ({user.role.value})")
        except Exception as e:
            print(f"Error creating user {user.username}: {e}")
    
    await user_repo.close()

if __name__ == "__main__":
    asyncio.run(init_sample_users())