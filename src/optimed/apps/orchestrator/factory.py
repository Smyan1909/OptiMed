import os
from typing import Tuple, Callable, Optional
from optimed.apps.orchestrator.patient_flow import LangGraphDiagnosticEngine
from optimed.apps.orchestrator.connection_service import UserEHRConnectionService
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.adapters.smart_fhir.repository import SMARTFHIRRepository
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.quen3_sft.client import IIMedicalClient
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.adapters.user_repository.pg_ehr_connection_repository import PGUserEHRConnectionRepository
from optimed.core.ports import DiagnosticEngine, FHIRRepository, VectorStore, UserRepository, UserEHRConnectionRepository, ImageAnalysisEngine, ImageGenerationService, GeneratedImageRepository
from optimed.adapters.dicom.pydicom_processor import PyDICOMProcessor
from optimed.adapters.dicom.image_service import ImageServiceImpl
from optimed.adapters.dicom.pg_image_repository import PostgreSQLImageRepository
from optimed.adapters.dicom.image_storage import FileSystemImageStorage
from optimed.adapters.dicom.image_embedding_service import DICOMImageEmbeddingService
from optimed.adapters.web_search.web_service import TavilyWebSearchService
from optimed.adapters.image_generation.stabilityai_client import StabilityAIClient
from optimed.adapters.image_generation.repository import PostgresGeneratedImageRepository
from optimed.apps.orchestrator.image_flow import LangGraphImageAnalysisEngine
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


def create_app_dependencies(use_smart=False) -> Tuple[DiagnosticEngine, 
                                                      FHIRRepository, 
                                                      VectorStore, 
                                                      UserRepository, 
                                                      UserEHRConnectionRepository, 
                                                      UserEHRConnectionService, 
                                                      Callable[[], ImageServiceImpl], 
                                                      ImageAnalysisEngine,
                                                      Optional[ImageGenerationService],
                                                      Optional[GeneratedImageRepository]]:
    """Factory function to wire up all application dependencies."""

    # Load environment variables from .env file
    load_dotenv()
    # Create repositories
    fhir_repo: FHIRRepository = HAPIFHIRRepository() if not use_smart else create_smart_fhir_repository()
    vector_store: VectorStore = PGVectorAdapter(dsn=str(os.getenv("PGVECTOR_DSN")))
    llm_client = IIMedicalClient()
    user_repo: UserRepository = PGUserRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
    
    # Initialize image generation service if configured
    image_generation_service: Optional[ImageGenerationService] = None
    generated_image_repo: Optional[GeneratedImageRepository] = None

    stability_api_key = os.getenv("STABILITY_API_KEY")
    if stability_api_key and os.getenv("IMAGE_GENERATION_ENABLED", "false").lower() == "true":
        try:
            image_generation_service = StabilityAIClient(
                api_key=stability_api_key,
                llm_client=llm_client
            )
            generated_image_repo = PostgresGeneratedImageRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
            print("Image generation service (Stability AI) initialized")
        except Exception as e:
            print(f"Warning: Could not initialize image generation service: {e}")

    # New EHR connection dependencies
    connection_repo: UserEHRConnectionRepository = PGUserEHRConnectionRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
    connection_service = UserEHRConnectionService(connection_repo)
    

    # DICOM embedding service with vision transformer
    image_embedding_service = DICOMImageEmbeddingService(
        model_name=os.getenv("VISION_MODEL_NAME", "microsoft/swin-base-patch4-window7-224")
    )

    # Image analysis engine
    image_analysis_engine: ImageAnalysisEngine = LangGraphImageAnalysisEngine(
        llm_client=llm_client,
        fhir_repo=fhir_repo,
        vector_store=vector_store,
        embedding_service=image_embedding_service,
        user_repo=user_repo,
        connection_service=connection_service,
    )
    
    # Image service factory (creates per request with fresh repository)
    def create_image_service():
        dicom_processor = PyDICOMProcessor()
        image_storage = FileSystemImageStorage()
        image_repository = PostgreSQLImageRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
        return ImageServiceImpl(image_repository, image_storage, dicom_processor, image_embedding_service, vector_store)


    # Web search service
    web_search_service = TavilyWebSearchService(
        api_key=str(os.getenv("TAVILY_API_KEY")),
        llm_client=llm_client,
    )

    # Main engine with connection service
    engine: DiagnosticEngine = LangGraphDiagnosticEngine(
        fhir_repo=fhir_repo,
        vector_store=vector_store,
        llm_client=llm_client,
        user_repo=user_repo,
        connection_service=connection_service,
        web_search_service=web_search_service,
        image_generation_service=image_generation_service,
        generated_image_repo=generated_image_repo,
    )
    
    return engine, fhir_repo, vector_store, user_repo, connection_repo, connection_service, create_image_service, image_analysis_engine, image_generation_service, generated_image_repo