import csv
import json
import sqlite3

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
        # Regression: name must not bleed into Price/Stock fields
        assert records[0]["Name"] == "3D Printer Model X"
        assert records[0]["Price"] == 299.99
        assert records[0]["Stock"] == 5
        assert records[1]["Name"] == "Laptop Charger"
        assert records[1]["Price"] == 49.99
        assert records[1]["Stock"] == 10

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


class TestOutputFormatCsv:
    def test_csv_produces_header_and_rows(self, make_input_file, tmp_path):
        out = str(tmp_path / "out.csv")
        path = make_input_file([VALID_LINE, VALID_LINE_2])
        result = bulletproof_processor(path, out, output_format="csv")

        assert result["matched"] == 2
        with open(out, encoding="utf-8", newline="") as f:
            reader = list(csv.DictReader(f))
        assert len(reader) == 2
        assert reader[0]["ID"] == "ABC-001"
        assert reader[0]["Name"] == "3D Printer Model X"
        assert float(reader[0]["Price"]) == 299.99
        assert int(reader[0]["Stock"]) == 5

    def test_csv_garbage_lines_skipped(self, make_input_file, tmp_path):
        out = str(tmp_path / "out.csv")
        path = make_input_file([GARBAGE_LINE, VALID_LINE])
        result = bulletproof_processor(path, out, output_format="csv")

        assert result["matched"] == 1
        with open(out, encoding="utf-8", newline="") as f:
            reader = list(csv.DictReader(f))
        assert len(reader) == 1


class TestOutputFormatSqlite:
    def test_sqlite_creates_records_table(self, make_input_file, tmp_path):
        out = str(tmp_path / "out.db")
        path = make_input_file([VALID_LINE, VALID_LINE_2])
        result = bulletproof_processor(path, out, output_format="sqlite")

        assert result["matched"] == 2
        conn = sqlite3.connect(out)
        rows = conn.execute("SELECT * FROM records").fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0][0] == "ABC-001"
        assert rows[0][1] == "3D Printer Model X"
        assert rows[0][2] == 299.99
        assert rows[0][3] == 5

    def test_sqlite_garbage_lines_skipped(self, make_input_file, tmp_path):
        out = str(tmp_path / "out.db")
        path = make_input_file([GARBAGE_LINE, VALID_LINE])
        result = bulletproof_processor(path, out, output_format="sqlite")

        assert result["matched"] == 1
        conn = sqlite3.connect(out)
        rows = conn.execute("SELECT * FROM records").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_sqlite_invalid_format_raises(self, make_input_file, tmp_path):
        out = str(tmp_path / "out.xyz")
        path = make_input_file([VALID_LINE])
        with pytest.raises(ValueError, match="Unsupported output_format"):
            bulletproof_processor(path, out, output_format="parquet")


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
