"""
Tests for dih_engine.config_store and the `dih-engine config` CLI subcommand.

Security contract under test: secret values never appear in list output or
metadata beyond their last 4 characters; unknown names are rejected; comments
and foreign lines in .env are never touched.
"""
import json
import sys
from unittest.mock import patch

import pytest

from src.dih_engine import config_store
from src.dih_engine.cli import _build_parser, main


@pytest.fixture
def paths(tmp_path):
    return str(tmp_path / ".env"), str(tmp_path / ".env.meta.json")


class TestSetVar:
    def test_set_new_secret_writes_env_and_meta(self, paths):
        env, meta = paths
        entry = config_store.set_var("SCRAPFLY_API_KEY", "scp-live-abcd1234", env, meta)

        with open(env, encoding="utf-8") as f:
            assert "SCRAPFLY_API_KEY=scp-live-abcd1234" in f.read()
        assert entry["set_at"] is not None
        assert entry["rotated_at"] is None
        assert entry["last4"] == "1234"
        # The metadata file must never contain the secret value itself.
        with open(meta, encoding="utf-8") as f:
            assert "scp-live-abcd1234" not in f.read()

    def test_rotation_updates_rotated_at_and_last4_keeps_set_at(self, paths):
        env, meta = paths
        first = config_store.set_var("DIH_API_KEY", "original-key-xyz1", env, meta)
        second = config_store.set_var("DIH_API_KEY", "replacement-key-9876", env, meta)

        assert second["set_at"] == first["set_at"]
        assert second["rotated_at"] is not None
        assert second["last4"] == "9876"
        # .env holds exactly one line for the var -- rotated in place.
        with open(env, encoding="utf-8") as f:
            content = f.read()
        assert content.count("DIH_API_KEY=") == 1
        assert "replacement-key-9876" in content
        assert "original-key-xyz1" not in content

    def test_preserves_comments_and_foreign_lines(self, paths):
        env, meta = paths
        with open(env, "w", encoding="utf-8") as f:
            f.write("# my precious comment\nCUSTOM_THING=untouched\n\nDIH_API_KEY=old-value-aaaa\n")
        config_store.set_var("DIH_API_KEY", "new-value-bbbb", env, meta)

        with open(env, encoding="utf-8") as f:
            lines = f.read().splitlines()
        assert lines[0] == "# my precious comment"
        assert lines[1] == "CUSTOM_THING=untouched"
        assert lines[2] == ""
        assert lines[3] == "DIH_API_KEY=new-value-bbbb"

    def test_unknown_name_rejected(self, paths):
        env, meta = paths
        with pytest.raises(ValueError, match="unknown variable"):
            config_store.set_var("DIH_API_KEYY", "typo-value", env, meta)

    def test_empty_value_rejected(self, paths):
        env, meta = paths
        with pytest.raises(ValueError, match="must not be empty"):
            config_store.set_var("DIH_API_KEY", "   ", env, meta)

    def test_multiline_value_rejected(self, paths):
        env, meta = paths
        with pytest.raises(ValueError, match="single line"):
            config_store.set_var("DIH_API_KEY", "evil\nINJECTED=1", env, meta)

    def test_short_secret_fully_masked(self, paths):
        env, meta = paths
        entry = config_store.set_var("DIH_API_KEY", "tiny", env, meta)
        assert entry["last4"] == "****"  # 4 chars of a 4-char secret = the secret

    def test_non_secret_gets_no_last4(self, paths):
        env, meta = paths
        entry = config_store.set_var("SEER_SAMPLE_SIZE", "5", env, meta)
        assert "last4" not in entry

    def test_provider_recorded_and_kept_on_rotation(self, paths):
        env, meta = paths
        config_store.set_var("SCRAPFLY_API_KEY", "scp-live-abcd1234", env, meta, provider="Scrapfly free tier")
        entry = config_store.set_var("SCRAPFLY_API_KEY", "scp-live-efgh5678", env, meta)
        assert entry["provider"] == "Scrapfly free tier"


