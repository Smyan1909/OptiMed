import os
from typing import Tuple, Callable, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv # type: ignore
from optimed.apps.orchestrator.patient_flow import LangGraphDiagnosticEngine
from optimed.apps.orchestrator.info_flow_ram import LangGraphRAMInformationEngine
from optimed.apps.orchestrator.connection_service import UserEHRConnectionService
from optimed.apps.orchestrator.image_flow import LangGraphImageAnalysisEngine
from optimed.apps.orchestrator.ml_adapters import MultilingualCrossEncoder, MultilingualZeroShotClassifier
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.adapters.smart_fhir.repository import SMARTFHIRRepository
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.openai_gpt.azure_gpt5_mini_client import AzureOpenAIGPT5MiniClient # type: ignore
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.adapters.user_repository.pg_ehr_connection_repository import PGUserEHRConnectionRepository
from optimed.adapters.dicom.pydicom_processor import PyDICOMProcessor
from optimed.adapters.dicom.image_service import ImageServiceImpl
from optimed.adapters.dicom.pg_image_repository import PostgreSQLImageRepository
from optimed.adapters.dicom.image_storage import FileSystemImageStorage
from optimed.adapters.dicom.image_embedding_service import DICOMImageEmbeddingService
from optimed.adapters.web_search.web_service import TavilyWebSearchService
from optimed.adapters.image_generation.stabilityai_client import StabilityAIClient
from optimed.adapters.image_generation.repository import PostgresGeneratedImageRepository
from optimed.adapters.pdf.pdf_processor import PyMuPDFProcessor
from optimed.adapters.xml.xml_processor import LibXML2Processor
from optimed.adapters.security.session_cleanup import initialize_cleanup_service
from optimed.adapters.note_templates import PGTemplateRepository, TemplateServiceAdapter, NoteGeneratorAdapter
from optimed.adapters.audit import PGAuditRepository
from optimed.apps.pdf.memory_pdf_service import MemoryPDFService
from optimed.apps.xml.memory_xml_service import MemoryXMLService
from optimed.core.domain import UserEHRConnection
from optimed.core.ports import DiagnosticEngine, FHIRRepository, VectorStore, UserRepository, UserEHRConnectionRepository, ImageAnalysisEngine, ImageGenerationService, GeneratedImageRepository, LLMClient, PDFService, XMLService, TemplateRepository, TemplateService, NoteGenerator, AuditRepository
from optimed.core.logging_utils import get_logger

logger = get_logger(__name__)


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


async def create_app_dependencies(use_smart=False) -> Tuple[DiagnosticEngine,
                                                      FHIRRepository,
                                                      VectorStore,
                                                      UserRepository,
                                                      UserEHRConnectionRepository,
                                                      UserEHRConnectionService,
                                                      Callable[[], ImageServiceImpl],
                                                      ImageAnalysisEngine,
                                                      Optional[ImageGenerationService],
                                                      Optional[GeneratedImageRepository],
                                                      LLMClient,
                                                      TavilyWebSearchService,
                                                      PDFService,
                                                      XMLService,
                                                      TemplateRepository,
                                                      TemplateService,
                                                      NoteGenerator,
                                                      AuditRepository]:
    """Factory function to wire up all application dependencies."""

    # Load environment variables from .env file
    load_dotenv()
    # Create repositories
    fhir_repo: FHIRRepository = HAPIFHIRRepository() if not use_smart else create_smart_fhir_repository()
    vector_store: VectorStore = PGVectorAdapter(
        dsn=str(os.getenv("PGVECTOR_DSN")),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "1024"))
    )
    # Use fast GPT-5 mini for general LLM (minimal reasoning effort)
    llm_client = AzureOpenAIGPT5MiniClient()
    journal_client = AzureOpenAIGPT5MiniClient()
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
            logger.info("Image generation service (Stability AI) initialized")
        except Exception as e:
            logger.warning(f"Could not initialize image generation service: {e}")

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

    # PDF service (memory-only for GDPR compliance)
    pdf_processor = PyMuPDFProcessor()
    pdf_service: PDFService = MemoryPDFService(pdf_processor)

    # XML service (memory-only for GDPR compliance)
    xml_processor = LibXML2Processor()
    xml_service: XMLService = MemoryXMLService(xml_processor)

    # Web search service
    web_search_service = TavilyWebSearchService(
        api_key=str(os.getenv("TAVILY_API_KEY")),
        llm_client=llm_client,
    )

    # Initialize ML models for intelligent retrieval
    logger.info("Initializing ML models for intelligent retrieval...")
    cross_encoder = MultilingualCrossEncoder()
    zero_shot_classifier = MultilingualZeroShotClassifier()
    logger.info("ML models initialized successfully")

    # Initialize GDPR compliance services
    logger.info("Initializing GDPR compliance services...")
    cleanup_service = initialize_cleanup_service(vector_store, user_repo)
    await cleanup_service.start_cleanup_service()
    logger.info("GDPR compliance services initialized")

    # Note template adapters (GDPR-compliant, no content storage)
    logger.info("Initializing note template services...")
    template_repo: TemplateRepository = PGTemplateRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
    template_service: TemplateService = TemplateServiceAdapter(template_repo=template_repo)
    note_generator: NoteGenerator = NoteGeneratorAdapter(template_repo=template_repo)
    logger.info("Note template services initialized")

    # Audit repository (GDPR-compliant logging)
    logger.info("Initializing audit logging services...")
    audit_repo: AuditRepository = PGAuditRepository(dsn=str(os.getenv("PGVECTOR_DSN")))
    logger.info("Audit logging services initialized")

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
    ) if os.getenv("NEXT_PUBLIC_INFO_MODE") == "false" else LangGraphRAMInformationEngine(
        fhir_repo=fhir_repo,
        vector_store=vector_store,
        llm_client=llm_client,
        user_repo=user_repo,
        connection_service=connection_service,
        web_search_service=web_search_service,
        cross_encoder=cross_encoder,
        zero_shot_classifier=zero_shot_classifier,
        pdf_service=pdf_service,
        xml_service=xml_service,
        audit_repo=audit_repo,
    )

    return (
        engine, fhir_repo, vector_store, user_repo, connection_repo,
        connection_service, create_image_service, image_analysis_engine,
        image_generation_service, generated_image_repo, journal_client,
        web_search_service, pdf_service, xml_service,
        template_repo, template_service, note_generator, audit_repo
    )


# Chunking orchestrator factory (for CLI or future wiring)
def create_chunking_orchestrator():
    from optimed.apps.orchestrator.chunking_orchestrator import ChunkingOrchestrator
    from optimed.apps.orchestrator.chunking_config import STRATEGY_REGISTRY, POLICY_PRESETS
    from optimed.adapters.outbound.tokenizer.whitespace_tokenizer import WhitespaceTokenizer
    from optimed.adapters.outbound.phi_redactor.simple_redactor import SimplePhiRedactor

    return ChunkingOrchestrator(
        tokenizer=WhitespaceTokenizer(),
        redactor=SimplePhiRedactor(),
        strategy_registry=STRATEGY_REGISTRY,
        policies=POLICY_PRESETS,
    )