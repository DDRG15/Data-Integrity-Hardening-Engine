import json

import pytest
from src.dih_engine.extraction.engine import bulletproof_processor, _disk_path_for_file


VALID_LINE = "ID: ABC-001 PRODUCT: 3D Printer Model X PRICE: S/ 299.99 Stock 5"
VALID_LINE_2 = "ID: XYZ-002 PRODUCT: Laptop Charger PRICE: S/ 49.99 Stock 10"
GARBAGE_LINE = "this line matches nothing at all"


class TestBulletproofProcessor:
    def test_happy_path_produces_jsonl(self, make_input_file, output_file):
        path = make_input_file([VALID_LINE, VALID_LINE_2])
        result = bulletproof_processor(path, output_file)

        assert result["matched"] == 2
        assert result["skipped"] == 0
        assert result["total"] == 2

        with open(output_file, encoding="utf-8") as f:
            records = [json.loads(line) for line in f]
        assert len(records) == 2

    def test_no_digit_3_substitution(self, make_input_file, output_file):
        # Regression: bug #1 — product names must not have '3' replaced with 'e'
        path = make_input_file([VALID_LINE])
        bulletproof_processor(path, output_file)

        with open(output_file, encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert "3D Printer" in record["Name"]
        assert "eD Printer" not in record["Name"]

    def test_unmatched_lines_counted(self, make_input_file, output_file):
        path = make_input_file([VALID_LINE, GARBAGE_LINE, GARBAGE_LINE])
        result = bulletproof_processor(path, output_file)

        assert result["matched"] == 1
        assert result["skipped"] == 2

    def test_empty_file_produces_zero_counts(self, make_input_file, output_file):
        path = make_input_file([])
        result = bulletproof_processor(path, output_file)

        assert result["total"] == 0
        assert result["matched"] == 0
        assert result["skipped"] == 0
        assert result["aborted"] is False

    def test_missing_input_raises_file_not_found(self, tmp_path, output_file):
        with pytest.raises(FileNotFoundError):
            bulletproof_processor(str(tmp_path / "nonexistent.txt"), output_file)

    def test_id_ocr_correction_applied(self, make_input_file, output_file):
        line = "ID: O01-ABC PRODUCT: Widget PRICE: S/ 9.99 Stock 1"
        path = make_input_file([line])
        bulletproof_processor(path, output_file)

        with open(output_file, encoding="utf-8") as f:
            record = json.loads(f.readline())
        assert record["ID"] == "001-ABC"

    def test_missing_stock_defaults_to_zero(self, make_input_file, output_file):
        line = "ID: DEF-003 PRODUCT: No Stock Item PRICE: S/ 5.00"
        path = make_input_file([line])
        bulletproof_processor(path, output_file)

        with open(output_file, encoding="utf-8") as f:
            record = json.loads(f.readline())
        assert record["Stock"] == 0


class TestDiskPathHelper:
    def test_windows_path_ends_with_backslash(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.dih_engine.extraction.engine.sys.platform", "win32")
        # On a real Windows system this returns e.g. 'C:\\'
        path = _disk_path_for_file(str(tmp_path / "file.txt"))
        assert path.endswith("\\")
        assert "/" not in path

    def test_unix_path_is_root_slash(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.dih_engine.extraction.engine.sys.platform", "linux")
        path = _disk_path_for_file(str(tmp_path / "file.txt"))
        assert path == "/"
