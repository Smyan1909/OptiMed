import os
from typing import Tuple
from optimed.apps.orchestrator.patient_flow import LangGraphDiagnosticEngine
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient
from optimed.core.ports import DiagnosticEngine, FHIRRepository
from dotenv import load_dotenv # type: ignore


def create_app_dependencies() -> Tuple[DiagnosticEngine, FHIRRepository]:
    """Factory function to wire up all application dependencies."""

    # Load environment variables from .env file
    load_dotenv()

    fhir_repo = HAPIFHIRRepository()
    vector_store = PGVectorAdapter(os.getenv("PGVECTOR_DSN"))
    llm_client = AnthropicClaudeClient()

    
    diagnostic_engine = LangGraphDiagnosticEngine(
        fhir_repo=fhir_repo,
        vector_store=vector_store,
        llm_client=llm_client,
    )
    
    return diagnostic_engine, fhir_repo