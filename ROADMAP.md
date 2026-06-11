# Roadmap

## Current State — V4.2

The engine is production-ready as a local CLI, an importable Python library, and a
runnable HTTP API. Published on TestPyPI. **198 tests passing, 94% coverage.**

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

**Shipped in V4.2:**
- Tier 2 API service (`dih-engine[api]`): `/health`, `/sanitize`, `/extract`, `/extract/async`, `/jobs/{id}` with fail-closed `X-API-Key` auth
- Exponential backoff in `delay_retry` — base 5s, 2x, cap 60s, jitter, aborts on error-class change
- Per-host circuit breaker — skips remaining URLs of a host after 3 terminal failures
- Locale-aware amount normalization — European `1.234,50` and US `1,234.50`
- 198 tests, 94% coverage

---

## Tier 1 — Hardened CLI Tool

- [x] Publish `dih-engine` to TestPyPI — verified installable
- [x] Test coverage 80%+ — achieved **94%**, 198 tests
- [ ] Publish to real PyPI — requires `PYPI_API_TOKEN` secret added in GitHub repo settings
- [x] **Exponential backoff in `delay_retry`** — done 2026-06-10: base 5s, multiplier 2x, cap 60s, 0-1s jitter, abort on error class change
- [x] **Per-host circuit breaker** — done 2026-06-10: 3 terminal failures opens the host for the run
- [ ] FlareSolverr end-to-end validation against real Cloudflare-protected sites in CI
- [ ] Playwright end-to-end validation for `js_required` detection on real CSR pages
- [x] Locale-aware amount normalization — done 2026-06-10: `1.234,50` (EU) and `1,234.50` (US) via rightmost-separator rule, no locale detection needed
- [ ] `--retry` second-pass flag — re-probe only the non-ok rows of a previous output CSV (deferred re-run instead of in-process standby)
- [ ] `@pytest.mark.live` smoke tests against `httpbin.org` — excluded from CI, run manually

---

## Tier 2 — API Service

Target: data teams that do not want to manage a Python environment.

- [x] FastAPI wrapper, scaffold shipped V4.2:
  - [x] `POST /sanitize` — single line in, cleaned record with status out
  - [x] `POST /extract` — raw OCR text in, structured records + audit out
  - [x] `POST /extract/async` + `GET /jobs/{id}` — async jobs for large files
  - [x] `GET /health` — unauthenticated liveness probe
- [x] API key authentication (header-based, fail-closed)
- [x] Dockerfile.api + docker-compose `api` service
- [ ] Deploy to Railway or Render — needs hosting account
- [ ] Usage metering + pricing tiers per 10K records
- [ ] Redis-backed `JobStore` — required the moment a second instance runs behind a load balancer

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
