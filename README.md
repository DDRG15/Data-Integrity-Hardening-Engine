# Data Integrity Hardening Engine (V4)

[![CI](https://github.com/DDRG15/Data-Integrity-Hardening-Engine/actions/workflows/ci.yml/badge.svg)](https://github.com/DDRG15/Data-Integrity-Hardening-Engine/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)

---

OCR-generated text is not clean data — it is a stream of character mutations, phantom tokens, and structural noise. Unstructured receipts, POS exports, and scraped product feeds all arrive with the same problem: `O` where `0` belongs, garbage rows mixed in with real records, and no way to tell how many records were silently dropped.

This engine solves that in three discrete layers, available as a CLI, a Python library, and an HTTP API:

1. **Extraction** — Deterministic regex pipeline that ingests raw text files, applies pattern matching, corrects OCR character confusions, and emits structured JSONL. Designed for large files: constant memory footprint, real-time disk/memory monitoring, and a full audit log of every record dropped.

2. **Sanitizer** — A composable `DataSanitizer` class for line-level OCR cleaning. Zero-trust input model: every line is assumed corrupt until proven structured. Returns `APPROVED` / `PARTIAL` / `REJECTED` status per record so downstream consumers know exactly what they received. Locale-aware amount normalization handles European (`1.234,50`) and US (`1,234.50`) formats.

3. **Recon (Seer V4)** — HTTP probe that identifies the tech stack of a target URL list (Next.js, React, VTEX, Squarespace, Static HTML, JSON API). Classifies every failure by type and automatically activates the correct fallback module, with exponential backoff on rate limits and a per-host circuit breaker. Sends notifications to Slack and Discord after each run.

A **Tier 2 API service** (`dih-engine[api]`) exposes the sanitizer and extraction engine over HTTP with fail-closed API-key auth — see the [API Service](#api-service-tier-2) section.

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
pip install "dih-engine[api]"      # fastapi + uvicorn -- HTTP service (Tier 2)
pip install "dih-engine[full]"     # all of the above

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

# Run the API service (Tier 2)
uvicorn "dih_engine.api:create_app" --factory --port 8000
# or via Docker: DIH_API_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(32))") docker compose up api

# Run the full test suite
pytest
```

---

## API Service (Tier 2)

The engine is also available over HTTP for teams that do not want to manage a Python
environment. Install with `pip install "dih-engine[api]"` and run:

```bash
uvicorn "dih_engine.api:create_app" --factory --port 8000
```

Every data route requires the `X-API-Key` header matching the `DIH_API_KEY` env var.
The service is **fail-closed**: if `DIH_API_KEY` is unset on the server, every data route
returns `503` rather than running open.

| Method | Route | Auth | Purpose |
|--------|-------|------|---------|
| `GET`  | `/health` | none | Liveness probe — returns `{"status":"ok","version":"..."}` |
| `POST` | `/sanitize` | `X-API-Key` | One OCR line → one typed record (`APPROVED`/`PARTIAL`/`REJECTED`/`NOISE`) |
| `POST` | `/extract` | `X-API-Key` | Full OCR text → records + reconciliation audit (`total`/`matched`/`skipped`) |
| `POST` | `/extract/async` | `X-API-Key` | Submit large text, returns `202` + `job_id` |
| `GET`  | `/jobs/{id}` | `X-API-Key` | Poll an async job (`queued`/`running`/`done`/`failed`) |

```bash
# Sanitize one line
curl -H "X-API-Key: $DIH_API_KEY" -H "Content-Type: application/json" \
     -d '{"line":"O01234 SOME PRODUCT 1.234,50"}' \
     http://localhost:8000/sanitize
# {"id":"001234","amount":"1234.50","status":"APPROVED"}
```

`/extract` reuses the same `bulletproof_processor` engine as the CLI, so it inherits every
guardrail: a server disk above threshold returns `507`, never a silent `200` with empty
records. Large payloads belong on `/extract/async` — a synchronous request that takes
minutes is a client timeout, not a feature.

---

## Seer V4 -- Fallback Chain

When a probe fails, the error is classified and the appropriate fallback module is activated automatically:

| Error code | Cause | Fallback module |
|------------|-------|-----------------|
| `http_401` | Site requires authentication (paid API, login wall) | terminal -- no fallback resolves missing credentials |
| `http_403` | WAF / Cloudflare block | `curl_cffi` -> `flaresolverr` -> `proxy` |
| `http_429` | Rate limited | `delay_retry` (10-12s backoff + retry) |
| `http_521` | Cloudflare origin server down | `curl_cffi` (sometimes bypasses) |
| `ssl_error` | TLS handshake mismatch | `curl_cffi` -> `flaresolverr` -> `proxy` |
| `timeout` | Slow site | `delay_retry` |
| `js_required` | CSR-only page (empty body) | `playwright` (headless browser) |
| `connection_error` | DNS failure | terminal -- documented in CSV, no retry |

The output CSV gains three columns per probed URL: `Status`, `Error_Detail`, `Fallback_Module`.

Real-world results from a 101-URL live test (2026-05-21, parallel probing):
- **91 ok** -- direct success
- **3 http_other** -- reqres.in + reuters.com went paid (401), chilli.com.br 521
- **2 http_403** -- centauro.com.br, etsy.com (chain exhausted, proxy needed)
- **2 timeout** -- asos.com (retry → 403), bestbuy.com (retry → timeout)
- **1 ssl_error** -- expired server cert (terminal, correctly buried)
- **1 connection_error** -- DNS failure (terminal)
- **1 connection_error** -- DNS failure (terminal)

### FlareSolverr (second-level fallback, no account needed)

Self-hosted Cloudflare challenge solver. Runs a real Chrome in Docker.

```bash
# Start once (add to docker-compose is already done):
docker compose up -d flaresolverr

# Add to .env:
FLARE_SOLVER_URL=http://localhost:8191/v1
```

FlareSolverr activates automatically after curl_cffi fails. No registration required.

### Proxy rotation (third-level fallback)
When `curl_cffi` also fails on a 403, `proxy_probe` is tried automatically.
Configure one backend in `.env`:

```env
# Option A: any HTTP/SOCKS5 proxy (Oxylabs, BrightData, Smartproxy, etc.)
DIH_PROXY_URL=http://user:pass@proxy.provider.com:8080

# Option B: Scrapfly free tier (https://scrapfly.io)
SCRAPFLY_API_KEY=scp-live-...
```

SOCKS5 support requires `pip install "dih-engine[proxy]"`. If neither is set, the module
documents `module_unavailable` in the CSV and continues without raising.

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
| `DIH_API_KEY` | string | — | Required by every API data route; unset = `503` (fail-closed) |

> **Logging:** This is a library -- it does not configure logging internally. Call `logging.basicConfig(level=logging.DEBUG)` in your own script before importing.

---

## Project Structure

```
src/dih_engine/
├── extraction/
│   ├── engine.py               # Main processing loop + resource monitoring
│   └── patterns.py             # Compiled regex and OCR correction maps
├── sanitizer/
│   └── core.py                 # DataSanitizer class
├── recon/
│   ├── seer.py                 # Orchestrator: probe -> classify -> fallback -> notify
│   ├── error_taxonomy.py       # Maps error codes to fallback module names
│   ├── loading_messages.py     # CLI flavor text: waiting / success / failure phrases
│   └── modules/
│       ├── requests_probe.py       # Default HTTP probe (always available)
│       ├── curlffi_probe.py        # TLS fingerprint bypass [dih-engine[tls]]
│       ├── playwright_probe.py     # Headless browser [dih-engine[browser]]
│       ├── flaresolverr_probe.py   # Self-hosted Cloudflare solver (no account needed)
│       └── proxy_probe.py          # HTTP/SOCKS5 or Scrapfly rotation [dih-engine[proxy]]
├── notifications/
│   ├── slack_notifier.py       # Slack Block Kit report
│   └── discord_notifier.py     # Discord rich embed report
└── api/                        # Tier 2 HTTP service [dih-engine[api]]
    ├── app.py                  # create_app() factory + endpoints
    ├── auth.py                 # X-API-Key dependency (fail-closed)
    ├── schemas.py              # Pydantic request/response contracts
    └── jobs.py                 # In-memory async JobStore
tests/
├── test_extraction.py          # Extraction engine + edge cases
├── test_sanitizer.py           # DataSanitizer + locale amount normalization
├── test_seer.py                # Recon orchestrator + backoff + circuit breaker
├── test_seer_followups.py      # Thread-pool timeout + FlareSolverr error paths
├── test_probe_modules.py       # Direct probe() coverage: requests, curlffi, playwright
├── test_cli.py                 # CLI argument parsing + sys.exit codes
├── test_notifications.py       # Slack + Discord notifiers
└── test_api.py                 # API auth, /sanitize, /extract, async jobs
```

---

## Roadmap

The engine is production-ready for its current scope. The following are deliberate next steps, not gaps:

| Priority | Item | Notes |
|----------|------|-------|
| High | **API deployment** | Deploy the Tier 2 service to Railway or Render with usage-based metering |
| High | **Redis-backed JobStore** | Replace the in-memory job store the moment a second API instance runs behind a load balancer |
| High | **Native async probing** (`aiohttp`) | Replace `ThreadPoolExecutor` with true async I/O for better resource efficiency at scale |
| High | **FlareSolverr live validation** | End-to-end test against real Cloudflare-protected sites (stackoverflow.com, etsy.com) once Docker is in CI |
| Medium | **Playwright live validation** | End-to-end test for `js_required` detection against real CSR-only pages |
| Low | **Streaming extraction** | Pipeline output as a generator instead of collecting all records in memory |
| Low | **~~Test coverage > 80%~~** | **Done — 94%, 198 tests** |
| Low | **~~Exponential backoff in `delay_retry`~~** | **Done — base 5s, 2x, cap 60s, jitter** |
| Low | **~~Locale-aware amount normalization~~** | **Done — `1.234,50` and `1,234.50` via rightmost-separator rule** |

---

## Known Limitations

**Persistent WAF blocks (Seer V4)**
Sites with advanced bot protection (Akamai Enterprise, Cloudflare Pro) block both
`requests` and `curl_cffi`. Live test confirmed: stackoverflow.com, etsy.com, centauro.com.br.
Full chain: `curl_cffi` -> `flaresolverr` (start with `docker compose up -d flaresolverr`)
-> `proxy` (set `DIH_PROXY_URL` or `SCRAPFLY_API_KEY`). Each step activates only if configured.

**Expired server certificates**
`ssl_error` where the remote server has an expired cert (e.g. tricae.com.br) is terminal --
no client-side module resolves a bad server cert. The site is documented in the output CSV
and should be removed from the URL list.

**Mixed-locale amounts in one file**
Amount normalization handles `14,50`, `1.234,50` (European) and `1,234.50` (US) by treating
the rightmost separator as the decimal mark. It does not infer a single locale per file — each
amount is normalized independently. A token with no 2-digit decimal tail (a bare integer, or a
date like `12.06.26`) is correctly not captured as an amount.

**Parallel Recon (10 workers)**
Seer V4 probes up to 10 URLs concurrently via `ThreadPoolExecutor`. At 100 URLs, expect
~1 minute. Aggressive WAF sites may 429 more readily under concurrent load -- `delay_retry`
handles this with exponential backoff. A per-host circuit breaker stops probing a domain
after 3 terminal failures, so a catalog with many URLs on one blocked host does not burn
the full fallback chain on every row. Future: `aiohttp` for true async I/O.

**API job store is in-memory**
The async `/extract/async` job store lives in the API process. This is correct for a single
instance. The moment a second instance runs behind a load balancer, `GET /jobs/{id}` returns
`404` for jobs created on the other instance. Resolution: back the store with Redis (Tier 3).

---

## Changelog

**V4.2.0 (current)**
- Added: Tier 2 API service (`dih-engine[api]`) -- `/health`, `/sanitize`, `/extract`, `/extract/async`, `/jobs/{id}` with fail-closed `X-API-Key` auth
- Added: exponential backoff in `delay_retry` -- base 5s, 2x, cap 60s, jitter, aborts on error-class change
- Added: per-host circuit breaker -- skips remaining URLs of a host after 3 terminal failures
- Added: locale-aware amount normalization -- European `1.234,50` and US `1,234.50`
- Tests: 198 tests, 94% coverage (was 162 tests, 93%)

**V4.1.1**
- Fixed: CI green on all Python versions -- `cffi_requests` / `sync_playwright` now assigned `None` in `except ImportError` so `patch()` works when optional deps are absent
- Fixed: `pythonpath = ["."]` added to pytest config -- `from src.dih_engine` imports reliable in all runner environments

**V4.1**
- Added: loading-screen flavor text (`loading_messages.py`) -- waiting / success / failure phrases forwarded to CLI, Slack, and Discord
- Added: strict URL schema validation -- rejects entries missing `http://` or `https://` before probing
- Hardened: CLI + programmatic input validation for all numeric parameters
- Tests: 162 tests, 93% coverage (was 124 tests, 83%)

**V4.0**
- Added: `ProbeResult` dataclass replaces raw tuples -- every URL gets a typed result
- Added: error taxonomy (`error_taxonomy.py`) -- maps failure codes to fallback modules
- Added: modular fallback chain -- `requests` -> `curl_cffi` -> `flaresolverr` -> `proxy`
- Added: `http_401` error code -- terminal, no fallback (site requires credentials)
- Added: `http_521` error code -- Cloudflare origin down, routes to `curl_cffi`
- Added: `Status`, `Error_Detail`, `Fallback_Module` columns in output CSV
- Added: Intelligence Report probe breakdown (e.g. "91 ok, 3 http_other, 2 http_403")
- Added: Slack notifier -- Block Kit formatted report after each recon run
- Added: Discord notifier -- rich embed with color-coded status after each recon run
- Added: FlareSolverr probe -- self-hosted Cloudflare JS solver, no account needed
- Added: proxy_probe -- generic HTTP/SOCKS5 or Scrapfly as third-level fallback
- Added: parallel probing via `ThreadPoolExecutor(max_workers=10)` -- ~8x faster on 100 URLs
- Added: `[tls]`, `[browser]`, `[proxy]`, `[full]` optional extras in `pyproject.toml`
- Added: `publish.yml` GitHub Actions workflow -- auto-publishes to PyPI on git tag push
- Published: `dih-engine 4.0.0` to TestPyPI -- verified installable
- Live tested: 101 URLs; 91 ok; curl_cffi rescued WAF blocks; delay_retry resolved rate limits

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
