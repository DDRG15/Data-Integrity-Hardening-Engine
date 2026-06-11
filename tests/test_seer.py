import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.dih_engine.recon.modules.flaresolverr_probe import probe as flaresolverr_probe
from src.dih_engine.recon.modules.proxy_probe import _via_generic_proxy, _via_scrapfly, probe as proxy_probe
import pandas as pd

from src.dih_engine.recon.seer import (
    ProbeResult,
    _build_probe_result,
    _disk_path,
    _identify_stack,
    _is_valid_url,
    _majority_stack,
    analyze_tech_stack,
    clean_and_optimize_map,
    locate_gold_mines,
)

_NO_SLEEP = lambda _: None  # noqa: E731


class TestDiskPath:
    def test_windows_path_does_not_use_forward_slash(self, monkeypatch):
        # Regression: bug #2 -- psutil.disk_usage('/') crashes on Windows
        monkeypatch.setattr("src.dih_engine.recon.seer.sys.platform", "win32")
        monkeypatch.setattr(
            "src.dih_engine.recon.seer.sys.executable", r"C:\Python311\python.exe"
        )
        path = _disk_path()
        assert path != "/"
        assert path.endswith("\\")

    def test_unix_path_is_root(self, monkeypatch):
        monkeypatch.setattr("src.dih_engine.recon.seer.sys.platform", "linux")
        assert _disk_path() == "/"


class TestIdentifyStack:
    def test_detects_nextjs(self):
        html = '<script id="__NEXT_DATA__">{"props":{"pageProps":{}}}</script>'
        tech, _ = _identify_stack(html, "text/html")
        assert "Next.js" in tech

    def test_detects_react(self):
        tech, _ = _identify_stack('<div data-reactroot=""></div>', "text/html")
        assert "React" in tech

    def test_detects_vtex(self):
        tech, _ = _identify_stack('<div class="vtex-store"></div>', "text/html")
        assert "VTEX" in tech

    def test_detects_json_api(self):
        tech, _ = _identify_stack("{}", "application/json")
        assert "JSON API" in tech

    def test_falls_back_to_static_html(self):
        tech, _ = _identify_stack("<html><body>Hello</body></html>", "text/html")
        assert "Static HTML" in tech


class TestBuildProbeResult:
    def test_ok_fetch_returns_ok_result(self):
        fetch = {
            "status": "ok",
            "html": "<html><body>Hello world</body></html>",
            "content_type": "text/html",
            "error_detail": "",
        }
        result = _build_probe_result("http://example.com", fetch)
        assert result.status == "ok"
        assert result.tech == "Static HTML"
        assert result.fallback_module == ""

    def test_403_fetch_maps_to_curl_cffi_fallback(self):
        fetch = {"status": "http_403", "html": "", "content_type": "", "error_detail": "Forbidden"}
        result = _build_probe_result("http://example.com", fetch)
        assert result.status == "http_403"
        assert result.fallback_module == "curl_cffi"

    def test_429_fetch_maps_to_delay_retry_fallback(self):
        fetch = {"status": "http_429", "html": "", "content_type": "", "error_detail": "Rate Limited"}
        result = _build_probe_result("http://example.com", fetch)
        assert result.fallback_module == "delay_retry"

    def test_timeout_maps_to_delay_retry_fallback(self):
        fetch = {"status": "timeout", "html": "", "content_type": "", "error_detail": "timeout after 10s"}
        result = _build_probe_result("http://example.com", fetch)
        assert result.fallback_module == "delay_retry"

    def test_js_required_maps_to_playwright_fallback(self):
        fetch = {"status": "js_required", "html": "<div id='root'></div>", "content_type": "text/html", "error_detail": "empty CSR shell"}
        result = _build_probe_result("http://example.com", fetch)
        assert result.fallback_module == "playwright"

    def test_connection_error_has_no_fallback(self):
        fetch = {"status": "connection_error", "html": "", "content_type": "", "error_detail": "DNS failure"}
        result = _build_probe_result("http://example.com", fetch)
        assert result.fallback_module == ""

    def test_401_is_terminal_no_fallback(self):
        fetch = {"status": "http_401", "html": "", "content_type": "", "error_detail": "HTTP 401 Unauthorized"}
        result = _build_probe_result("http://example.com", fetch)
        assert result.status == "http_401"
        assert result.fallback_module == ""

    def test_521_maps_to_curl_cffi_fallback(self):
        fetch = {"status": "http_521", "html": "", "content_type": "", "error_detail": "HTTP 521 Web Server Down"}
        result = _build_probe_result("http://example.com", fetch)
        assert result.status == "http_521"
        assert result.fallback_module == "curl_cffi"


