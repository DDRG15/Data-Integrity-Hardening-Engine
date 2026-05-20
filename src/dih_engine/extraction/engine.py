"""
Deterministic Extraction Engine
Processes large unstructured text files line-by-line, applies regex matching,
and emits structured JSONL records. Designed for OCR-corrupted data streams.
"""
import contextlib
import csv
import gc
import json
import logging
import os
import sqlite3
import sys
import time
from typing import Callable, Generator

import psutil

from .patterns import OCR_ID_FIXES, RECORD_PATTERN

_FIELDS = ["ID", "Name", "Price", "Stock"]


@contextlib.contextmanager
def _open_writer(
    output_file: str, output_format: str
) -> Generator[Callable[[dict], None], None, None]:
    if output_format == "jsonl":
        with open(output_file, "w", encoding="utf-8") as f:
            yield lambda record: f.write(json.dumps(record, ensure_ascii=False) + "\n")

    elif output_format == "csv":
        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDS)
            writer.writeheader()
            yield writer.writerow

    elif output_format == "sqlite":
        conn = sqlite3.connect(output_file)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS records "
                "(ID TEXT, Name TEXT, Price REAL, Stock INTEGER)"
            )

            def _insert(record: dict) -> None:
                conn.execute(
                    "INSERT INTO records VALUES (?,?,?,?)",
                    (record["ID"], record["Name"], record["Price"], record["Stock"]),
                )

            yield _insert
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    else:
        raise ValueError(f"Unsupported output_format: {output_format!r}")

logger = logging.getLogger(__name__)


def _disk_path_for_file(filepath: str) -> str:
    """Returns the disk root path appropriate for the OS and the given file's drive."""
    if sys.platform == "win32":
        drive = os.path.splitdrive(os.path.abspath(filepath))[0]
        return (drive + "\\") if drive else "C:\\"
    return "/"


def bulletproof_processor(
    input_file: str,
    output_file: str,
    pause_threshold: float = 80.0,
    disk_threshold: float = 95.0,
    output_format: str = "jsonl",
) -> dict:
    """
    Reads input_file line-by-line, extracts structured records via regex, and
    writes to output_file in the requested format (jsonl | csv | sqlite).
    Returns a summary dict with record counts.

    Raises FileNotFoundError if input_file does not exist.
    Raises ValueError for unsupported output_format.
    """
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    disk_path = _disk_path_for_file(input_file)

    logger.info("starting extraction input=%s output=%s", input_file, output_file)

    initial_disk = psutil.disk_usage(disk_path).percent
    if initial_disk > disk_threshold:
        logger.critical(
            "disk_full disk=%.1f%% threshold=%.1f%% — aborting before corrupting output",
            initial_disk,
            disk_threshold,
        )
        return {"total": 0, "matched": 0, "skipped": 0, "aborted": True}

    total = matched = skipped = 0

    try:
        with open(input_file, "r", encoding="utf-8") as f_in, _open_writer(
            output_file, output_format
        ) as write_record:
            for i, line in enumerate(f_in):
                total += 1
                match = RECORD_PATTERN.search(line)

                if not match:
                    skipped += 1
                    logger.debug("line=%d unmatched content=%r", i + 1, line[:80])
                    continue

                data = match.groupdict()

                # OCR correction applied only to the ID — product names must not be mutated.
                raw_id = data["id"] or ""
                corrected_id = raw_id.translate(OCR_ID_FIXES)

                price = None
                if data["price"]:
                    try:
                        price = float(data["price"].replace(",", "."))
                    except ValueError:
                        logger.warning(
                            "line=%d unparseable price=%r — stored as null", i + 1, data["price"]
                        )

                record = {
                    "ID": corrected_id,
                    "Name": data["name"].strip() if data["name"] else None,
                    "Price": price,
                    "Stock": int(data["stock"]) if data["stock"] else 0,
                }

                write_record(record)
                matched += 1

                if i > 0 and i % 10_000 == 0:
                    disk_now = psutil.disk_usage(disk_path).percent
                    mem_now = psutil.virtual_memory().percent

                    if disk_now > disk_threshold:
                        logger.critical(
                            "disk_full line=%d disk=%.1f%% — stopping to prevent corruption",
                            i + 1,
                            disk_now,
                        )
                        break

                    if mem_now > pause_threshold:
                        logger.warning(
                            "memory_pressure line=%d mem=%.1f%% — collecting garbage",
                            i + 1,
                            mem_now,
                        )
                        gc.collect()
                        time.sleep(2)

    except PermissionError as exc:
        logger.error("permission_denied: %s", exc)
        raise
    except UnicodeDecodeError as exc:
        logger.error("encoding_error: %s", exc)
        raise

    summary = {"total": total, "matched": matched, "skipped": skipped, "aborted": False}
    logger.info(
        "extraction_complete total=%d matched=%d skipped=%d output=%s",
        total,
        matched,
        skipped,
        output_file,
    )
    return summary


if __name__ == "__main__":
    print("Use 'dih-engine extract --input <file> --output <file>' instead.", flush=True)
    raise SystemExit(1)
