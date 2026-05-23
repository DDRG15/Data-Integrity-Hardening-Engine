"""
Tests for dih_engine.cli — the argparse entry point.

Strategy: test _build_parser() directly for argument parsing correctness,
and test main() by patching sys.argv + the underlying processor functions.
main() calls sys.exit() on failure — catch SystemExit with pytest.raises().
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.dih_engine.cli import _build_parser, main


class TestBuildParserExtract:
    def test_parses_required_args(self):
        args = _build_parser().parse_args(["extract", "--input", "in.txt", "--output", "out.jsonl"])
        assert args.command == "extract"
        assert args.input == "in.txt"
        assert args.output == "out.jsonl"

    def test_default_output_format_is_jsonl(self):
        args = _build_parser().parse_args(["extract", "--input", "a", "--output", "b"])
        assert args.output_format == "jsonl"

    def test_output_format_csv(self):
        args = _build_parser().parse_args(["extract", "--input", "a", "--output", "b", "--output-format", "csv"])
        assert args.output_format == "csv"

    def test_output_format_sqlite(self):
        args = _build_parser().parse_args(["extract", "--input", "a", "--output", "b", "--output-format", "sqlite"])
        assert args.output_format == "sqlite"

    def test_default_pause_and_disk_thresholds(self):
        args = _build_parser().parse_args(["extract", "--input", "a", "--output", "b"])
        assert args.pause_threshold == 80.0
        assert args.disk_threshold == 95.0

    def test_custom_thresholds(self):
        args = _build_parser().parse_args([
            "extract", "--input", "a", "--output", "b",
            "--pause-threshold", "70.0", "--disk-threshold", "90.0",
        ])
        assert args.pause_threshold == 70.0
        assert args.disk_threshold == 90.0

    def test_invalid_output_format_raises(self):
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["extract", "--input", "a", "--output", "b", "--output-format", "parquet"])


class TestBuildParserRecon:
    def test_parses_required_args(self):
        args = _build_parser().parse_args(["recon", "--input", "urls.csv", "--output", "plan.csv"])
        assert args.command == "recon"
        assert args.input == "urls.csv"
        assert args.output == "plan.csv"

    def test_defaults_for_timeout_and_sample_size(self):
        args = _build_parser().parse_args(["recon", "--input", "a", "--output", "b"])
        assert args.timeout == 10
        assert args.sample_size == 3

    def test_custom_timeout_and_sample_size(self):
        args = _build_parser().parse_args([
            "recon", "--input", "a", "--output", "b",
            "--timeout", "30", "--sample-size", "10",
        ])
        assert args.timeout == 30
        assert args.sample_size == 10

    def test_no_subcommand_raises(self):
        with pytest.raises(SystemExit):
            _build_parser().parse_args([])


class TestMainExtract:
    _BASE_ARGV = ["dih-engine", "extract", "--input", "in.txt", "--output", "out.jsonl"]

    def test_success_prints_matched_and_skipped(self, capsys):
        with patch("sys.argv", self._BASE_ARGV):
            with patch("src.dih_engine.cli.bulletproof_processor",
                       return_value={"matched": 7, "skipped": 3, "aborted": False}):
                main()
        out = capsys.readouterr().out
        assert "7" in out
        assert "3" in out

    def test_file_not_found_exits_1(self):
        with patch("sys.argv", self._BASE_ARGV):
            with patch("src.dih_engine.cli.bulletproof_processor",
                       side_effect=FileNotFoundError("in.txt not found")):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1

    def test_aborted_result_exits_2(self):
        with patch("sys.argv", self._BASE_ARGV):
            with patch("src.dih_engine.cli.bulletproof_processor",
                       return_value={"matched": 0, "skipped": 0, "aborted": True}):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 2

    def test_error_message_written_to_stderr_on_file_not_found(self, capsys):
        with patch("sys.argv", self._BASE_ARGV):
            with patch("src.dih_engine.cli.bulletproof_processor",
                       side_effect=FileNotFoundError("in.txt not found")):
                with pytest.raises(SystemExit):
                    main()
        assert "error" in capsys.readouterr().err.lower()

    def test_csv_format_flag_forwarded_to_processor(self):
        mock_fn = MagicMock(return_value={"matched": 0, "skipped": 0, "aborted": False})
        argv = self._BASE_ARGV + ["--output-format", "csv"]
        with patch("sys.argv", argv):
            with patch("src.dih_engine.cli.bulletproof_processor", mock_fn):
                main()
        _, kwargs = mock_fn.call_args
        positional = mock_fn.call_args.args
        assert "csv" in positional or kwargs.get("output_format") == "csv"


class TestMainRecon:
    _BASE_ARGV = ["dih-engine", "recon", "--input", "urls.csv", "--output", "plan.csv"]

    def test_success_calls_clean_and_optimize_map(self):
        mock_fn = MagicMock()
        with patch("sys.argv", self._BASE_ARGV):
            with patch("src.dih_engine.recon.clean_and_optimize_map", mock_fn):
                main()
        mock_fn.assert_called_once()

    def test_passes_timeout_and_sample_size(self):
        mock_fn = MagicMock()
        argv = self._BASE_ARGV + ["--timeout", "20", "--sample-size", "5"]
        with patch("sys.argv", argv):
            with patch("src.dih_engine.recon.clean_and_optimize_map", mock_fn):
                main()
        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs.get("request_timeout") == 20
        assert call_kwargs.get("sample_size") == 5

    def test_file_not_found_exits_1(self):
        with patch("sys.argv", self._BASE_ARGV):
            with patch("src.dih_engine.recon.clean_and_optimize_map",
                       side_effect=FileNotFoundError("urls.csv not found")):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1

    def test_value_error_exits_1(self):
        with patch("sys.argv", self._BASE_ARGV):
            with patch("src.dih_engine.recon.clean_and_optimize_map",
                       side_effect=ValueError("CSV missing required 'URL' column")):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1

    def test_error_message_written_to_stderr_on_value_error(self, capsys):
        with patch("sys.argv", self._BASE_ARGV):
            with patch("src.dih_engine.recon.clean_and_optimize_map",
                       side_effect=ValueError("CSV missing 'URL'")):
                with pytest.raises(SystemExit):
                    main()
        assert "error" in capsys.readouterr().err.lower()
