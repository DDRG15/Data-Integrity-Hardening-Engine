# Data Integrity Hardening Engine (V4)

[![CI](https://github.com/DDRG15/Data-Integrity-Hardening-Engine/actions/workflows/ci.yml/badge.svg)](https://github.com/DDRG15/Data-Integrity-Hardening-Engine/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)

---

OCR-generated text is not clean data — it is a stream of character mutations, phantom tokens, and structural noise. Unstructured receipts, POS exports, and scraped product feeds all arrive with the same problem: `O` where `0` belongs, garbage rows mixed in with real records, and no way to tell how many records were silently dropped.

This engine solves that in three discrete layers:

1. **Extraction** — Deterministic regex pipeline that ingests raw text files, applies pattern matching, corrects OCR character confusions, and emits structured JSONL. Designed for large files: constant memory footprint, real-time disk/memory monitoring, and a full audit log of every record dropped.

2. **Sanitizer** — A composable `DataSanitizer` class for line-level OCR cleaning. Zero-trust input model: every line is assumed corrupt until proven structured. Returns `APPROVED` / `PARTIAL` / `REJECTED` status per record so downstream consumers know exactly what they received.

3. **Recon (Seer V4)** — HTTP probe that identifies the tech stack of a target URL list (Next.js, React, VTEX, Squarespace, Static HTML, JSON API). Classifies every failure by type and automatically activates the correct fallback module. Sends notifications to Slack and Discord after each run.

---

## Architecture

```
Input (raw .txt / OCR stream)
          |
          v
+-----------------------+
|  DataSanitizer        |  <- line-level noise filter + OCR correction
|  sanitizer/core.py    |
+-----------+-----------+
            | clean lines
            v
+-----------------------+
|  Extraction Engine    |  <- regex match -> structured record
|  extraction/          |  <- audit log: total / matched / skipped
+-----------+-----------+
            | structured records
            v
     output.jsonl | output.csv | output.db

URL List (CSV)
          |
          v
+-----------------------+
|  Seer V4 Recon        |  <- HTTP probe -> error classification
|  recon/seer.py        |  <- error taxonomy -> fallback routing
+-----------+-----------+
            |
    [requests_probe]  -- on failure -->  [error_taxonomy]
            |                                   |
            |              http_403 / ssl_error -> [curlffi_probe]
            |              http_429 / timeout  -> [delay_retry]
            |              js_required         -> [playwright_probe]
            v
   master_plan.csv  (Status + Error_Detail + Fallback_Module columns)
          +
   Intelligence Report (stdout + Slack + Discord)
```

---

## Quick Start

```bash
# Install core
pip install -e .

# Install optional fallback modules
pip install "dih-engine[tls]"      # curl_cffi -- WAF bypass
pip install "dih-engine[browser]"  # playwright -- headless browser for JS-only pages
pip install "dih-engine[full]"     # both

# Extract structured records from a raw OCR text file
dih-engine extract --input data/raw_ocr_export.txt --output output/records.jsonl
dih-engine extract --input data/raw_ocr_export.txt --output output/records.csv --output-format csv
dih-engine extract --input data/raw_ocr_export.txt --output output/records.db  --output-format sqlite

# Probe a URL list and produce a tech stack strategy plan
dih-engine recon --input data/urls.csv --output output/recon_plan.csv
dih-engine recon --input data/urls.csv --output output/recon_plan.csv --sample-size 50

# Use DataSanitizer as a library in your own pipeline
from dih_engine import DataSanitizer
sanitizer = DataSanitizer()
result = sanitizer.extract_data("O01234 SOME PRODUCT 14.50")
# {'id': '001234', 'amount': '14.50', 'status': 'APPROVED'}

# Docker (mounts ./data as /data inside the container)
docker compose run --rm extract extract --input /data/raw.txt --output /data/out.jsonl
docker compose run --rm recon recon --input /data/urls.csv --output /data/plan.csv

# Run the full test suite
pytest
```

---

## Seer V4 -- Fallback Chain

When a probe fails, the error is classified and the appropriate fallback module is activated automatically:

| Error code | Cause | Fallback module |
|------------|-------|-----------------|
| `http_403` | WAF / Cloudflare block | `curl_cffi` (TLS fingerprint bypass) |
| `ssl_error` | TLS handshake mismatch | `curl_cffi` |
| `http_429` | Rate limited | `delay_retry` (10-12s backoff + retry) |
| `timeout` | Slow site | `delay_retry` |
| `js_required` | CSR-only page (empty body) | `playwright` (headless browser) |
| `connection_error` | DNS failure | terminal -- documented in CSV, no retry |

The output CSV gains three columns per probed URL: `Status`, `Error_Detail`, `Fallback_Module`.

Real-world results from a 100-URL live test (2026-05-21):
- **87 ok** -- direct success
- **6 http_403** -- WAF blocks; curl_cffi rescued 3, 3 remain (proxy needed)
- **2 timeout** -- delay_retry resolved both
- **1 ssl_error** -- expired server cert (terminal, correctly buried)
- **1 connection_error** -- DNS failure (terminal)

### Proxy rotation (next module)
Sites that block both `requests` and `curl_cffi` (e.g. stackoverflow.com, etsy.com) require
a residential proxy service. This is the next planned module (`proxy_probe.py`).
See [ROADMAP.md](ROADMAP.md).

---

## Notifications

After each recon run, Seer V4 sends an Intelligence Report to all configured channels.
Set env vars in `.env` (copy from `.env.example`):

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Both are optional and independent. Unset = silent no-op.

---

## Configuration

Copy `.env.example` to `.env` and set values before running.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEE_PAUSE_THRESHOLD` | float | `80.0` | Memory % that triggers a GC pause in extraction |
| `DEE_DISK_THRESHOLD` | float | `95.0` | Disk % that aborts extraction |
| `SEER_INPUT_CSV` | string | `seer_mapa_v2.csv` | Default URL list path (overridden by `--input`) |
| `SEER_OUTPUT_FILE` | string | `seer_mapa_master_plan.csv` | Default output path (overridden by `--output`) |
| `SEER_REQUEST_TIMEOUT` | int | `10` | HTTP timeout per probe in seconds |
| `SEER_SAMPLE_SIZE` | int | `3` | URLs sampled for tech stack majority vote |
| `SLACK_WEBHOOK_URL` | string | — | Slack incoming webhook URL |
| `DISCORD_WEBHOOK_URL` | string | — | Discord webhook URL |

> **Logging:** This is a library -- it does not configure logging internally. Call `logging.basicConfig(level=logging.DEBUG)` in your own script before importing.

---

## Project Structure

```
src/dih_engine/
├── extraction/
│   ├── engine.py          # Main processing loop + resource monitoring
│   └── patterns.py        # Compiled regex and OCR correction maps
├── sanitizer/
│   └── core.py            # DataSanitizer class
├── recon/
│   ├── seer.py            # Orchestrator: probe -> classify -> fallback -> notify
│   ├── error_taxonomy.py  # Maps error codes to fallback module names
│   └── modules/
│       ├── requests_probe.py   # Default HTTP probe (always available)
│       ├── curlffi_probe.py    # TLS fingerprint bypass [pip install dih-engine[tls]]
│       └── playwright_probe.py # Headless browser [pip install dih-engine[browser]]
└── notifications/
    ├── slack_notifier.py       # Slack Block Kit report
    └── discord_notifier.py     # Discord rich embed report
tests/
├── test_extraction.py
├── test_sanitizer.py
└── test_seer.py
```

---

## Known Limitations

**Persistent WAF blocks (Seer V4)**
Sites with advanced bot protection (Akamai Enterprise, Cloudflare Pro) block both
`requests` and `curl_cffi`. Live test confirmed: stackoverflow.com, etsy.com, centauro.com.br.
Resolution: `proxy_probe.py` module using a residential proxy service (Scrapfly, ZenRows, Oxylabs).

**Expired server certificates**
`ssl_error` where the remote server has an expired cert (e.g. tricae.com.br) is terminal --
no client-side module resolves a bad server cert. The site is documented in the output CSV
and should be removed from the URL list.

**European Thousand Separators**
Amount normalization handles `14,50` -> `14.50` but not `1.234,50` (period-as-thousands,
comma-as-decimal). Resolution: locale detection before normalization.

**Synchronous Recon**
Seer V4 probes URLs sequentially. At 100 URLs, expect 4-8 minutes. Resolution: async
probe via `aiohttp` (see ROADMAP.md).

---

## Changelog

**V4.0 (current)**
- Added: `ProbeResult` dataclass replaces raw tuples -- every URL gets a typed result
- Added: error taxonomy (`error_taxonomy.py`) -- maps failure codes to fallback modules
- Added: modular fallback chain -- `requests` -> `curl_cffi` -> `playwright` or `delay_retry`
- Added: `Status`, `Error_Detail`, `Fallback_Module` columns in output CSV
- Added: Intelligence Report probe breakdown (e.g. "87 ok, 6 http_403, 2 timeout")
- Added: Slack notifier -- Block Kit formatted report after each recon run
- Added: Discord notifier -- rich embed with color-coded status after each recon run
- Added: `[tls]`, `[browser]`, `[full]` optional extras in `pyproject.toml`
- Live tested: 100 URLs; curl_cffi rescued 3 WAF-blocked sites; delay_retry resolved both 429s

**V3.2**
- Fixed HIGH: `RECORD_PATTERN` regex -- `Name` was capturing `PRICE` and `Stock` content. Fixed with non-greedy `.+?` + `\s*$` anchor.
- Fixed HIGH: `B->8` in `OCR_ID_FIXES` corrupting alphanumeric IDs (`ABC-001` -> `A8C-001`). Removed `B` from translation table.
- Fixed MEDIUM: `logging.basicConfig()` at module import hijacking root logger. Removed.
- Fixed LOW: `pyproject.toml` build backend nonexistent. Corrected to `setuptools.build_meta`.
- Added: `dih-engine` CLI -- `extract` and `recon` subcommands
- Added: `--output-format csv|sqlite` on `extract`
- Added: Dockerfile + docker-compose.yml
- Added: injectable sleep in `analyze_tech_stack` -- tests no longer sleep 1-4s each
- Added: Squarespace detection in Seer
- Refactored: seer.py module-level globals -> function parameters

**V3.1**
- Fixed CRITICAL: product name corruption (`replace("3", "e")` removed)
- Fixed CRITICAL: Windows crash on `psutil.disk_usage('/')` -- derives path from input file drive
- Fixed HIGH: silent record loss -- extraction engine logs total/matched/skipped on every run
- Fixed HIGH: no connection reuse in Seer -- `requests.Session()` wraps all probe calls
- Fixed MEDIUM: `re.search()` + `^` anchor inconsistency -- corrected to `re.match()`
- Fixed MEDIUM: blacklist substring false positives -- whole-word boundary matching
- Fixed MEDIUM: single-URL tech stack sampling -- majority vote over configurable N samples
- Fixed MEDIUM: bare `except:` catching `KeyboardInterrupt` -- specific exception types only
- Added: structured logging, pytest suite, GitHub Actions CI, pyproject.toml

**V3.0**
- Initial PoC: deterministic sanitizer + extraction engine + recon probe
