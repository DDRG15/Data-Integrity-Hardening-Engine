"""
Tests for the dih-engine API service (Tier 2, phase 3a).

Auth contract: every data endpoint requires X-API-Key. /health does not --
liveness probes cannot carry secrets. Fail-closed: no server-side key = 503.
"""
import time

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


class TestExtractEndpoint:
    _VALID_TEXT = (
        "ID: ABC-001 PRODUCT: Industrial Press PRICE: S/ 1499.90 Stock 4\n"
        "garbage line that matches nothing\n"
        "ID: XYZ-002 PRODUCT: Hydraulic Pump PRICE: S/ 850.00 Stock 12\n"
    )

    def test_requires_api_key(self, client):
        resp = client.post("/extract", json={"text": self._VALID_TEXT})
        assert resp.status_code == 401

    def test_happy_path_records_and_audit(self, client):
        resp = client.post("/extract", json={"text": self._VALID_TEXT}, headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["audit"] == {"total": 3, "matched": 2, "skipped": 1}
        assert len(body["records"]) == 2
        assert body["records"][0]["ID"] == "ABC-001"
        assert body["records"][0]["Name"] == "Industrial Press"
        assert body["records"][1]["ID"] == "XYZ-002"

    def test_all_noise_returns_empty_records(self, client):
        resp = client.post("/extract", json={"text": "nothing\nuseful\nhere\n"}, headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["records"] == []
        assert body["audit"]["matched"] == 0
        assert body["audit"]["total"] == 3

    def test_empty_text_rejected_422(self, client):
        resp = client.post("/extract", json={"text": ""}, headers=AUTH)
        assert resp.status_code == 422

    def test_disk_abort_returns_507(self, client, monkeypatch):
        # Server disk above threshold: the engine refuses to start and the API
        # must surface that as 507, never a 200 with silently empty records.
        monkeypatch.setattr(
            "src.dih_engine.api.app.bulletproof_processor",
            lambda *a, **k: {"total": 0, "matched": 0, "skipped": 0, "aborted": True},
        )
        resp = client.post("/extract", json={"text": self._VALID_TEXT}, headers=AUTH)
        assert resp.status_code == 507


class TestAsyncJobs:
    _TEXT = (
        "ID: ABC-001 PRODUCT: Industrial Press PRICE: S/ 1499.90 Stock 4\n"
        "noise line\n"
        "ID: XYZ-002 PRODUCT: Hydraulic Pump PRICE: S/ 850.00 Stock 12\n"
    )

    @staticmethod
    def _wait_for_terminal(client, job_id, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = client.get(f"/jobs/{job_id}", headers=AUTH).json()
            if body["status"] in ("done", "failed"):
                return body
            time.sleep(0.05)
        pytest.fail(f"job {job_id} did not reach a terminal state in {timeout}s")

    def test_submit_returns_202_with_job_id(self, client):
        resp = client.post("/extract/async", json={"text": self._TEXT}, headers=AUTH)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        assert len(body["job_id"]) == 32  # uuid4 hex

    def test_job_completes_with_same_contract_as_sync_extract(self, client):
        job_id = client.post("/extract/async", json={"text": self._TEXT}, headers=AUTH).json()["job_id"]
        body = self._wait_for_terminal(client, job_id)
        assert body["status"] == "done"
        assert body["error"] is None
        # The async result must honor the exact same reconciliation contract
        # as the sync endpoint -- counts, not just a 200.
        assert body["result"]["audit"] == {"total": 3, "matched": 2, "skipped": 1}
        assert [r["ID"] for r in body["result"]["records"]] == ["ABC-001", "XYZ-002"]

    def test_failed_job_reports_error_not_silence(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.dih_engine.api.app._run_extraction",
            lambda text: (_ for _ in ()).throw(RuntimeError("engine exploded mid-run")),
        )
        job_id = client.post("/extract/async", json={"text": self._TEXT}, headers=AUTH).json()["job_id"]
        body = self._wait_for_terminal(client, job_id)
        assert body["status"] == "failed"
        assert "engine exploded" in body["error"]
        assert body["result"] is None

    def test_unknown_job_returns_404(self, client):
        resp = client.get("/jobs/deadbeefdeadbeefdeadbeefdeadbeef", headers=AUTH)
        assert resp.status_code == 404

    def test_both_endpoints_require_api_key(self, client):
        assert client.post("/extract/async", json={"text": self._TEXT}).status_code == 401
        assert client.get("/jobs/abc123").status_code == 401
