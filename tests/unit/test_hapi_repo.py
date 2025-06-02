# tests/unit/test_hapi_repo.py
import pytest, types
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.core.domain import PatientContext
from conftest import FakeResp

@pytest.mark.asyncio
async def test_get_patient_stub(monkeypatch, _load_fixture):
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

        if category == "vital-signs":
            return FakeResp(vitals_json)
        if category == "laboratory":
            return FakeResp(labs_json)

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
async def test_search_patients_stub(monkeypatch, _load_fixture):
    """Adapter returns a list[PatientContext] for /Patient?name= query."""
    bundle_json = {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": _load_fixture("patient_example.json")}],
    }

    async def _fake_get(self, path: str, *_, **kwargs):
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