class TestAnalyzeTechStack:
    def test_happy_path_returns_ok_probe_result(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Static page with enough content to not be a JS shell</body></html>"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert isinstance(result, ProbeResult)
        assert result.status == "ok"
        assert isinstance(result.tech, str)
        assert isinstance(result.strategy, str)
        assert isinstance(result.mines, list)

    def test_connection_error_returns_error_result(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("refused")

        result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert isinstance(result, ProbeResult)
        assert result.status == "connection_error"

    def test_timeout_returns_error_result_with_delay_retry(self):
        mock_session = MagicMock()
        # First call times out, second (retry) also times out
        mock_session.get.side_effect = requests.exceptions.Timeout()

        result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert isinstance(result, ProbeResult)
        assert result.status == "timeout"
        assert result.fallback_module == "delay_retry"

    def test_403_triggers_curl_cffi_fallback(self):
        http_error = requests.exceptions.HTTPError(response=MagicMock(status_code=403))
        mock_session = MagicMock()
        mock_session.get.side_effect = http_error

        # Simulate curl_cffi also blocked (persistent WAF) so proxy is tried next
        curlffi_blocked = {"status": "http_403", "html": "", "content_type": "", "error_detail": "HTTP 403"}
        fs_blocked = {"status": "module_unavailable", "html": "", "content_type": "", "error_detail": "not configured"}
        proxy_blocked = {"status": "module_unavailable", "html": "", "content_type": "", "error_detail": "no proxy configured"}
        with patch("src.dih_engine.recon.seer.curlffi_probe.probe", return_value=curlffi_blocked), \
             patch("src.dih_engine.recon.seer.flaresolverr_probe.probe", return_value=fs_blocked), \
             patch("src.dih_engine.recon.seer.proxy_probe.probe", return_value=proxy_blocked):
            result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert isinstance(result, ProbeResult)
        assert result.status == "http_403"
        assert result.fallback_module == "curl_cffi"

    def test_401_is_terminal_not_retried(self):
        http_error = requests.exceptions.HTTPError(response=MagicMock(status_code=401))
        mock_session = MagicMock()
        mock_session.get.side_effect = http_error

        result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert result.status == "http_401"
        assert result.fallback_module == ""

    def test_521_triggers_curl_cffi_fallback(self):
        http_error = requests.exceptions.HTTPError(response=MagicMock(status_code=521))
        mock_session = MagicMock()
        mock_session.get.side_effect = http_error

        curlffi_ok = {"status": "ok", "html": "<html><body>Rescued by curl_cffi</body></html>", "content_type": "text/html", "error_detail": ""}
        with patch("src.dih_engine.recon.seer.curlffi_probe.probe", return_value=curlffi_ok):
            result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert result.status == "ok"
        assert result.tech == "Static HTML"

    def test_keyboard_interrupt_propagates(self):
        # KeyboardInterrupt must NOT be swallowed -- regression for bare except: removal
        mock_session = MagicMock()
        mock_session.get.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)

    def test_playwright_fallback_success(self):
        first_fetch = {
            "status": "js_required",
            "html": "",
            "content_type": "text/html",
            "error_detail": "JavaScript shell detected",
        }
        play_fetch = {
            "status": "ok",
            "html": "<html><body>Rendered by Playwright</body></html>",
            "content_type": "text/html",
            "error_detail": "",
        }
        with patch("src.dih_engine.recon.seer.requests_probe.probe", return_value=first_fetch), \
             patch("src.dih_engine.recon.seer.playwright_probe.probe", return_value=play_fetch):
            result = analyze_tech_stack("http://example.com", session=None, _sleep_fn=_NO_SLEEP)

        assert result.status == "ok"
        assert result.error_detail == ""
        assert result.tech == "Static HTML"

    def test_delay_retry_success(self):
        first_fetch = {
            "status": "timeout",
            "html": "",
            "content_type": "",
            "error_detail": "timeout after 10s",
        }
        retry_fetch = {
            "status": "ok",
            "html": "<html><body>Delay retry success</body></html>",
            "content_type": "text/html",
            "error_detail": "",
        }
        with patch("src.dih_engine.recon.seer.requests_probe.probe", side_effect=[first_fetch, retry_fetch]):
            result = analyze_tech_stack("http://example.com", session=None, _sleep_fn=_NO_SLEEP)

        assert result.status == "ok"
        assert result.error_detail == ""
        assert result.tech == "Static HTML"

    def test_curl_cffi_flaresolverr_proxy_success(self):
        first_fetch = {
            "status": "http_403",
            "html": "",
            "content_type": "",
            "error_detail": "HTTP 403 Forbidden",
        }
        curlffi_blocked = {
            "status": "http_403",
            "html": "",
            "content_type": "",
            "error_detail": "curl_cffi blocked",
        }
        flaresolverr_blocked = {
            "status": "module_unavailable",
            "html": "",
            "content_type": "",
            "error_detail": "FlareSolverr not configured",
        }
        proxy_ok = {
            "status": "ok",
            "html": "<html><body>Proxy fallback success</body></html>",
            "content_type": "text/html",
            "error_detail": "",
        }

        with patch("src.dih_engine.recon.seer.requests_probe.probe", return_value=first_fetch), \
             patch("src.dih_engine.recon.seer.curlffi_probe.probe", return_value=curlffi_blocked), \
             patch("src.dih_engine.recon.seer.flaresolverr_probe.probe", return_value=flaresolverr_blocked), \
             patch("src.dih_engine.recon.seer.proxy_probe.probe", return_value=proxy_ok):
            result = analyze_tech_stack("http://example.com", session=None, _sleep_fn=_NO_SLEEP)

        assert result.status == "ok"
        assert result.error_detail == ""
        assert result.tech == "Static HTML"


class TestMajorityStack:
    def test_clear_majority_selected(self):
        results = [
            ProbeResult(url="http://a.com", status="ok", tech="Static HTML", strategy="BeautifulSoup", mines=["found 5"]),
            ProbeResult(url="http://b.com", status="ok", tech="Static HTML", strategy="BeautifulSoup", mines=["found 8"]),
            ProbeResult(url="http://c.com", status="ok", tech="React.js (CSR)", strategy="Selenium", mines=["found 2"]),
        ]
        winner = _majority_stack(results)
        assert winner.tech == "Static HTML"

    def test_no_majority_still_returns_result(self):
        results = [
            ProbeResult(url="http://a.com", status="ok", tech="Static HTML", strategy="BeautifulSoup", mines=[]),
            ProbeResult(url="http://b.com", status="ok", tech="React.js (CSR)", strategy="Selenium", mines=[]),
            ProbeResult(url="http://c.com", status="ok", tech="Next.js (SSR)", strategy="Parse JSON", mines=[]),
        ]
        winner = _majority_stack(results)
        assert isinstance(winner.tech, str)


class TestLocateGoldMines:
    def test_finds_article_tags(self):
        html = "<html>" + "<article>item</article>" * 15 + "</html>"
        mines = locate_gold_mines(html)
        assert any("article" in m for m in mines)

    def test_returns_fallback_for_sparse_html(self):
        mines = locate_gold_mines("<html><body><p>Hello</p></body></html>")
        assert "No obvious" in mines[0]


class TestFlareSolverrProbe:
    def test_no_config_returns_module_unavailable(self, monkeypatch):
        monkeypatch.delenv("FLARE_SOLVER_URL", raising=False)
        result = flaresolverr_probe("http://example.com")
        assert result["status"] == "module_unavailable"
        assert "FLARE_SOLVER_URL" in result["error_detail"]

    def test_success_returns_ok(self, monkeypatch):
        monkeypatch.setenv("FLARE_SOLVER_URL", "http://localhost:8191/v1")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "ok",
            "solution": {"status": 200, "response": "<html><body>Solved page</body></html>"},
        }
        with patch("src.dih_engine.recon.modules.flaresolverr_probe.requests.post", return_value=mock_response):
            result = flaresolverr_probe("http://example.com", timeout=10)
        assert result["status"] == "ok"
        assert "Solved" in result["html"]

    def test_container_not_running_returns_unavailable(self, monkeypatch):
        monkeypatch.setenv("FLARE_SOLVER_URL", "http://localhost:8191/v1")
        with patch(
            "src.dih_engine.recon.modules.flaresolverr_probe.requests.post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            result = flaresolverr_probe("http://example.com", timeout=10)
        assert result["status"] == "module_unavailable"
        assert "docker" in result["error_detail"].lower()

    def test_flaresolverr_challenge_failed_returns_error(self, monkeypatch):
        monkeypatch.setenv("FLARE_SOLVER_URL", "http://localhost:8191/v1")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "error",
            "message": "Challenge not solved within timeout",
        }
        with patch("src.dih_engine.recon.modules.flaresolverr_probe.requests.post", return_value=mock_response):
            result = flaresolverr_probe("http://example.com", timeout=10)
        assert result["status"] == "http_other"
        assert "Challenge" in result["error_detail"]


