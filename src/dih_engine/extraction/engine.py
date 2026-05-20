"""
Deterministic Extraction Engine
Processes large unstructured text files line-by-line, applies regex matching,
and emits structured JSONL records. Designed for OCR-corrupted data streams.
"""
import gc
import json
import logging
import os
import sys
import time

import psutil

from .patterns import OCR_ID_FIXES, RECORD_PATTERN

logging.basicConfig(
    level=os.getenv("DEE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
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
) -> dict:
    """
    Reads input_file line-by-line, extracts structured records via regex, and
    writes JSONL to output_file. Returns a summary dict with record counts.

    Raises FileNotFoundError if input_file does not exist.
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
        with open(input_file, "r", encoding="utf-8") as f_in, open(
            output_file, "w", encoding="utf-8"
        ) as f_out:
            for i, line in enumerate(f_in):
                total += 1
                match = RECORD_PATTERN.search(line)

                if not match:
                    skipped += 1
                    logger.debug("line=%d unmatched content=%r", i + 1, line[:80])
                    continue

                data = match.groupdict()

                # OCR correction: translate common character confusions in the ID field.
                # Applied only to the ID — product names must not be mutated.
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

                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
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
    import argparse

    parser = argparse.ArgumentParser(
        description="Deterministic Extraction Engine — processes OCR text files into structured JSONL"
    )
    parser.add_argument("--input", required=True, help="Path to input text file")
    parser.add_argument("--output", required=True, help="Path to output JSONL file")
    parser.add_argument(
        "--pause-threshold",
        type=float,
        default=float(os.getenv("DEE_PAUSE_THRESHOLD", "80.0")),
        help="Memory %% at which to trigger GC pause (default: 80.0)",
    )
    parser.add_argument(
        "--disk-threshold",
        type=float,
        default=float(os.getenv("DEE_DISK_THRESHOLD", "95.0")),
        help="Disk %% at which to abort (default: 95.0)",
    )
    args = parser.parse_args()

    result = bulletproof_processor(
        args.input,
        args.output,
        args.pause_threshold,
        args.disk_threshold,
    )
    print(result)
