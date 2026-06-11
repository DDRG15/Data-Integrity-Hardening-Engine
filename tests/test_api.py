"""
Tests for the dih-engine API service (Tier 2, phase 3a).

Auth contract: every data endpoint requires X-API-Key. /health does not --
liveness probes cannot carry secrets. Fail-closed: no server-side key = 503.
"""
import pytest
from fastapi.testclient import TestClient

from src.dih_engine.api import create_app

TEST_KEY = "test-key-for-api-tests"
AUTH = {"X-API-Key": TEST_KEY}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DIH_API_KEY", TEST_KEY)
    return TestClient(create_app())


@pytest.fixture
def client_no_server_key(monkeypatch):
    monkeypatch.delenv("DIH_API_KEY", raising=False)
    return TestClient(create_app())


class TestHealth:
    def test_health_requires_no_auth(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["version"]  # non-empty version string

    def test_health_works_even_without_server_key(self, client_no_server_key):
        # Liveness must not depend on auth configuration -- a probe that 503s
        # on a missing key would restart-loop the container forever.
        assert client_no_server_key.get("/health").status_code == 200


class TestAuthGate:
    def test_missing_key_returns_401(self, client):
        resp = client.post("/sanitize", json={"line": "01234 ITEM 14.50"})
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, client):
        resp = client.post(
            "/sanitize",
            json={"line": "01234 ITEM 14.50"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_no_server_key_fails_closed_with_503(self, client_no_server_key):
        # Operator forgot DIH_API_KEY: the API must refuse to run open,
        # even when the caller presents some key.
        resp = client_no_server_key.post(
            "/sanitize",
            json={"line": "01234 ITEM 14.50"},
            headers={"X-API-Key": "anything"},
        )
        assert resp.status_code == 503


class TestSanitizeEndpoint:
    def test_approved_record(self, client):
        resp = client.post("/sanitize", json={"line": "O01234 SOME PRODUCT 14.50"}, headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"id": "001234", "amount": "14.50", "status": "APPROVED"}

    def test_noise_line_returns_noise_status(self, client):
        resp = client.post("/sanitize", json={"line": "TOTAL 500.00"}, headers=AUTH)
        assert resp.status_code == 200
        assert resp.json() == {"id": None, "amount": None, "status": "NOISE"}

    def test_partial_record(self, client):
        resp = client.post("/sanitize", json={"line": "01234 PRODUCT WITH NO PRICE"}, headers=AUTH)
        body = resp.json()
        assert body["status"] == "PARTIAL"
        assert body["id"] == "01234"
        assert body["amount"] is None

    def test_european_amount_normalized_end_to_end(self, client):
        # The locale feature must survive the full HTTP round trip.
        resp = client.post("/sanitize", json={"line": "01234 INDUSTRIAL PRESS 1.234,50"}, headers=AUTH)
        body = resp.json()
        assert body["status"] == "APPROVED"
        assert body["amount"] == "1234.50"

    def test_oversized_line_rejected_422(self, client):
        resp = client.post("/sanitize", json={"line": "X" * 10_001}, headers=AUTH)
        assert resp.status_code == 422

    def test_missing_line_field_rejected_422(self, client):
        resp = client.post("/sanitize", json={}, headers=AUTH)
        assert resp.status_code == 422
