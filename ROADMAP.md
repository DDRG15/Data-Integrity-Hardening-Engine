# Roadmap

## Current State — V4.1

The engine is production-ready as a local CLI and importable Python library.
Published on TestPyPI. **162 tests passing, 93% coverage.**

**Shipped in V4.0:**
- Modular fallback chain: `requests` -> `curl_cffi` -> `FlareSolverr` -> `proxy`
- Full error taxonomy: `http_401`, `http_403`, `http_429`, `http_521`, `ssl_error`, `timeout`, `connection_error`, `js_required`
- Parallel probing via `ThreadPoolExecutor(max_workers=10)` — ~8x faster than sequential
- Slack + Discord notifications after each recon run
- `Status`, `Error_Detail`, `Fallback_Module` columns in every output CSV
- Live tested: 91/101 URLs resolved successfully

**Shipped in V4.1:**
- Loading-screen flavor text (`loading_messages.py`) — 41 waiting / 8 success / 9 failure phrases, forwarded to Slack + Discord
- Strict URL schema validation — rejects entries without `http://` or `https://` scheme before probing
- CLI + programmatic input validation — all numeric parameters guarded with descriptive errors
- URL column pre-filter — strips whitespace, handles `"nan"` strings, raises if all entries blank
- 162 tests, 93% coverage (was 124 tests, 83%)
- `requests_probe` 100%, `proxy_probe` 100%, `curlffi_probe` 90%, `playwright_probe` 91%

---

## Tier 1 — Hardened CLI Tool (current focus)

- [x] Publish `dih-engine` to TestPyPI — verified installable
- [x] Test coverage 80%+ — achieved **93%**, 162 tests
- [ ] Publish to real PyPI — requires `PYPI_API_TOKEN` secret added in GitHub repo settings
- [x] **Exponential backoff in `delay_retry`** — done 2026-06-10: base 5s, multiplier 2x, cap 60s, 0-1s jitter, abort on error class change
- [ ] FlareSolverr end-to-end validation against real Cloudflare-protected sites in CI
- [ ] Playwright end-to-end validation for `js_required` detection on real CSR pages
- [x] Locale-aware amount normalization — done 2026-06-10: `1.234,50` (EU) and `1,234.50` (US) via rightmost-separator rule, no locale detection needed

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
