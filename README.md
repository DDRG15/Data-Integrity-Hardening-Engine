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
          │ JSONL records
          ▼
     output.jsonl

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
# Install runtime dependencies
pip install -r requirements.txt
pip install -e .

# Extract structured records from a raw OCR text file
python -m dih_engine.extraction.engine \
    --input data/raw_ocr_export.txt \
    --output output/structured_records.jsonl

# Run the sanitizer as a standalone smoke test
python -m dih_engine.sanitizer.core

# Run the recon probe against a URL list
SEER_INPUT_CSV=data/urls.csv python -m dih_engine.recon.seer

# Run the full test suite
pip install -r requirements-dev.txt
pytest
```

---

## Configuration

Copy `.env.example` to `.env` and set values before running. All parameters can also be passed as environment variables directly.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEE_LOG_LEVEL` | string | `INFO` | Log level for the extraction engine |
| `DEE_PAUSE_THRESHOLD` | float | `80.0` | Memory % that triggers a GC pause |
| `DEE_DISK_THRESHOLD` | float | `95.0` | Disk % that aborts the process |
| `SC_LOG_LEVEL` | string | `INFO` | Log level for the sanitizer |
| `SEER_INPUT_CSV` | string | `seer_mapa_v2.csv` | Path to URL list CSV |
| `SEER_OUTPUT_FILE` | string | `seer_mapa_master_plan.csv` | Output path for the master plan |
| `SEER_REQUEST_TIMEOUT` | int | `10` | HTTP timeout per probe (seconds) |
| `SEER_SAMPLE_SIZE` | int | `3` | URLs sampled for tech stack majority vote |
| `SEER_LOG_LEVEL` | string | `INFO` | Log level for the recon module |

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

**V3.1 (current)**
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
