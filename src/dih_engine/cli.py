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

    # ── config ────────────────────────────────────────────────────────────────
    cf = subparsers.add_parser(
        "config",
        help="Manage .env credentials without hand-editing -- list, set, unset",
    )
    cf_sub = cf.add_subparsers(dest="config_command", required=True)

    cf_list = cf_sub.add_parser("list", help="Show every variable: status, masked value, dates")
    cf_list.add_argument("--env-file", default=".env", help="Path to .env (default: .env)")
    cf_list.add_argument("--meta-file", default=".env.meta.json", help="Path to metadata file")

    cf_set = cf_sub.add_parser("set", help="Set or rotate a variable (hidden prompt for secrets)")
    cf_set.add_argument("name", help="Variable name, e.g. SCRAPFLY_API_KEY")
    cf_set.add_argument(
        "--value",
        default=None,
        help="Value (omit to be prompted -- hidden input for secrets; "
             "note: --value lands in shell history, prefer the prompt for secrets)",
    )
    cf_set.add_argument("--provider", default=None, help='Optional label, e.g. "Scrapfly free tier"')
    cf_set.add_argument("--env-file", default=".env", help="Path to .env (default: .env)")
    cf_set.add_argument("--meta-file", default=".env.meta.json", help="Path to metadata file")

    cf_unset = cf_sub.add_parser("unset", help="Remove a variable (expired/rotated-out key)")
    cf_unset.add_argument("name", help="Variable name to remove")
    cf_unset.add_argument("--env-file", default=".env", help="Path to .env (default: .env)")
    cf_unset.add_argument("--meta-file", default=".env.meta.json", help="Path to metadata file")

    return parser


def _run_config(args) -> None:
    from . import config_store

    if args.config_command == "list":
        rows = config_store.list_vars(args.env_file, args.meta_file)
        name_w = max(len(r["name"]) for r in rows)
        val_w = max(len(r["display"]) for r in rows)
        header = f"{'VARIABLE':<{name_w}}  {'VALUE':<{val_w}}  {'SET':<10}  {'ROTATED':<10}  PROVIDER"
        print(header)
        print("-" * len(header))
        for r in rows:
            print(
                f"{r['name']:<{name_w}}  {r['display']:<{val_w}}  "
                f"{r['set_at']:<10}  {r['rotated_at']:<10}  {r['provider']}"
            )

    elif args.config_command == "set":
        value = args.value
        if value is None:
            spec = config_store.KNOWN_VARS.get(args.name)
            if spec and spec["secret"]:
                import getpass
                value = getpass.getpass(f"{args.name} (hidden): ")
            else:
                value = input(f"{args.name}: ")
        try:
            entry = config_store.set_var(
                args.name, value, args.env_file, args.meta_file, provider=args.provider
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        masked = f" (****{entry['last4']})" if "last4" in entry else ""
        action = "rotated" if entry.get("rotated_at") else "set"
        print(f"{args.name} {action}{masked} -> {args.env_file}")

    elif args.config_command == "unset":
        try:
            config_store.unset_var(args.name, args.env_file, args.meta_file)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"{args.name} removed from {args.env_file}")


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

    elif args.command == "config":
        _run_config(args)