class TestUnsetVar:
    def test_unset_removes_line_and_meta(self, paths):
        env, meta = paths
        config_store.set_var("DIH_API_KEY", "doomed-key-0001", env, meta)
        config_store.unset_var("DIH_API_KEY", env, meta)

        with open(env, encoding="utf-8") as f:
            assert "DIH_API_KEY" not in f.read()
        with open(meta, encoding="utf-8") as f:
            assert "DIH_API_KEY" not in json.load(f)

    def test_unset_missing_var_raises(self, paths):
        env, meta = paths
        with pytest.raises(ValueError, match="not set"):
            config_store.unset_var("DIH_API_KEY", env, meta)

    def test_unset_unknown_name_rejected(self, paths):
        env, meta = paths
        with pytest.raises(ValueError, match="unknown variable"):
            config_store.unset_var("NOT_A_VAR", env, meta)


class TestListVars:
    def test_secret_value_never_appears_in_rows(self, paths):
        env, meta = paths
        config_store.set_var("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/SECRETPART", env, meta)
        rows = config_store.list_vars(env, meta)
        dumped = json.dumps(rows)
        assert "SECRETPART" not in dumped
        slack = next(r for r in rows if r["name"] == "SLACK_WEBHOOK_URL")
        assert slack["display"] == "****PART"

    def test_non_secret_shown_as_is(self, paths):
        env, meta = paths
        config_store.set_var("SEER_SAMPLE_SIZE", "7", env, meta)
        row = next(r for r in config_store.list_vars(env, meta) if r["name"] == "SEER_SAMPLE_SIZE")
        assert row["display"] == "7"

    def test_unset_known_var_listed_as_not_set(self, paths):
        env, meta = paths
        row = next(r for r in config_store.list_vars(env, meta) if r["name"] == "DIH_API_KEY")
        assert row["set"] is False
        assert row["display"] == "(not set)"

    def test_hand_edited_secret_without_meta_masked_with_unknown_last4(self, paths):
        env, meta = paths
        with open(env, "w", encoding="utf-8") as f:
            f.write("DIH_API_KEY=hand-edited-secret-value\n")
        row = next(r for r in config_store.list_vars(env, meta) if r["name"] == "DIH_API_KEY")
        assert row["display"] == "****????"

    def test_unknown_var_in_env_reported_but_masked(self, paths):
        env, meta = paths
        with open(env, "w", encoding="utf-8") as f:
            f.write("MYSTERY_TOKEN=super-secret-mystery\n")
        rows = config_store.list_vars(env, meta)
        mystery = next(r for r in rows if r["name"] == "MYSTERY_TOKEN")
        assert "super-secret-mystery" not in json.dumps(rows)
        assert mystery["display"] == "**** (unknown var)"


class TestConfigCli:
    def test_parser_accepts_config_set(self):
        args = _build_parser().parse_args(["config", "set", "DIH_API_KEY", "--value", "v" * 12])
        assert args.command == "config"
        assert args.config_command == "set"
        assert args.name == "DIH_API_KEY"

    def test_cli_set_then_list_roundtrip(self, paths, capsys):
        env, meta = paths
        with patch.object(sys, "argv", [
            "dih-engine", "config", "set", "SCRAPFLY_API_KEY",
            "--value", "scp-live-abcd1234", "--provider", "Scrapfly",
            "--env-file", env, "--meta-file", meta,
        ]):
            main()
        out = capsys.readouterr().out
        assert "SCRAPFLY_API_KEY set (****1234)" in out
        assert "scp-live-abcd1234" not in out  # value never echoed

        with patch.object(sys, "argv", [
            "dih-engine", "config", "list", "--env-file", env, "--meta-file", meta,
        ]):
            main()
        out = capsys.readouterr().out
        assert "****1234" in out
        assert "scp-live-abcd1234" not in out
        assert "Scrapfly" in out

    def test_cli_unset_missing_exits_1(self, paths, capsys):
        env, meta = paths
        with patch.object(sys, "argv", [
            "dih-engine", "config", "unset", "DIH_API_KEY", "--env-file", env, "--meta-file", meta,
        ]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1
        assert "not set" in capsys.readouterr().err

    def test_cli_set_unknown_var_exits_1(self, paths, capsys):
        env, meta = paths
        with patch.object(sys, "argv", [
            "dih-engine", "config", "set", "TYPO_VAR", "--value", "whatever-value",
            "--env-file", env, "--meta-file", meta,
        ]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1
        assert "unknown variable" in capsys.readouterr().err