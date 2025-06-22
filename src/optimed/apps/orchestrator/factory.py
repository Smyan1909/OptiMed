import os
from typing import Tuple
from optimed.apps.orchestrator.patient_flow import LangGraphDiagnosticEngine
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.adapters.smart_fhir.factory import create_smart_fhir_repository
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.core.ports import DiagnosticEngine, FHIRRepository, VectorStore, UserRepository
from dotenv import load_dotenv # type: ignore


def create_app_dependencies(use_smart=False) -> Tuple[DiagnosticEngine, FHIRRepository, VectorStore, UserRepository]:
    """Factory function to wire up all application dependencies."""

    # Load environment variables from .env file
    load_dotenv()

    if use_smart:
        base_url = os.getenv("SMART_FHIR_BASE_URL")
        client_id = os.getenv("SMART_FHIR_CLIENT_ID")
        client_secret = os.getenv("SMART_FHIR_CLIENT_SECRET")
        fhir_repo = create_smart_fhir_repository(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret
        )
    else:
        fhir_repo = HAPIFHIRRepository()
    vector_store = PGVectorAdapter(str(os.getenv("PGVECTOR_DSN")))
    llm_client = AnthropicClaudeClient()
    user_repo = PGUserRepository(str(os.getenv("PGVECTOR_DSN")))
    
    diagnostic_engine = LangGraphDiagnosticEngine(
        fhir_repo=fhir_repo,
        vector_store=vector_store,
        llm_client=llm_client,
        user_repo=user_repo,
    )
    
    return diagnostic_engine, fhir_repo, vector_store, user_repo