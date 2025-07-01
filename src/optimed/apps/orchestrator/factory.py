import os
from typing import Tuple
from optimed.apps.orchestrator.patient_flow import LangGraphDiagnosticEngine
from optimed.apps.orchestrator.connection_service import UserEHRConnectionService
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.adapters.smart_fhir.repository import SMARTFHIRRepository
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.adapters.user_repository.pg_ehr_connection_repository import PGUserEHRConnectionRepository
from optimed.core.ports import DiagnosticEngine, FHIRRepository, VectorStore, UserRepository, UserEHRConnectionRepository
from optimed.adapters.dicom.pydicom_processor import PyDICOMProcessor
from optimed.adapters.dicom.image_service import ImageServiceImpl
from optimed.adapters.dicom.pg_image_repository import PostgreSQLImageRepository
from optimed.adapters.dicom.image_storage import FileSystemImageStorage
from optimed.core.domain import UserEHRConnection
from datetime import datetime, timezone
from dotenv import load_dotenv # type: ignore


def create_smart_fhir_repository() -> SMARTFHIRRepository:
    """Create a SMART FHIR repository with environment configuration."""
    # This creates a basic SMART repository for testing - real connections come through the service
    from optimed.adapters.smart_fhir.auth_provider import SMARTAuthProvider
    
    # Create a dummy connection for the default repository
    dummy_connection = UserEHRConnection(
        connection_id="default",
        user_id="system",
        provider_type="smart_fhir",
        fhir_server_url=os.getenv("SMART_FHIR_SERVER_URL", "https://launch.smarthealthit.org/v/r4/fhir"),
        client_id=os.getenv("SMART_CLIENT_ID", "demo_client"),
        credentials={},
        is_active=False,  # Not authenticated
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    auth_provider = SMARTAuthProvider(
        fhir_server_url=dummy_connection.fhir_server_url,
        client_id=dummy_connection.client_id,
        client_secret=os.getenv("SMART_CLIENT_SECRET"),
        redirect_uri=os.getenv("SMART_REDIRECT_URI", "http://localhost:3000/api/smart/callback")
    )
    
    return SMARTFHIRRepository(dummy_connection, auth_provider)


def create_app_dependencies(use_smart=False) -> Tuple[DiagnosticEngine, FHIRRepository, VectorStore, UserRepository, UserEHRConnectionRepository, UserEHRConnectionService]:
    """Factory function to wire up all application dependencies."""

    # Load environment variables from .env file
    load_dotenv()

    # Create repositories
    fhir_repo: FHIRRepository = HAPIFHIRRepository() if not use_smart else create_smart_fhir_repository()
    vector_store: VectorStore = PGVectorAdapter(dsn=str(os.getenv("PGVECTOR_DSN")))
    llm_client = AnthropicClaudeClient()
    user_repo: UserRepository = PGUserRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
    
    # New EHR connection dependencies
    connection_repo: UserEHRConnectionRepository = PGUserEHRConnectionRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
    connection_service = UserEHRConnectionService(connection_repo)
    
    
    
    # Image service factory (creates per request with fresh repository)
    def create_image_service():
        dicom_processor = PyDICOMProcessor()
        image_storage = FileSystemImageStorage()
        image_repository = PostgreSQLImageRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
        return ImageServiceImpl(image_repository, image_storage, dicom_processor)

    # Main engine with connection service
    engine: DiagnosticEngine = LangGraphDiagnosticEngine(
        fhir_repo=fhir_repo,
        vector_store=vector_store,
        llm_client=llm_client,
        user_repo=user_repo,
        connection_service=connection_service
    )
    
    return engine, fhir_repo, vector_store, user_repo, connection_repo, connection_service, create_image_service