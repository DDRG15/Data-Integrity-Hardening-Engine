"""
Credential and configuration store for the .env file.

The problem this solves: asking an operator to hand-edit .env means hunting
for placeholders, guessing variable names, and leaving no record of when a
key was added or rotated. When a key expires three months later, nobody
remembers which one it was or when it went in.

Design:
  - Values live ONLY in .env (gitignored). This module never logs, prints,
    or copies a secret value anywhere else.
  - Metadata lives in .env.meta.json (gitignored): set date, rotation date,
    optional provider label, and the last 4 characters of secret values --
    enough to distinguish keys without exposing them (same convention as
    credit card statements).
  - Unknown variable names are rejected: a typo like DIH_API_KEYY would
    otherwise write a dead variable and the operator would debug a 503 for
    an hour. The registry below is the contract.
  - .env writes are atomic (tempfile + os.replace): a crash mid-write can
    not truncate the operator's credential file.

This module owns the logic; the CLI (and any future local UI) is a thin
layer on top.
"""
import json
import logging
import os
import tempfile
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

ENV_FILE = ".env"
META_FILE = ".env.meta.json"

# The registry: every variable the engine reads, and whether its value is a
# secret. Secrets get hidden prompts, masked display, and last-4 metadata.
# Non-secrets (thresholds, paths) are shown as-is -- masking "80.0" is theater.
KNOWN_VARS: dict[str, dict] = {
    "DEE_PAUSE_THRESHOLD":  {"secret": False, "description": "Memory % that triggers GC pause in extraction"},
    "DEE_DISK_THRESHOLD":   {"secret": False, "description": "Disk % that aborts extraction"},
    "SEER_INPUT_CSV":       {"secret": False, "description": "Default URL list path for recon"},
    "SEER_OUTPUT_FILE":     {"secret": False, "description": "Default recon output path"},
    "SEER_REQUEST_TIMEOUT": {"secret": False, "description": "HTTP timeout per probe (seconds)"},
    "SEER_SAMPLE_SIZE":     {"secret": False, "description": "URLs sampled for tech stack vote"},
    "FLARE_SOLVER_URL":     {"secret": False, "description": "FlareSolverr endpoint (self-hosted)"},
    "SLACK_WEBHOOK_URL":    {"secret": True,  "description": "Slack incoming webhook"},
    "DISCORD_WEBHOOK_URL":  {"secret": True,  "description": "Discord webhook"},
    "DIH_PROXY_URL":        {"secret": True,  "description": "HTTP/SOCKS5 proxy URL (may embed user:pass)"},
    "SCRAPFLY_API_KEY":     {"secret": True,  "description": "Scrapfly managed proxy API key"},
    "DIH_API_KEY":          {"secret": True,  "description": "API service auth key (X-API-Key)"},
}


def _last4(value: str) -> str:
    """Last 4 characters of a secret -- or full mask when too short to be safe."""
    return value[-4:] if len(value) >= 8 else "****"


def _read_lines(env_path: str) -> list[str]:
    if not os.path.exists(env_path):
        return []
    with open(env_path, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def _write_atomic(env_path: str, lines: list[str]) -> None:
    """tempfile + os.replace: a crash mid-write cannot truncate the file."""
    directory = os.path.dirname(os.path.abspath(env_path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".env.tmp.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp_path, env_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _load_meta(meta_path: str) -> dict:
    if not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("config_meta_unreadable path=%s -- starting fresh", meta_path)
        return {}


def _save_meta(meta_path: str, meta: dict) -> None:
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


def _current_values(lines: list[str]) -> dict[str, str]:
    """Parse KEY=VALUE pairs; comments and blanks are ignored, never modified."""
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def set_var(
    name: str,
    value: str,
    env_path: str = ENV_FILE,
    meta_path: str = META_FILE,
    provider: Optional[str] = None,
) -> dict:
    """
    Sets or rotates a variable in .env. Preserves every comment and every
    line this module does not own. Returns the metadata entry (never the value).
    """
    if name not in KNOWN_VARS:
        valid = ", ".join(sorted(KNOWN_VARS))
        raise ValueError(f"unknown variable {name!r} -- valid names: {valid}")
    if not value or not value.strip():
        raise ValueError("value must not be empty")
    value = value.strip()
    if "\n" in value or "\r" in value:
        raise ValueError("value must be a single line")

    lines = _read_lines(env_path)
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{name}="):
            lines[i] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")
    _write_atomic(env_path, lines)

    meta = _load_meta(meta_path)
    today = date.today().isoformat()
    entry = meta.get(name, {})
    if entry:
        entry["rotated_at"] = today
    else:
        entry = {"set_at": today, "rotated_at": None}
    if KNOWN_VARS[name]["secret"]:
        entry["last4"] = _last4(value)
    if provider is not None:
        entry["provider"] = provider
    meta[name] = entry
    _save_meta(meta_path, meta)

    logger.info("config_set name=%s rotated=%s", name, replaced)
    return entry


def unset_var(name: str, env_path: str = ENV_FILE, meta_path: str = META_FILE) -> None:
    """Removes a variable from .env and its metadata. Raises if not present."""
    if name not in KNOWN_VARS:
        valid = ", ".join(sorted(KNOWN_VARS))
        raise ValueError(f"unknown variable {name!r} -- valid names: {valid}")

    lines = _read_lines(env_path)
    kept = [line for line in lines if not line.strip().startswith(f"{name}=")]
    if len(kept) == len(lines):
        raise ValueError(f"{name} is not set in {env_path}")
    _write_atomic(env_path, kept)

    meta = _load_meta(meta_path)
    meta.pop(name, None)
    _save_meta(meta_path, meta)
    logger.info("config_unset name=%s", name)


def list_vars(env_path: str = ENV_FILE, meta_path: str = META_FILE) -> list[dict]:
    """
    Returns one row per known variable plus any unknown ones found in .env.
    Secret values are never returned -- only their masked form.
    """
    values = _current_values(_read_lines(env_path))
    meta = _load_meta(meta_path)
    rows: list[dict] = []

    for name, spec in KNOWN_VARS.items():
        raw = values.get(name, "")
        is_set = bool(raw)
        entry = meta.get(name, {})
        if not is_set:
            display = "(not set)"
        elif spec["secret"]:
            # Prefer the recorded last4; a hand-edited .env has no metadata.
            display = "****" + entry.get("last4", "????")
        else:
            display = raw
        rows.append({
            "name": name,
            "secret": spec["secret"],
            "set": is_set,
            "display": display,
            "set_at": entry.get("set_at", "-"),
            "rotated_at": entry.get("rotated_at") or "-",
            "provider": entry.get("provider", "-"),
            "description": spec["description"],
        })

    # Unknown vars in .env: report their existence, mask their value -- we
    # cannot know whether a variable we do not recognize is a secret.
    for name in sorted(set(values) - set(KNOWN_VARS)):
        rows.append({
            "name": name, "secret": True, "set": True, "display": "**** (unknown var)",
            "set_at": "-", "rotated_at": "-", "provider": "-",
            "description": "(not in registry -- hand-added)",
        })
    return rows
