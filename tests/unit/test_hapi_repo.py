# tests/unit/test_hapi_repo.py
import pytest
import httpx
from typing import Any
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.core.domain import PatientContext
from conftest import FakeResp

@pytest.mark.asyncio
async def test_get_patient_stub(monkeypatch: Any, _load_fixture: Any) -> None:
    """Adapter returns a PatientContext when /Patient and /Observation calls succeed."""
    patient_json = _load_fixture("patient_example.json")
    vitals_json = _load_fixture("observations_vital.json")
    labs_json   = _load_fixture("observations_lab.json")

    # ----- monkey-patch sequence of calls -----
    call_log = []          # optional: see what the adapter asked for

    async def _fake_get(self, path: str, *_, **kwargs):
        call_log.append(path)

        if path.startswith("/Patient/"):
            return FakeResp(patient_json)

        params = kwargs.get("params", {})
        category = params.get("category")

        # Handle /Observation requests with different categories
        if path == "/Observation":
            if category == "vital-signs":
                return FakeResp(vitals_json)
            if category == "laboratory":
                return FakeResp(labs_json)
            # Return empty bundles for other observation categories
            if category in ["imaging", "exam", "procedure", "social-history"]:
                return FakeResp({"resourceType": "Bundle", "type": "searchset", "entry": []})

        # Handle other FHIR resource requests
        if path in ["/MedicationRequest", "/AllergyIntolerance", "/Condition"]:
            return FakeResp({"resourceType": "Bundle", "type": "searchset", "entry": []})

        raise AssertionError(f"Unexpected URL {path} with params={params}")
    
    monkeypatch.setattr(
        "optimed.adapters.fhir_hapi.repository.httpx.AsyncClient.get",
        _fake_get,
        raising=True,
    )

    # ----- run the method under test -----
    repo = HAPIFHIRRepository(base_url="https://stub")
    pat: PatientContext = await repo.get_patient("example")

    # ----- assertions -----
    assert pat.patient_id == "example"
    assert pat.name.startswith("Adam")
    assert pat.vitals == {}
    assert pat.labs == {}
    assert "/Patient/example" in call_log
    await repo.close()


@pytest.mark.asyncio
async def test_search_patients_stub(monkeypatch: Any, _load_fixture: Any) -> None:
    """Adapter returns a list[PatientContext] for /Patient?name= query."""
    bundle_json = {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": _load_fixture("patient_example.json")}],
    }

    async def _fake_get(self, path: str, *_, **kwargs):
        # Simulate patient‐by‐ID not found:
        if path.startswith("/Patient/"):
            # raise HTTPStatusError to trigger the except block in search_patients
            raise httpx.HTTPStatusError(
                "Not Found",
                request=httpx.Request("GET", path),
                response=httpx.Response(404),
            )
        # Otherwise return our name‐search bundle
        return FakeResp(bundle_json)

    monkeypatch.setattr(
        "optimed.adapters.fhir_hapi.repository.httpx.AsyncClient.get",
        _fake_get,
        raising=True,
    )

    repo = HAPIFHIRRepository(base_url="https://stub")
    results = await repo.search_patients("adam")
    await repo.close()

    assert len(results) == 1
    assert results[0].patient_id == "example"
