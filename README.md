# Data Integrity Hardening Engine (V3)

[![CI](https://github.com/DDRG15/Data-Integrity-Hardening-Engine/actions/workflows/ci.yml/badge.svg)](https://github.com/DDRG15/Data-Integrity-Hardening-Engine/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)

---

OCR-generated text is not clean data — it is a stream of character mutations, phantom tokens, and structural noise. Unstructured receipts, POS exports, and scraped product feeds all arrive with the same problem: `O` where `0` belongs, garbage rows mixed in with real records, and no way to tell how many records were silently dropped.

This engine solves that in three discrete layers:

1. **Extraction** — Deterministic regex pipeline that ingests raw text files, applies pattern matching, corrects OCR character confusions, and emits structured JSONL. Designed for large files: constant memory footprint, real-time disk/memory monitoring, and a full audit log of every record dropped.

2. **Sanitizer** — A composable `DataSanitizer` class for line-level OCR cleaning. Zero-trust input model: every line is assumed corrupt until proven structured. Returns `APPROVED` / `PARTIAL` / `REJECTED` status per record so downstream consumers know exactly what they received.

3. **Recon (Seer V3)** — HTTP probe that identifies the tech stack of a target URL list (Next.js, React, VTEX, Static HTML, JSON API) and produces a strategic extraction plan. Uses multi-URL majority sampling to avoid false reads from anomalous pages.

---

## Architecture

```
Input (raw .txt / OCR stream)
          │
          ▼
┌─────────────────────┐
│  DataSanitizer      │  ← line-level noise filter + OCR correction
│  sanitizer/core.py  │
└─────────┬───────────┘
          │ clean lines
          ▼
┌─────────────────────┐
│  Extraction Engine  │  ← regex match → structured record
│  extraction/        │  ← audit log: total / matched / skipped
└─────────┬───────────┘
          │ structured records
          ▼
     output.jsonl | output.csv | output.db

URL List (CSV)
          │
          ▼
┌─────────────────────┐
│  Seer V3 Recon      │  ← HTTP probe → tech stack detection
│  recon/seer.py      │  ← majority vote over N sample URLs
└─────────┬───────────┘
          │
          ▼
   master_plan.csv  +  Intelligence Report (stdout)
```

---

## Quick Start

```bash
# Install
pip install -r requirements.txt
pip install -e .

# Extract structured records from a raw OCR text file
dih-engine extract --input data/raw_ocr_export.txt --output output/records.jsonl
dih-engine extract --input data/raw_ocr_export.txt --output output/records.csv --output-format csv
dih-engine extract --input data/raw_ocr_export.txt --output output/records.db  --output-format sqlite

# Probe a URL list and produce a tech stack strategy plan
dih-engine recon --input data/urls.csv --output output/recon_plan.csv

# Use DataSanitizer as a library in your own pipeline
from dih_engine import DataSanitizer
sanitizer = DataSanitizer()
result = sanitizer.extract_data("O01234 SOME PRODUCT 14.50")
# {'id': '001234', 'amount': '14.50', 'status': 'APPROVED'}

# Docker (mounts ./data as /data inside the container)
docker compose run --rm extract extract --input /data/raw.txt --output /data/out.jsonl
docker compose run --rm recon recon --input /data/urls.csv --output /data/plan.csv

# Run the full test suite
pip install -r requirements-dev.txt
pytest
```

---

## Configuration

Copy `.env.example` to `.env` and set values before running. All parameters can also be passed as environment variables directly.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEE_PAUSE_THRESHOLD` | float | `80.0` | Memory % that triggers a GC pause in the extraction engine |
| `DEE_DISK_THRESHOLD` | float | `95.0` | Disk % that aborts the extraction process |
| `SEER_INPUT_CSV` | string | `seer_mapa_v2.csv` | Default path to URL list CSV (overridden by `--input`) |
| `SEER_OUTPUT_FILE` | string | `seer_mapa_master_plan.csv` | Default output path for the master plan (overridden by `--output`) |
| `SEER_REQUEST_TIMEOUT` | int | `10` | HTTP timeout per probe in seconds (overridden by `--timeout`) |
| `SEER_SAMPLE_SIZE` | int | `3` | URLs sampled for tech stack majority vote (overridden by `--sample-size`) |

> **Logging:** This is a library — it does not configure logging internally. To enable debug output, call `logging.basicConfig(level=logging.DEBUG)` in your own script before importing.

---

## Running Tests

```bash
pytest
```

With coverage:
```bash
pytest --cov=src/dih_engine --cov-report=term-missing
```

The test suite covers:
- Happy path extraction and sanitization
- Regression for all CRITICAL/HIGH bugs (see Changelog below)
- OCR character correction
- Windows disk path compatibility (`psutil.disk_usage` never called with `/` on Windows)
- Network failure handling in the recon probe (timeout, connection error, HTTP 4xx/5xx)
- Edge cases: empty files, missing CSV columns, unparseable amounts, empty lines

---

## Project Structure

```
src/dih_engine/
├── extraction/
│   ├── engine.py      # Main processing loop + resource monitoring
│   └── patterns.py    # Compiled regex and OCR correction maps
├── sanitizer/
│   └── core.py        # DataSanitizer class
└── recon/
    └── seer.py        # HTTP probe + tech stack fingerprinting
tests/
├── conftest.py
├── test_extraction.py
├── test_sanitizer.py
└── test_seer.py
docs/
├── ARCHITECTURE.md
└── ADR-001-extraction-strategy.md
```

---

## Known Limitations

**TLS Fingerprinting (Seer V3)**
The `requests` library exposes a default Python JA3 fingerprint. Enterprise WAFs identify and block it within milliseconds on protected sites. This is wrong the moment you aim it at Akamai or Cloudflare. Resolution path: swap `requests` for `curl_cffi`, or route through a managed proxy service (Scrapfly, ZenRows). See [ROADMAP.md](ROADMAP.md) for the V4 Swarm Protocol.

**European Thousand Separators**
Amount normalization handles `14,50` → `14.50` correctly but not `1.234,50` (period-as-thousands, comma-as-decimal). This is wrong the moment your data source uses European locale formatting. Resolution: locale detection before normalization.

**Synchronous Recon**
Seer V3 probes URLs sequentially with 1–3.5s entropy delays. At 100 URLs, expect a 3–6 minute runtime. Resolution: V4 async probe via `aiohttp` + `asyncio` (see [ROADMAP.md](ROADMAP.md)).

---

## Changelog

**V3.2 (current)**
- Fixed HIGH: `RECORD_PATTERN` regex — `Name` was capturing `PRICE` and `Stock` content; `Price`/`Stock` output as `null`/`0`. Root cause: `[^|]+` greedy with no end anchor. Fixed with non-greedy `.+?` + `\s*$` anchor.
- Fixed HIGH: `B→8` in `OCR_ID_FIXES` was corrupting alphanumeric IDs (`ABC-001` → `A8C-001`). Removed `B` from translation table.
- Fixed MEDIUM: `logging.basicConfig()` called at module import in all three modules — was hijacking the root logger of any app that imported the library. Removed.
- Fixed LOW: `pyproject.toml` build backend was `setuptools.backends.legacy:build` (nonexistent). Corrected to `setuptools.build_meta`.
- Added: `dih-engine` CLI entry point — `extract` and `recon` commands
- Added: `--output-format csv|sqlite` support on `extract` command
- Added: `Dockerfile` + `docker-compose.yml`
- Added: `.gitignore` + `.dockerignore`
- Added: public API surface via `__init__.py` — `from dih_engine import DataSanitizer` now works
- Added: injectable sleep in `analyze_tech_stack` — test suite no longer sleeps 1–4s per test
- Refactored: `seer.py` module-level globals → function parameters — library-safe, testable without env mutation

**V3.1**
- Fixed CRITICAL: product name corruption (`replace("3", "e")` removed — was corrupting every name containing the digit 3)
- Fixed CRITICAL: Windows crash on `psutil.disk_usage('/')` — now derives disk path from the input file's drive letter
- Fixed HIGH: silent record loss — extraction engine now logs `total/matched/skipped` counts on every run
- Fixed HIGH: no connection reuse in Seer — `requests.Session()` now wraps all probe calls
- Fixed MEDIUM: `re.search()` + `^` anchor inconsistency in sanitizer — corrected to `re.match()`
- Fixed MEDIUM: blacklist substring false positives (`TOTALIZER` no longer triggers `TOTAL`) — whole-word boundary matching
- Fixed MEDIUM: single-URL tech stack sampling — majority vote over configurable N samples
- Fixed MEDIUM: bare `except:` in Seer catching `KeyboardInterrupt` — specific exception types only
- Added: structured logging across all modules (timestamps, levels, context fields)
- Added: argparse CLI for the extraction engine
- Added: pytest suite with regression coverage for all critical fixes
- Added: GitHub Actions CI (Python 3.10 / 3.11 / 3.12)
- Added: `pyproject.toml`, pinned `requirements.txt`, `.env.example`

**V3.0**
- Initial PoC: deterministic sanitizer + extraction engine + recon probe
