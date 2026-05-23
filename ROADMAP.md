# Roadmap

## Current State — V4.0

The engine is production-ready as a local CLI and importable Python library.
Published on TestPyPI. 63 tests passing across Python 3.10–3.12.

**Shipped in V4.0:**
- Modular fallback chain: `requests` -> `curl_cffi` -> `FlareSolverr` -> `proxy`
- Full error taxonomy: `http_401`, `http_403`, `http_429`, `http_521`, `ssl_error`, `timeout`, `connection_error`, `js_required`
- Parallel probing via `ThreadPoolExecutor(max_workers=10)` — ~8x faster than sequential
- Slack + Discord notifications after each recon run
- `Status`, `Error_Detail`, `Fallback_Module` columns in every output CSV
- Live tested: 91/101 URLs resolved successfully

---

## Tier 1 — Hardened CLI Tool (current focus)

- Publish `dih-engine` to PyPI — `pip install dih-engine`
- FlareSolverr end-to-end validation against real Cloudflare-protected sites in CI
- Playwright end-to-end validation for `js_required` detection on real CSR pages
- Locale-aware amount normalization — handle European format `1.234,50`
- Test coverage from 57% to 80%+

---

## Tier 2 — API Service

Target: data teams that do not want to manage a Python environment.

- FastAPI wrapper with three endpoints:
  - `POST /extract` — submit raw OCR text, receive structured JSONL
  - `POST /sanitize` — submit a single line, receive a cleaned record with status
  - `GET /jobs/{id}` — poll async extraction jobs for large files
- API key authentication (header-based)
- Hosted on Railway or Render
- Pricing: usage-based tiers metered per 10K records

---

## Tier 3 — Scale

Target: production teams running large-scale document processing at 1M+ records/day.

- Native async probing with `aiohttp` — replace `ThreadPoolExecutor` with true async I/O
- Residential proxy rotation middleware for IP-based rate limit bypass
- Playwright grid for high-volume CSR page rendering
- Webhook callbacks on batch job completion
- Multi-tenant data isolation in the API layer
- Streaming extraction — pipeline output as a generator, constant memory footprint

---

## Out of Scope

Real-time streaming ingestion (Kafka, Kinesis) is not planned. The Tier 2 API is
request-response. If stream processing becomes a requirement, it is a separate
architectural decision affecting the storage layer, worker model, and billing model —
treated as a distinct initiative, not a feature added to this engine.
