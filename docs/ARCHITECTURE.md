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
│  majority vote over N samples, DOM density heuristics.   │
│  Independent of extraction and sanitizer modules.        │
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

---

## Resource Management

The extraction engine monitors disk and memory at 10,000-line intervals. If disk exceeds `DEE_DISK_THRESHOLD` (default 95%), it stops and logs a CRITICAL event — it does not continue writing into a full disk, which would corrupt both the output file and the filesystem. If memory exceeds `DEE_PAUSE_THRESHOLD` (default 80%), it calls `gc.collect()` and sleeps 2 seconds before resuming.

The recon module wraps all HTTP calls in a `requests.Session()` context manager. This ensures TCP connections are reused across probes to the same host and the connection pool is explicitly closed when the session exits, even if an exception occurs mid-run.
