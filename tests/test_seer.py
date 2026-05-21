import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.dih_engine.recon.modules.flaresolverr_probe import probe as flaresolverr_probe
from src.dih_engine.recon.modules.proxy_probe import _via_generic_proxy, _via_scrapfly, probe as proxy_probe
from src.dih_engine.recon.seer import (
    ProbeResult,
    _build_probe_result,
    _disk_path,
    _identify_stack,
    _majority_stack,
    analyze_tech_stack,
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

    def test_keyboard_interrupt_propagates(self):
        # KeyboardInterrupt must NOT be swallowed -- regression for bare except: removal
        mock_session = MagicMock()
        mock_session.get.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)


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