class TestProxyProbe:
    def test_no_config_returns_module_unavailable(self, monkeypatch):
        monkeypatch.delenv("DIH_PROXY_URL", raising=False)
        monkeypatch.delenv("SCRAPFLY_API_KEY", raising=False)
        result = proxy_probe("http://example.com")
        assert result["status"] == "module_unavailable"
        assert "DIH_PROXY_URL" in result["error_detail"]

    def test_generic_proxy_success(self, monkeypatch):
        monkeypatch.setenv("DIH_PROXY_URL", "http://proxy.example.com:8080")
        monkeypatch.delenv("SCRAPFLY_API_KEY", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Rescued page</body></html>"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", return_value=mock_response):
            result = _via_generic_proxy("http://example.com", "http://proxy.example.com:8080", timeout=10)

        assert result["status"] == "ok"
        assert "Rescued" in result["html"]

    def test_generic_proxy_403_returns_error(self, monkeypatch):
        http_error = requests.exceptions.HTTPError(response=MagicMock(status_code=403))
        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", side_effect=http_error):
            result = _via_generic_proxy("http://example.com", "http://proxy.example.com:8080", timeout=10)
        assert result["status"] == "http_403"

    def test_scrapfly_success(self, monkeypatch):
        monkeypatch.delenv("DIH_PROXY_URL", raising=False)
        monkeypatch.setenv("SCRAPFLY_API_KEY", "scp-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "content": "<html><body>Scrapfly page</body></html>",
                "response_headers": {"content-type": "text/html"},
            }
        }

        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", return_value=mock_response):
            result = _via_scrapfly("http://example.com", "scp-test-key", timeout=10)

        assert result["status"] == "ok"
        assert "Scrapfly" in result["html"]

    def test_scrapfly_empty_content_returns_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": {"content": "", "response_headers": {}}}

        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", return_value=mock_response):
            result = _via_scrapfly("http://example.com", "scp-test-key", timeout=10)

        assert result["status"] == "http_other"
        assert "empty" in result["error_detail"]

    def test_scrapfly_401_returns_invalid_api_key(self):
        error_response = MagicMock()
        error_response.status_code = 401
        http_error = requests.exceptions.HTTPError(response=error_response)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_error

        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", return_value=mock_response):
            result = _via_scrapfly("http://example.com", "scp-test-key", timeout=10)

        assert result["status"] == "http_other"
        assert "invalid API key" in result["error_detail"]

    def test_scrapfly_429_returns_quota_exceeded(self):
        error_response = MagicMock()
        error_response.status_code = 429
        http_error = requests.exceptions.HTTPError(response=error_response)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_error

        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", return_value=mock_response):
            result = _via_scrapfly("http://example.com", "scp-test-key", timeout=10)

        assert result["status"] == "http_429"
        assert "quota exceeded" in result["error_detail"]

    def test_scrapfly_generic_http_error_returns_http_other(self):
        error_response = MagicMock()
        error_response.status_code = 503
        http_error = requests.exceptions.HTTPError(response=error_response)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_error

        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", return_value=mock_response):
            result = _via_scrapfly("http://example.com", "scp-test-key", timeout=10)

        assert result["status"] == "http_other"
        assert "HTTP 503" in result["error_detail"]

    def test_scrapfly_exception_returns_http_other(self):
        with patch(
            "src.dih_engine.recon.modules.proxy_probe.requests.get",
            side_effect=requests.exceptions.RequestException("network failure"),
        ):
            result = _via_scrapfly("http://example.com", "scp-test-key", timeout=10)

        assert result["status"] == "http_other"
        assert "scrapfly: network failure" in result["error_detail"]

    def test_proxy_probe_prefers_generic_proxy(self, monkeypatch):
        monkeypatch.setenv("DIH_PROXY_URL", "http://proxy.example.com:8080")
        monkeypatch.delenv("SCRAPFLY_API_KEY", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Rescued page</body></html>"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", return_value=mock_response):
            result = proxy_probe("http://example.com")

        assert result["status"] == "ok"

    def test_proxy_probe_uses_scrapfly_when_generic_proxy_missing(self, monkeypatch):
        monkeypatch.delenv("DIH_PROXY_URL", raising=False)
        monkeypatch.setenv("SCRAPFLY_API_KEY", "scp-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "content": "<html><body>Scrapfly page</body></html>",
                "response_headers": {"content-type": "text/html"},
            }
        }

        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", return_value=mock_response):
            result = proxy_probe("http://example.com")

        assert result["status"] == "ok"
        assert "Scrapfly" in result["html"]

    def test_full_chain_error_detail_has_all_three_layers(self, monkeypatch):
        # When requests AND curl_cffi both 403, proxy should be attempted third
        monkeypatch.delenv("DIH_PROXY_URL", raising=False)
        monkeypatch.delenv("SCRAPFLY_API_KEY", raising=False)

        http_error = requests.exceptions.HTTPError(response=MagicMock(status_code=403))
        mock_session = MagicMock()
        mock_session.get.side_effect = http_error

        curlffi_blocked = {"status": "http_403", "html": "", "content_type": "", "error_detail": "HTTP 403"}
        fs_blocked = {"status": "module_unavailable", "html": "", "content_type": "", "error_detail": "FlareSolverr not configured"}
        proxy_blocked = {"status": "module_unavailable", "html": "", "content_type": "", "error_detail": "no proxy configured"}
        with patch("src.dih_engine.recon.seer.curlffi_probe.probe", return_value=curlffi_blocked), \
             patch("src.dih_engine.recon.seer.flaresolverr_probe.probe", return_value=fs_blocked), \
             patch("src.dih_engine.recon.seer.proxy_probe.probe", return_value=proxy_blocked):
            result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)

        # All four layers failed -- error_detail must document all three fallback attempts
        assert "curl_cffi" in result.error_detail
        assert "flaresolverr" in result.error_detail
        assert "proxy" in result.error_detail


