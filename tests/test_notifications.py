"""
Tests for dih_engine.notifications — Slack and Discord webhook notifiers.

All tests mock requests.post so no real network calls are made.
notify_recon_complete() must NEVER raise — only return True/False.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.dih_engine.notifications.slack_notifier import (
    _build_blocks,
    _status_emoji,
    notify_recon_complete as slack_notify,
)
from src.dih_engine.notifications.discord_notifier import (
    _embed_color,
    notify_recon_complete as discord_notify,
)
from src.dih_engine.notifications import notify_all


# ── shared fixture data ────────────────────────────────────────────────────────

_STATUS_COUNTS = {"ok": 2, "http_403": 1}
_FALLBACK_COUNTS = {"curl_cffi": 1}
_KWARGS = dict(
    tech="Static HTML",
    strategy="BeautifulSoup",
    gold_mine="Found 42 <li> elements",
    status_counts=_STATUS_COUNTS,
    fallback_counts=_FALLBACK_COUNTS,
    output_file="plan.csv",
)


# ── Slack: pure helper functions ───────────────────────────────────────────────

class TestStatusEmoji:
    def test_all_ok(self):
        assert _status_emoji(ok_count=3, total=3) == ":white_check_mark:"

    def test_all_failed(self):
        assert _status_emoji(ok_count=0, total=3) == ":x:"

    def test_mixed(self):
        assert _status_emoji(ok_count=1, total=3) == ":warning:"


class TestBuildBlocks:
    def test_returns_list_of_dicts(self):
        blocks = _build_blocks(
            tech="Static HTML",
            strategy="BeautifulSoup",
            gold_mine="Found 5 <li>",
            status_counts={"ok": 2},
            fallback_counts={},
            output_file="out.csv",
            total=2,
        )
        assert isinstance(blocks, list)
        assert len(blocks) > 0
        assert all(isinstance(b, dict) for b in blocks)

    def test_header_block_contains_report_text(self):
        blocks = _build_blocks(
            tech="Next.js (SSR)", strategy="Parse JSON",
            gold_mine="n/a", status_counts={"ok": 1},
            fallback_counts={}, output_file="out.csv", total=1,
        )
        header = next((b for b in blocks if b.get("type") == "header"), None)
        assert header is not None
        assert "Seer" in header["text"]["text"]

    def test_no_fallback_renders_as_none(self):
        blocks = _build_blocks(
            tech="Static HTML", strategy="BS4", gold_mine="n/a",
            status_counts={"ok": 1}, fallback_counts={},
            output_file="out.csv", total=1,
        )
        all_text = str(blocks)
        assert "none" in all_text

    def test_fallback_counts_appear_in_blocks(self):
        blocks = _build_blocks(
            tech="Static HTML", strategy="BS4", gold_mine="n/a",
            status_counts={"ok": 1, "http_403": 2},
            fallback_counts={"curl_cffi": 2},
            output_file="out.csv", total=3,
        )
        all_text = str(blocks)
        assert "curl_cffi" in all_text


# ── Slack: notify_recon_complete ───────────────────────────────────────────────

class TestSlackNotify:
    def test_no_webhook_returns_false_silently(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        assert slack_notify(**_KWARGS) is False

    def test_successful_post_returns_true(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        with patch("src.dih_engine.notifications.slack_notifier.requests.post",
                   return_value=mock_response):
            result = slack_notify(**_KWARGS)
        assert result is True

    def test_request_exception_returns_false_never_raises(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
        with patch("src.dih_engine.notifications.slack_notifier.requests.post",
                   side_effect=requests.exceptions.ConnectionError("refused")):
            result = slack_notify(**_KWARGS)
        assert result is False

    def test_http_error_from_slack_returns_false(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=MagicMock(status_code=429)
        )
        with patch("src.dih_engine.notifications.slack_notifier.requests.post",
                   return_value=mock_response):
            result = slack_notify(**_KWARGS)
        assert result is False

    def test_empty_fallback_counts_renders_none(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        captured = {}
        def capture_post(url, json, timeout):
            captured["payload"] = json
            return mock_response
        with patch("src.dih_engine.notifications.slack_notifier.requests.post", capture_post):
            slack_notify(
                tech="Static HTML", strategy="BS4", gold_mine="n/a",
                status_counts={"ok": 1}, fallback_counts={}, output_file="out.csv",
            )
        assert "none" in str(captured["payload"])


# ── Discord: pure helper ───────────────────────────────────────────────────────

class TestEmbedColor:
    def test_all_ok_is_green(self):
        assert _embed_color(ok_count=3, total=3) == 3066993

    def test_all_failed_is_red(self):
        assert _embed_color(ok_count=0, total=3) == 15158332

    def test_mixed_is_yellow(self):
        assert _embed_color(ok_count=1, total=3) == 16776960


# ── Discord: notify_recon_complete ─────────────────────────────────────────────

class TestDiscordNotify:
    def test_no_webhook_returns_false_silently(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert discord_notify(**_KWARGS) is False

    def test_successful_post_returns_true(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test/token")
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.raise_for_status = MagicMock()
        with patch("src.dih_engine.notifications.discord_notifier.requests.post",
                   return_value=mock_response):
            result = discord_notify(**_KWARGS)
        assert result is True

    def test_request_exception_returns_false_never_raises(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test/token")
        with patch("src.dih_engine.notifications.discord_notifier.requests.post",
                   side_effect=requests.exceptions.Timeout("timed out")):
            result = discord_notify(**_KWARGS)
        assert result is False

    def test_http_429_from_discord_returns_false(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test/token")
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=MagicMock(status_code=429)
        )
        with patch("src.dih_engine.notifications.discord_notifier.requests.post",
                   return_value=mock_response):
            result = discord_notify(**_KWARGS)
        assert result is False

    def test_embed_fields_contain_tech_and_strategy(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test/token")
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.raise_for_status = MagicMock()
        captured = {}
        def capture_post(url, json, timeout):
            captured["payload"] = json
            return mock_response
        with patch("src.dih_engine.notifications.discord_notifier.requests.post", capture_post):
            discord_notify(**_KWARGS)
        embed = captured["payload"]["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Architecture" in field_names
        assert "Strategy" in field_names


# ── notify_all orchestrator ────────────────────────────────────────────────────

class TestNotifyAll:
    def test_calls_both_slack_and_discord(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        slack_mock = MagicMock(return_value=False)
        discord_mock = MagicMock(return_value=False)
        with patch("src.dih_engine.notifications.slack_notifier.notify_recon_complete", slack_mock), \
             patch("src.dih_engine.notifications.discord_notifier.notify_recon_complete", discord_mock):
            notify_all(**_KWARGS)
        slack_mock.assert_called_once()
        discord_mock.assert_called_once()

    def test_does_not_raise_when_both_succeed(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        with patch("src.dih_engine.notifications.slack_notifier.notify_recon_complete",
                   return_value=True), \
             patch("src.dih_engine.notifications.discord_notifier.notify_recon_complete",
                   return_value=True):
            notify_all(**_KWARGS)
