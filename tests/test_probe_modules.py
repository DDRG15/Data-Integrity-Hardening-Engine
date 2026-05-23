"""
Tests for the three probe modules that had low coverage after the full suite:
  requests_probe.py   79%  (lines 27, 45, 54-55, 67, 70, 73-74, 85-86, 90)
  curlffi_probe.py    30%  (lines 14-15, 23-40)
  playwright_probe.py 26%  (lines 14-15, 23-43)

Strategy:
  - Call probe() directly (not through analyze_tech_stack) to avoid seer-level mocking.
  - Patch the underlying library calls at the module level.
  - For _AVAILABLE=False paths: temporarily set the module attribute to False.
  - Lines 14-15 of each module (the ImportError except block) can only be covered when
    the optional library is NOT installed. Since curl_cffi and playwright ARE installed
    in this env, those two lines remain an acceptable gap (documented below).
"""
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

from src.dih_engine.recon.modules import requests_probe, curlffi_probe, playwright_probe


# ── Helper ────────────────────────────────────────────────────────────────────

_NO_SLEEP = lambda _: None  # noqa: E731


def _http_error(code: int) -> _requests.exceptions.HTTPError:
    mock_resp = MagicMock()
    mock_resp.status_code = code
    return _requests.exceptions.HTTPError(response=mock_resp)


# ── requests_probe ────────────────────────────────────────────────────────────

class TestRequestsProbeSessionNone:
    """session=None path: probe creates its own Session, sets User-Agent, closes it."""

    def test_creates_session_sets_user_agent_and_closes(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = "<html><body>enough content to not be a JS shell at all</body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch("src.dih_engine.recon.modules.requests_probe.requests.Session",
                   return_value=mock_session):
            result = requests_probe.probe("http://example.com", session=None, _sleep_fn=_NO_SLEEP)

        mock_session.headers.update.assert_called_once()
        user_agent_arg = mock_session.headers.update.call_args[0][0]
        assert "User-Agent" in user_agent_arg
        mock_session.close.assert_called_once()
        assert result["status"] == "ok"

    def test_jitter_sleep_is_called_before_request(self):
        slept = []
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = "<html>full page content here to avoid js_shell detection</html>"
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch("src.dih_engine.recon.modules.requests_probe.requests.Session",
                   return_value=mock_session):
            requests_probe.probe("http://example.com", session=None, _sleep_fn=slept.append)

        assert len(slept) == 1
        assert isinstance(slept[0], float)
        assert 1.0 <= slept[0] <= 4.0


