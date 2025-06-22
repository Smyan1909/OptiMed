from optimed.adapters.smart_fhir.repository import SMARTFHIRRepository
from optimed.core.ports import FHIRRepository

def create_smart_fhir_repository(
    base_url: str,
    client_id: str,
    client_secret: str = None,
    scope: str = "patient/*.read",
    token_url: str = None,
    redirect_uri: str = "http://localhost:8000/callback",
) -> FHIRRepository:
    """Create and return a SMART on FHIR repository instance."""
    return SMARTFHIRRepository(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        token_url=token_url,
        redirect_uri=redirect_uri,
    )