class TestUrlValidation:
    def test_valid_http_url_passes(self):
        assert _is_valid_url("http://example.com") is True

    def test_valid_https_url_passes(self):
        assert _is_valid_url("https://www.google.com/path?q=1") is True

    def test_missing_scheme_fails(self):
        assert _is_valid_url("example.com") is False

    def test_missing_host_fails(self):
        assert _is_valid_url("http://") is False

    def test_not_a_url_fails(self):
        assert _is_valid_url("N/A") is False

    def test_invalid_url_status_returned_by_analyze(self):
        result = analyze_tech_stack("not-a-url", session=None, _sleep_fn=_NO_SLEEP)
        assert result.status == "invalid_url"
        assert result.fallback_module == ""

    def test_proxy_credentials_not_in_error_detail(self):
        from src.dih_engine.recon.modules.proxy_probe import _via_generic_proxy
        err = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool: Failed to establish connection to http://user:secret@proxy.host:8080"
        )
        with patch("src.dih_engine.recon.modules.proxy_probe.requests.get", side_effect=err):
            result = _via_generic_proxy("http://target.com", "http://user:secret@proxy.host:8080", timeout=5)
        assert "secret" not in result["error_detail"]
        assert "***" in result["error_detail"]


class TestCleanAndOptimizeMap:
    def test_writes_csv_with_status_columns(self, tmp_path):
        input_csv = tmp_path / "urls.csv"
        input_csv.write_text("URL,Nombre Categoria\nhttps://example.com,Test\n")
        output_csv = tmp_path / "output.csv"

        ok_result = ProbeResult(
            url="https://example.com", status="ok",
            tech="Static HTML", strategy="BeautifulSoup", mines=["Found 5 <div>"],
        )
        with patch("src.dih_engine.recon.seer.analyze_tech_stack", return_value=ok_result), \
             patch("src.dih_engine.recon.seer.notify_all"):
            clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=10, sample_size=1)

        df = pd.read_csv(str(output_csv))
        assert "Status" in df.columns
        assert "Error_Detail" in df.columns
        assert "Fallback_Module" in df.columns
        assert df.loc[df["URL"] == "https://example.com", "Status"].iloc[0] == "ok"

    def test_non_probed_urls_get_not_probed_sentinel(self, tmp_path):
        input_csv = tmp_path / "urls.csv"
        input_csv.write_text("URL,Nombre Categoria\nhttps://a.com,A\nhttps://b.com,B\n")
        output_csv = tmp_path / "output.csv"

        ok_result = ProbeResult(
            url="https://a.com", status="ok",
            tech="Static HTML", strategy="BeautifulSoup", mines=[],
        )
        with patch("src.dih_engine.recon.seer.analyze_tech_stack", return_value=ok_result), \
             patch("src.dih_engine.recon.seer.notify_all"):
            clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=10, sample_size=1)

        df = pd.read_csv(str(output_csv))
        b_status = df.loc[df["URL"] == "https://b.com", "Status"].iloc[0]
        assert b_status == "not_probed", f"expected 'not_probed', got {b_status!r}"

    def test_missing_input_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            clean_and_optimize_map(str(tmp_path / "nope.csv"), str(tmp_path / "out.csv"))

    def test_invalid_url_in_csv_gets_invalid_url_status(self, tmp_path):
        input_csv = tmp_path / "urls.csv"
        input_csv.write_text("URL,Nombre Categoria\nnot-a-url,Bad\n")
        output_csv = tmp_path / "output.csv"
        with patch("src.dih_engine.recon.seer.notify_all"):
            with pytest.raises(ValueError, match="malformed URLs"):
                clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=10, sample_size=1)

    def test_partial_map_with_invalid_and_valid_urls_writes_all_rows(self, tmp_path):
        input_csv = tmp_path / "urls.csv"
        input_csv.write_text(
            "URL,Nombre Categoria\nnot-a-url,Bad\nhttps://example.com,Valid\n"
        )
        output_csv = tmp_path / "output.csv"

        def analysis_side_effect(url, session=None, timeout=10, _sleep_fn=None):
            if url == "https://example.com":
                return ProbeResult(
                    url=url,
                    status="ok",
                    tech="Static HTML",
                    strategy="BeautifulSoup",
                    mines=["Found 1 article"],
                )
            return ProbeResult(url=url, status="invalid_url", error_detail="malformed URL -- missing scheme or host")

        with patch("src.dih_engine.recon.seer.analyze_tech_stack", side_effect=analysis_side_effect), \
             patch("src.dih_engine.recon.seer.notify_all"):
            with pytest.raises(ValueError, match="malformed URLs"):
                clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=10, sample_size=2)

    def test_notification_failure_does_not_abort_csv_write(self, tmp_path):
        input_csv = tmp_path / "urls.csv"
        input_csv.write_text("URL,Nombre Categoria\nhttps://example.com,Test\n")
        output_csv = tmp_path / "output.csv"

        ok_result = ProbeResult(
            url="https://example.com", status="ok",
            tech="Static HTML", strategy="BeautifulSoup", mines=[],
        )
        with patch("src.dih_engine.recon.seer.analyze_tech_stack", return_value=ok_result), \
             patch("src.dih_engine.recon.seer.notify_all", side_effect=Exception("channel down")):
            clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=10, sample_size=1)

        assert output_csv.exists(), "CSV must be written even when notifications fail"

    def test_request_timeout_must_be_positive(self, tmp_path):
        input_csv = tmp_path / "urls.csv"
        input_csv.write_text("URL,Nombre Categoria\nhttps://example.com,Test\n")
        output_csv = tmp_path / "output.csv"

        with pytest.raises(ValueError, match="request_timeout must be a positive integer"):
            clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=0, sample_size=1)

    def test_sample_size_must_be_positive(self, tmp_path):
        input_csv = tmp_path / "urls.csv"
        input_csv.write_text("URL,Nombre Categoria\nhttps://example.com,Test\n")
        output_csv = tmp_path / "output.csv"

        with pytest.raises(ValueError, match="sample_size must be a positive integer"):
            clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=10, sample_size=0)

    def test_csv_with_no_valid_urls_raises(self, tmp_path):
        input_csv = tmp_path / "urls.csv"
        input_csv.write_text("URL,Nombre Categoria\n,Empty\n\n")
        output_csv = tmp_path / "output.csv"

        with pytest.raises(ValueError, match="CSV 'URL' column contains no valid URLs"):
            clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=10, sample_size=1)


