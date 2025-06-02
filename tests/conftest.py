# tests/conftest.py
import json
import pathlib
import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())

class FakeResp:
    """Mimics httpx.Response enough for our adapter."""
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self): ...
    def json(self): return self._payload

@pytest.fixture
def _load_fixture():
    return load_fixture