class TestRequestsProbeHttpErrors:
    """HTTP error code classification branches."""

    def test_http_429_returns_rate_limited_status(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = _http_error(429)
        result = requests_probe.probe("http://example.com", session=mock_session, _sleep_fn=_NO_SLEEP)
        assert result["status"] == "http_429"
        assert "429" in result["error_detail"]

    def test_http_500_returns_http_other(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = _http_error(500)
        result = requests_probe.probe("http://example.com", session=mock_session, _sleep_fn=_NO_SLEEP)
        assert result["status"] == "http_other"
        assert "500" in result["error_detail"]

    def test_http_503_returns_http_other(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = _http_error(503)
        result = requests_probe.probe("http://example.com", session=mock_session, _sleep_fn=_NO_SLEEP)
        assert result["status"] == "http_other"

    def test_ssl_error_returns_ssl_error_status(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = _requests.exceptions.SSLError("certificate verify failed")
        result = requests_probe.probe("http://example.com", session=mock_session, _sleep_fn=_NO_SLEEP)
        assert result["status"] == "ssl_error"
        assert result["html"] == ""

    def test_generic_request_exception_returns_http_other(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = _requests.exceptions.RequestException("unknown network error")
        result = requests_probe.probe("http://example.com", session=mock_session, _sleep_fn=_NO_SLEEP)
        assert result["status"] == "http_other"
        assert "unknown network error" in result["error_detail"]


class TestRequestsProbeJsShell:
    """JS-shell detection: short body with <div id= triggers js_required."""

    def test_short_body_with_div_id_returns_js_required(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = '<div id="root"></div>'
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        result = requests_probe.probe("http://example.com", session=mock_session, _sleep_fn=_NO_SLEEP)
        assert result["status"] == "js_required"
        assert "CSR" in result["error_detail"] or "shell" in result["error_detail"]

    def test_json_content_type_not_classified_as_js_shell(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"key": "value"}'
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        result = requests_probe.probe("http://example.com", session=mock_session, _sleep_fn=_NO_SLEEP)
        assert result["status"] == "ok"


# ── curlffi_probe ─────────────────────────────────────────────────────────────

class TestCurlffiProbeUnavailable:
    """When _AVAILABLE is False, probe returns module_unavailable immediately."""

    def test_unavailable_returns_module_unavailable(self):
        with patch.object(curlffi_probe, "_AVAILABLE", False):
            result = curlffi_probe.probe("http://example.com")
        assert result["status"] == "module_unavailable"
        assert "dih-engine[tls]" in result["error_detail"]
        assert result["html"] == ""


class TestCurlffiProbeAvailable:
    """When curl_cffi IS installed, test success and failure through cffi_requests."""

    def test_successful_fetch_returns_ok(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = "<html><body>Real page content here</body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch.object(curlffi_probe, "_AVAILABLE", True), \
             patch("src.dih_engine.recon.modules.curlffi_probe.cffi_requests") as mock_cffi:
            mock_cffi.get.return_value = mock_response
            result = curlffi_probe.probe("http://example.com", timeout=10)

        assert result["status"] == "ok"
        assert result["html"] == "<html><body>Real page content here</body></html>"
        mock_cffi.get.assert_called_once_with("http://example.com", timeout=10, impersonate="chrome120")

    def test_http_error_returns_http_other(self):
        with patch.object(curlffi_probe, "_AVAILABLE", True), \
             patch("src.dih_engine.recon.modules.curlffi_probe.cffi_requests") as mock_cffi:
            mock_cffi.get.side_effect = Exception("Cloudflare challenge not bypassed")
            result = curlffi_probe.probe("http://example.com", timeout=10)

        assert result["status"] == "http_other"
        assert "Cloudflare" in result["error_detail"]

    def test_error_detail_truncated_to_120_chars(self):
        long_error = "x" * 200
        with patch.object(curlffi_probe, "_AVAILABLE", True), \
             patch("src.dih_engine.recon.modules.curlffi_probe.cffi_requests") as mock_cffi:
            mock_cffi.get.side_effect = Exception(long_error)
            result = curlffi_probe.probe("http://example.com")

        assert len(result["error_detail"]) <= 120

    def test_timeout_forwarded_to_cffi_get(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = "<html>content</html>"
        mock_response.raise_for_status = MagicMock()

        with patch.object(curlffi_probe, "_AVAILABLE", True), \
             patch("src.dih_engine.recon.modules.curlffi_probe.cffi_requests") as mock_cffi:
            mock_cffi.get.return_value = mock_response
            curlffi_probe.probe("http://example.com", timeout=30)

        _, kwargs = mock_cffi.get.call_args
        assert kwargs.get("timeout") == 30


# ── playwright_probe ──────────────────────────────────────────────────────────

class TestPlaywrightProbeUnavailable:
    """When _AVAILABLE is False, probe returns module_unavailable immediately."""

    def test_unavailable_returns_module_unavailable(self):
        with patch.object(playwright_probe, "_AVAILABLE", False):
            result = playwright_probe.probe("http://example.com")
        assert result["status"] == "module_unavailable"
        assert "dih-engine[browser]" in result["error_detail"]
        assert result["html"] == ""


class TestPlaywrightProbeAvailable:
    """When playwright IS installed, test success and failure through sync_playwright."""

    def _make_mock_playwright(self, html_content: str):
        mock_page = MagicMock()
        mock_page.content.return_value = html_content

        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_p = MagicMock()
        mock_p.chromium = mock_chromium

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_p)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        return mock_ctx, mock_page, mock_browser

    def test_successful_render_returns_ok(self):
        mock_ctx, mock_page, mock_browser = self._make_mock_playwright(
            "<html><body>JS-rendered content</body></html>"
        )
        with patch.object(playwright_probe, "_AVAILABLE", True), \
             patch("src.dih_engine.recon.modules.playwright_probe.sync_playwright",
                   return_value=mock_ctx):
            result = playwright_probe.probe("http://example.com", timeout=15)

        assert result["status"] == "ok"
        assert "JS-rendered content" in result["html"]
        assert result["content_type"] == "text/html"
        mock_browser.close.assert_called_once()

    def test_timeout_forwarded_as_milliseconds(self):
        mock_ctx, mock_page, mock_browser = self._make_mock_playwright("<html>content</html>")
        with patch.object(playwright_probe, "_AVAILABLE", True), \
             patch("src.dih_engine.recon.modules.playwright_probe.sync_playwright",
                   return_value=mock_ctx):
            playwright_probe.probe("http://example.com", timeout=20)

        mock_page.goto.assert_called_once_with(
            "http://example.com", timeout=20_000, wait_until="networkidle"
        )

    def test_exception_returns_http_other(self):
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(side_effect=Exception("browser crash"))
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch.object(playwright_probe, "_AVAILABLE", True), \
             patch("src.dih_engine.recon.modules.playwright_probe.sync_playwright",
                   return_value=mock_ctx):
            result = playwright_probe.probe("http://example.com", timeout=10)

        assert result["status"] == "http_other"
        assert "browser crash" in result["error_detail"]

    def test_error_detail_truncated_to_120_chars(self):
        long_error = "y" * 200
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(side_effect=Exception(long_error))
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch.object(playwright_probe, "_AVAILABLE", True), \
             patch("src.dih_engine.recon.modules.playwright_probe.sync_playwright",
                   return_value=mock_ctx):
            result = playwright_probe.probe("http://example.com")

        assert len(result["error_detail"]) <= 120