class TestExponentialBackoff:
    """delay_retry backoff: base 5s, multiplier 2x, cap 60s, 0-1s jitter, max 3 retries."""

    _RATE_LIMITED = {"status": "http_429", "html": "", "content_type": "", "error_detail": "Rate Limited"}
    _TIMED_OUT = {"status": "timeout", "html": "", "content_type": "", "error_detail": "timeout after 10s"}
    _FORBIDDEN = {"status": "http_403", "html": "", "content_type": "", "error_detail": "HTTP 403"}
    _OK = {
        "status": "ok",
        "html": "<html><body>Recovered after backoff</body></html>",
        "content_type": "text/html",
        "error_detail": "",
    }

    def test_delays_follow_exponential_sequence(self):
        slept = []
        with patch("src.dih_engine.recon.seer.requests_probe.probe", return_value=self._RATE_LIMITED):
            result = analyze_tech_stack("http://example.com", session=None, _sleep_fn=slept.append)

        assert len(slept) == 3
        assert 5.0 <= slept[0] <= 6.0    # base 5 + jitter [0, 1)
        assert 10.0 <= slept[1] <= 11.0  # 5 * 2^1 + jitter
        assert 20.0 <= slept[2] <= 21.0  # 5 * 2^2 + jitter
        assert result.status == "http_429"
        assert "retry 1" in result.error_detail
        assert "retry 3" in result.error_detail

    def test_delay_is_capped_at_60_seconds(self, monkeypatch):
        monkeypatch.setattr("src.dih_engine.recon.seer.BACKOFF_BASE", 40.0)
        slept = []
        with patch("src.dih_engine.recon.seer.requests_probe.probe", return_value=self._RATE_LIMITED):
            analyze_tech_stack("http://example.com", session=None, _sleep_fn=slept.append)

        assert len(slept) == 3
        assert 40.0 <= slept[0] <= 41.0  # base 40, under cap
        assert 60.0 <= slept[1] <= 61.0  # 80 capped to 60 + jitter
        assert 60.0 <= slept[2] <= 61.0  # 160 capped to 60 + jitter

    def test_success_on_second_retry_stops_backing_off(self):
        slept = []
        with patch(
            "src.dih_engine.recon.seer.requests_probe.probe",
            side_effect=[self._RATE_LIMITED, self._RATE_LIMITED, self._OK],
        ):
            result = analyze_tech_stack("http://example.com", session=None, _sleep_fn=slept.append)

        assert result.status == "ok"
        assert len(slept) == 2  # no third sleep after recovery

    def test_error_class_change_aborts_remaining_retries(self):
        # 429 -> 403 on first retry: site went from rate-limiting to blocking.
        # More waiting cannot help; remaining retries must be skipped.
        slept = []
        with patch(
            "src.dih_engine.recon.seer.requests_probe.probe",
            side_effect=[self._TIMED_OUT, self._FORBIDDEN],
        ):
            result = analyze_tech_stack("http://example.com", session=None, _sleep_fn=slept.append)

        assert len(slept) == 1
        assert result.status == "timeout"
        assert result.fallback_module == "delay_retry"
        assert "HTTP 403" in result.error_detail


