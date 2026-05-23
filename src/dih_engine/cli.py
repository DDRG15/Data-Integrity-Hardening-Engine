import argparse
import os
import sys

from .extraction import bulletproof_processor

# Force UTF-8 on stdout/stderr at the CLI entry point.
# Without this, Windows consoles running cp1252 crash on any non-ASCII character
# (em dashes, arrows, accented letters) printed anywhere in the process.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dih-engine",
        description="Data Integrity Hardening Engine -- OCR extraction and sanitization",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── extract ──────────────────────────────────────────────────────────────
    ex = subparsers.add_parser(
        "extract",
        help="Extract structured records from an OCR text file",
    )
    ex.add_argument("--input", required=True, help="Path to input text file")
    ex.add_argument("--output", required=True, help="Path to output file")
    ex.add_argument(
        "--output-format",
        choices=["jsonl", "csv", "sqlite"],
        default="jsonl",
        help="Output format: jsonl (default), csv, or sqlite",
    )
    ex.add_argument(
        "--pause-threshold",
        type=float,
        default=float(os.getenv("DEE_PAUSE_THRESHOLD", "80.0")),
        help="Memory %% at which to trigger GC pause (default: 80.0)",
    )
    ex.add_argument(
        "--disk-threshold",
        type=float,
        default=float(os.getenv("DEE_DISK_THRESHOLD", "95.0")),
        help="Disk %% at which to abort (default: 95.0)",
    )

    # ── recon ─────────────────────────────────────────────────────────────────
    rc = subparsers.add_parser(
        "recon",
        help="Probe a URL list and produce a tech stack extraction strategy",
    )
    rc.add_argument("--input", required=True, help="Path to input CSV with a URL column")
    rc.add_argument("--output", required=True, help="Path to output CSV master plan")
    rc.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("SEER_REQUEST_TIMEOUT", "10")),
        help="HTTP timeout per probe in seconds (default: 10)",
    )
    rc.add_argument(
        "--sample-size",
        type=int,
        default=int(os.getenv("SEER_SAMPLE_SIZE", "3")),
        help="URLs sampled for tech stack majority vote (default: 3)",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "extract":
        if not 0 < args.pause_threshold < 100:
            print("error: --pause-threshold must be between 0 and 100", file=sys.stderr)
            sys.exit(1)
        if not 0 < args.disk_threshold < 100:
            print("error: --disk-threshold must be between 0 and 100", file=sys.stderr)
            sys.exit(1)

        try:
            result = bulletproof_processor(
                args.input,
                args.output,
                args.pause_threshold,
                args.disk_threshold,
                args.output_format,
            )
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)

        if result.get("aborted"):
            print("error: extraction aborted -- disk full before completion", file=sys.stderr)
            sys.exit(2)

        print(
            f"extracted {result['matched']} records "
            f"({result['skipped']} skipped) -> {args.output}"
        )

    elif args.command == "recon":
        if args.timeout <= 0:
            print("error: --timeout must be a positive integer", file=sys.stderr)
            sys.exit(1)
        if args.sample_size <= 0:
            print("error: --sample-size must be a positive integer", file=sys.stderr)
            sys.exit(1)

        from .recon import clean_and_optimize_map

        try:
            clean_and_optimize_map(
                input_file=args.input,
                output_file=args.output,
                request_timeout=args.timeout,
                sample_size=args.sample_size,
            )
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
