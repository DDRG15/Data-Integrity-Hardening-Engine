# Roadmap

## Current State — V3.1 (Production-Hardened PoC)

The engine is a hardened, tested, and packaged Python library. All CRITICAL and HIGH bugs from V3.0 are resolved. The test suite enforces regressions. CI runs on every push across Python 3.10–3.12.

What it is: a local, synchronous data processing tool. What it is not yet: a service anyone can call over a network.

---

## Tier 1 — Developer Tool (Weeks 1–4)

Target audience: data engineers and SDETs who process OCR exports and need a reliable sanitization layer in their pipelines.

- Package published to PyPI as `dih-engine`
- `pip install dih-engine` installs the CLI and the importable library
- `--output-format csv|jsonl|sqlite` flag on the extraction engine
- `DataSanitizer` usable as a drop-in import in any Python pipeline
- Distribution: direct link, GitHub, or $50 one-time license for custom regex rule sets

---

## Tier 2 — API Service (Month 2–3)

Target audience: teams that do not want to manage a Python environment. They POST data, they get structured records back.

- FastAPI wrapper exposing three endpoints:
  - `POST /extract` — submit raw text, receive structured JSONL
  - `POST /sanitize` — submit a single line, receive a cleaned record with status
  - `GET /jobs/{id}` — poll async extraction jobs for large files
- API key authentication (header-based, issued on signup)
- Hosted on Railway or Render — no infrastructure to manage
- Pricing: $9/month entry tier (up to 100K records/month), $49/month growth tier

---

## Tier 3 — V4 Swarm Protocol (Month 4+)

Target audience: production data teams running large-scale competitive intelligence, price monitoring, or document processing at 1M+ records/day.

- **Async execution**: replace `requests` with `aiohttp` + `asyncio` — probe 100+ URLs concurrently
- **Proxy rotation**: residential proxy middleware to defeat IP-based rate limiting
- **Headless browser array**: Playwright grid for React/Next.js SPAs where `requests` sees an empty `<div id="root">`
- **TLS spoofing**: `curl_cffi` to defeat JA3 fingerprinting on WAF-protected sites
- **Webhook callbacks**: POST to a client endpoint when a large batch job completes
- **Multi-tenant isolation**: per-tenant data separation in the API layer
- **Usage-based billing**: per 10K records processed, metered via Stripe

---

## What This Roadmap Does Not Include

Real-time streaming ingestion (Kafka, Kinesis) is not planned for Tier 2. The Tier 2 API is request-response, not a streaming pipeline. If stream processing becomes a requirement, that is a separate architectural decision that would change the storage layer, the worker model, and the billing model simultaneously — and it would be treated as a V5 initiative, not a feature flag on Tier 2.