from src.dih_engine.recon.seer import _HostCircuitBreaker, CIRCUIT_BREAKER_THRESHOLD


class TestHostCircuitBreaker:
    """Per-host circuit breaker: opens after 3 terminal failures, scoped to one run."""

    def test_opens_after_threshold_terminal_failures(self):
        breaker = _HostCircuitBreaker()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            breaker.record("https://blocked.com/page", "http_403")
        assert breaker.is_open("https://blocked.com/other-page") is True

    def test_transient_failures_never_strike(self):
        breaker = _HostCircuitBreaker()
        for status in ("http_429", "timeout", "js_required", "http_other", "module_unavailable"):
            for _ in range(5):
                breaker.record("https://slow.com/page", status)
        assert breaker.is_open("https://slow.com/page") is False

    def test_success_resets_accumulated_strikes(self):
        breaker = _HostCircuitBreaker()
        breaker.record("https://flaky.com/a", "http_403")
        breaker.record("https://flaky.com/b", "ssl_error")
        breaker.record("https://flaky.com/c", "ok")  # host recovered
        breaker.record("https://flaky.com/d", "http_403")
        breaker.record("https://flaky.com/e", "http_403")
        assert breaker.is_open("https://flaky.com/f") is False  # 2 < threshold after reset

    def test_hosts_are_isolated(self):
        breaker = _HostCircuitBreaker()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            breaker.record("https://dead.com/x", "connection_error")
        assert breaker.is_open("https://dead.com/y") is True
        assert breaker.is_open("https://healthy.com/x") is False

    def test_run_skips_remaining_urls_of_blocked_host(self, tmp_path, monkeypatch):
        # 5 URLs on one host, every probe returns terminal 403. A serial executor
        # makes ordering deterministic: URLs 1-3 strike, URLs 4-5 must be skipped
        # without any probe call.
        class _SerialFuture:
            def __init__(self, fn, url):
                self._result = fn(url)

            def done(self):
                return True

            def result(self):
                return self._result

        class _SerialExecutor:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, url):
                return _SerialFuture(fn, url)

        input_csv = tmp_path / "urls.csv"
        rows = "\n".join(f"https://walled.com/p{i},Cat" for i in range(1, 6))
        input_csv.write_text(f"URL,Nombre Categoria\n{rows}\n")
        output_csv = tmp_path / "output.csv"

        probed_urls = []

        def _fake_analyze(url, session=None, timeout=10):
            probed_urls.append(url)
            return ProbeResult(url=url, status="http_403", error_detail="HTTP 403", fallback_module="curl_cffi")

        monkeypatch.setattr("src.dih_engine.recon.seer.ThreadPoolExecutor", _SerialExecutor)
        monkeypatch.setattr(
            "src.dih_engine.recon.seer.as_completed",
            lambda futures, timeout=None: iter(list(futures)),
        )
        monkeypatch.setattr("src.dih_engine.recon.seer.analyze_tech_stack", _fake_analyze)

        with patch("src.dih_engine.recon.seer.notify_all"):
            clean_and_optimize_map(str(input_csv), str(output_csv), request_timeout=5, sample_size=5)

        assert len(probed_urls) == 3  # circuit opened after the 3rd strike
        df = pd.read_csv(str(output_csv))
        statuses = df["Status"].tolist()
        assert statuses.count("http_403") == 3
        assert statuses.count("skipped_circuit_open") == 2
