import concurrent.futures
import time
from unittest.mock import patch

import pandas as pd
import requests

from src.dih_engine.recon.seer import clean_and_optimize_map, ProbeResult


class FakeFuture:
    def __init__(self, url):
        self._url = url

    def done(self):
        return False

    def result(self):
        raise RuntimeError("no result")


class FakeExecutor:
    def __init__(self, *args, **kwargs):
        self._futures = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, url):
        f = FakeFuture(url)
        self._futures.append(f)
        return f


def test_clean_and_optimize_map_handles_threadpool_timeout(tmp_path, monkeypatch):
    input_csv = tmp_path / "urls.csv"
    input_csv.write_text("URL,Nombre Categoria\nhttps://a.com,A\nhttps://b.com,B\n")
    output_csv = tmp_path / "output.csv"

    # Patch ThreadPoolExecutor to our fake and make as_completed raise TimeoutError
    monkeypatch.setattr("src.dih_engine.recon.seer.ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr("src.dih_engine.recon.seer.as_completed", lambda futures, timeout=None: (_ for _ in ()).throw(concurrent.futures.TimeoutError()))

    with patch("src.dih_engine.recon.seer.notify_all"):
        clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=1, sample_size=2)

    assert output_csv.exists()
    df = pd.read_csv(str(output_csv))
    statuses = set(df["Status"].tolist())
    assert "timeout" in statuses
    assert df.shape[0] == 2


def test_flaresolverr_error_path_returns_http_other(monkeypatch):
    # Simulate FlareSolverr returning status 'error' with a message
    from src.dih_engine.recon.modules import flaresolverr_probe

    monkeypatch.setenv("FLARE_SOLVER_URL", "http://localhost:8191/v1")

    mock_response = type("R", (), {})()
    mock_response.status_code = 200

    def raise_for_status():
        return None

    mock_response.raise_for_status = raise_for_status

    def json():
        return {"status": "error", "message": "Challenge timed out"}

    mock_response.json = json

    with patch("src.dih_engine.recon.modules.flaresolverr_probe.requests.post", return_value=mock_response):
        result = flaresolverr_probe.probe("http://example.com", timeout=10)

    assert result["status"] == "http_other"
    assert "Challenge timed out" in result["error_detail"]
