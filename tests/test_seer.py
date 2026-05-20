import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.dih_engine.recon.seer import (
    _disk_path,
    _identify_stack,
    _majority_stack,
    analyze_tech_stack,
    locate_gold_mines,
)


class TestDiskPath:
    def test_windows_path_does_not_use_forward_slash(self, monkeypatch):
        # Regression: bug #2 — psutil.disk_usage('/') crashes on Windows
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


_NO_SLEEP = lambda _: None  # noqa: E731


class TestAnalyzeTechStack:
    def test_happy_path_returns_tuple(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Static page</body></html>"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert result is not None
        tech, strategy, mines = result
        assert isinstance(tech, str)
        assert isinstance(strategy, str)
        assert isinstance(mines, list)

    def test_connection_error_returns_none(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("refused")

        result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert result is None

    def test_timeout_returns_none(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.Timeout()

        result = analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)
        assert result is None

    def test_keyboard_interrupt_propagates(self):
        # KeyboardInterrupt must NOT be swallowed — regression for bare except: removal
        mock_session = MagicMock()
        mock_session.get.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            analyze_tech_stack("http://example.com", mock_session, _sleep_fn=_NO_SLEEP)


class TestMajorityStack:
    def test_clear_majority_selected(self):
        results = [
            ("Static HTML", "BeautifulSoup", ["found 5"]),
            ("Static HTML", "BeautifulSoup", ["found 8"]),
            ("React.js (CSR)", "Selenium", ["found 2"]),
        ]
        tech, strategy, _ = _majority_stack(results)
        assert tech == "Static HTML"

    def test_no_majority_still_returns_result(self):
        results = [
            ("Static HTML", "BeautifulSoup", []),
            ("React.js (CSR)", "Selenium", []),
            ("Next.js (SSR)", "Parse JSON", []),
        ]
        # Should not raise — returns the most frequent (any of them, since all tied)
        tech, strategy, mines = _majority_stack(results)
        assert isinstance(tech, str)


class TestLocateGoldMines:
    def test_finds_article_tags(self):
        html = "<html>" + "<article>item</article>" * 15 + "</html>"
        mines = locate_gold_mines(html)
        assert any("article" in m for m in mines)

    def test_returns_fallback_for_sparse_html(self):
        mines = locate_gold_mines("<html><body><p>Hello</p></body></html>")
        assert "No obvious" in mines[0]
