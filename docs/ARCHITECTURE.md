# Architecture

## Problem Statement

OCR engines produce text that is structurally correct but semantically corrupted. A product ID scanned from a receipt arrives as `O01234` instead of `001234`. A price field arrives as `14,50` or `14.50` depending on the scanner's locale settings. A blacklisted token like `TOTAL` appears on the same line as a legitimate product name like `TOTALIZER CHARGER`.

Standard string parsing fails against this input because it assumes the data is clean. This engine assumes it is not.

---

## Design Principles

**Zero-trust input.** Every line entering the sanitizer is treated as corrupt until it satisfies the extraction pattern. Lines that partially match are flagged `PARTIAL`, not silently promoted or dropped.

**Deterministic correction.** Character substitutions (O→0, l→1, I→1) are applied from an explicit map, not inferred at runtime. If the map is wrong, it is wrong visibly and consistently — not randomly.

**Observable failures.** A run that drops 90% of records must not look identical to a run that drops 0%. The extraction engine emits `total`, `matched`, and `skipped` counts on every run. Silent record loss is a design failure, not an acceptable outcome.

**No mutation of non-ID fields.** OCR correction is applied only to fields where the correction is semantically safe (IDs, numeric codes). Product names are passed through as-is after stripping whitespace. Applying character maps to free-text names produces nonsense and is prohibited.

---

## Module Boundaries

```
┌──────────────────────────────────────────────────────────┐
│  dih_engine.sanitizer.core                               │
│                                                          │
│  Input:  raw string (one line of OCR text)               │
│  Output: { id, amount, status } | None                   │
│                                                          │
│  Responsibility: noise detection, character correction,  │
│  amount normalization. Stateless — no I/O.               │
└──────────────────────┬───────────────────────────────────┘
                       │ used by
┌──────────────────────▼───────────────────────────────────┐
│  dih_engine.extraction.engine                            │
│                                                          │
│  Input:  text file path                                  │
│  Output: JSONL file + summary dict                       │
│                                                          │
│  Responsibility: file I/O, regex matching, resource      │
│  monitoring, record counting. Streaming — O(1) memory.   │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  dih_engine.recon.seer                                   │
│                                                          │
│  Input:  CSV file of URLs                                │
│  Output: CSV master plan + stdout intelligence report    │
│                                                          │
│  Responsibility: HTTP probing, tech stack fingerprinting,│
│  majority vote over N samples, DOM density heuristics,   │
│  exponential backoff, per-host circuit breaker.          │
│  Independent of extraction and sanitizer modules.        │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  dih_engine.api  (optional extra: [api])                 │
│                                                          │
│  Input:  HTTP requests (JSON, X-API-Key header)          │
│  Output: typed JSON responses (Pydantic contracts)       │
│                                                          │
│  Responsibility: transport + auth only. Delegates all    │
│  processing to sanitizer.core and extraction.engine —    │
│  the API owns zero business logic. In-memory JobStore    │
│  for async extraction (single-instance by design).       │
└──────────────────────────────────────────────────────────┘
```

---

## Key Decisions

**`src/` layout over flat layout**
Flat layout makes the package importable from the repo root without installation, which hides missing `__init__.py` files and import path bugs. The `src/` layout forces installation (`pip install -e .`) and surfaces those bugs before CI does.

**`re.match()` over `re.search()` for ID patterns**
The ID extraction regex is anchored with `^` because IDs only appear at the start of a valid line. Using `re.search()` with a `^` anchor produces the same result in most cases but communicates the wrong intent to the reader and breaks silently on multi-line input strings. `re.match()` is the correct call when you mean "anchored to the start."

**Word-boundary blacklist over substring blacklist**
A substring match on `TOTAL` rejects `TOTALIZER CHARGER 9.99`, which is a valid product record. The word-boundary pattern `\bTOTAL\b` rejects only lines where `TOTAL` appears as a standalone token. The cost is a pre-compiled regex per blacklist entry (done once at `__init__` time). The benefit is correctness on real product catalogs.

**Majority vote for tech stack detection**
Sampling one URL and using that result to classify an entire URL list fails the moment the sampled URL is an outlier (a static error page on a React site, a redirect to a CDN). Sampling N URLs and taking the majority makes the detection robust to exactly that failure mode. N=3 is the default; it is configurable via `SEER_SAMPLE_SIZE`.

**Rightmost separator as decimal mark — no locale detection**
`1.234,50` (European) and `1,234.50` (US) are ambiguous only if you try to infer a locale. The amount pattern requires a 2-digit decimal tail, which makes the rightmost separator the decimal mark by construction — every separator before it is a thousands mark. Locale detection would add a failure mode (wrong inference corrupts every amount in the file); the positional rule has none. Tokens without the 2-digit tail (dates like `12.06.26`, bare integers) are correctly not captured as amounts.

**Exponential backoff with abort on error-class change**
A site that returns 429 is asking for time; retrying on a fixed schedule re-triggers the limiter and burns the run's wall clock. Backoff is 5s → 10s → 20s (cap 60s) with 0–1s jitter so the 10 parallel workers do not retry in a synchronized burst. If the error class changes mid-retry (429 → 403), the site escalated from rate-limiting to blocking — waiting longer cannot help, so remaining retries are aborted instead of slept through.

**Per-host circuit breaker, scoped to one run**
A catalog CSV routinely carries dozens of URLs on one domain. Without a breaker, every URL of a WAF-blocked host pays full price for the same answer: another exhausted fallback chain, more wall clock, a worse IP reputation with that WAF. After 3 terminal failures (`http_403`, `http_401`, `ssl_error`, `connection_error`) from one host, remaining URLs of that host are written `skipped_circuit_open` with zero network calls. A successful probe resets the host's strikes. Transient statuses (429, timeout, js_required) never strike — they have their own recovery paths.

**API owns transport, never business logic**
The `/extract` endpoint bridges the HTTP payload to `bulletproof_processor` through tempfiles instead of reimplementing extraction. The day the engine gains a guardrail, the API inherits it the same day — there is no second implementation to drift out of sync. A server disk above threshold surfaces as `507 Insufficient Storage`, never a `200` with silently empty records.

**Fail-closed API authentication**
An operator who forgets to set `DIH_API_KEY` gets a `503` on the first data request — loud, immediate, fixable in minutes. The alternative (running open when no key is configured) is a publicly writable API discovered weeks later. `/health` stays unauthenticated because orchestrator liveness probes cannot carry secrets; a probe that 503s on a missing key restart-loops the container forever. Key comparison uses `secrets.compare_digest` — constant-time, no timing side channel.

**In-memory JobStore with a named replacement trigger**
The async job store lives in the API process: one instance, one store, zero infrastructure. This is correct until the exact moment a second instance runs behind a load balancer — then `GET /jobs/{id}` returns 404 for jobs created on the other instance. That moment, and not earlier, is the Redis migration trigger (documented in `jobs.py` and the ROADMAP). Eviction never touches queued or running jobs: losing an in-flight job means a client polls a 404 for work the server accepted.

---

## Resource Management

The extraction engine monitors disk and memory at 10,000-line intervals. If disk exceeds `DEE_DISK_THRESHOLD` (default 95%), it stops and logs a CRITICAL event — it does not continue writing into a full disk, which would corrupt both the output file and the filesystem. If memory exceeds `DEE_PAUSE_THRESHOLD` (default 80%), it calls `gc.collect()` and sleeps 2 seconds before resuming.

The recon module wraps all HTTP calls in a `requests.Session()` context manager. This ensures TCP connections are reused across probes to the same host and the connection pool is explicitly closed when the session exits, even if an exception occurs mid-run.
