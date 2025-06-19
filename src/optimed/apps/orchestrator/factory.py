import os
from typing import Tuple
from optimed.apps.orchestrator.patient_flow import LangGraphDiagnosticEngine
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.core.ports import DiagnosticEngine, FHIRRepository, VectorStore, UserRepository
from dotenv import load_dotenv # type: ignore


def create_app_dependencies() -> Tuple[DiagnosticEngine, FHIRRepository, VectorStore, UserRepository]:
    """Factory function to wire up all application dependencies."""

    # Load environment variables from .env file
    load_dotenv()

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