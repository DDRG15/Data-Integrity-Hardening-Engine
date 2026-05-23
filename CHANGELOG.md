# Changelog — dih-engine

All version history in reverse-chronological order.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [4.0.0] — 2026-05-23

### Added
- **Seer V4 — modular fallback chain**: requests → curl_cffi → FlareSolverr → proxy rotation.
  Each failed probe triggers the appropriate fallback module based on `error_taxonomy.py`.
- **`ProbeResult` dataclass**: typed probe result replaces raw dicts. Fields: `url`, `status`,
  `tech`, `strategy`, `mines`, `error_detail`, `fallback_module`.
- **`error_taxonomy.py`**: central `FALLBACK_MAP` dict mapping error codes to module names.
  `http_403 / ssl_error → curl_cffi`, `http_429 / timeout → delay_retry`,
  `js_required → playwright`, `http_521 → curl_cffi`, `http_401 → terminal (no fallback)`.
- **`curlffi_probe`**: TLS fingerprint bypass via `curl-cffi`. Optional dep: `pip install "dih-engine[tls]"`.
- **`flaresolverr_probe`**: self-hosted Cloudflare solver. No account needed.
  Requires `docker compose up -d flaresolverr` and `FLARE_SOLVER_URL` in `.env`.
- **`proxy_probe`**: residential proxy rotation as third-level fallback.
  Supports `DIH_PROXY_URL` (any HTTP/SOCKS5 proxy) and `SCRAPFLY_API_KEY` (managed SaaS).
  Credential redaction: `user:pass` stripped from all log lines and CSV output via `_redact()`.
- **Slack + Discord notifications**: `notify_all()` fires after each recon run.
  Block Kit for Slack, rich embeds for Discord. Both are optional — no webhook = silent no-op.
- **`ThreadPoolExecutor` parallel probing**: up to 10 concurrent probe threads.
  Wall-clock timeout prevents hung TCP sockets from freezing the CLI indefinitely.
  Partial results collected on timeout; unprobed URLs marked `"not_probed"` in output CSV.
- **`_is_valid_url()` pre-validation**: malformed entries (`"N/A"`, empty strings) get
  `status="invalid_url"` without attempting any network call.
- **`http_401` / `http_521` error codes**: 401 is terminal (no fallback can authenticate).
  521 (Cloudflare origin down) routes to `curl_cffi`.
- **Output CSV columns**: `Status`, `Error_Detail`, `Fallback_Module` appended to every row.
  Console report shows probe breakdown and fallback usage counts.
- **Optional extras in `pyproject.toml`**: `[tls]`, `[browser]`, `[proxy]`, `[full]`.
- **GitHub Actions `publish.yml`**: twine + API token approach. Tag `v*` → test + publish
  to TestPyPI → publish to PyPI. Requires secrets: `TEST_PYPI_API_TOKEN`, `PYPI_API_TOKEN`.

### Fixed
- Notification failure no longer aborts CSV write. `notify_all()` wrapped in try/except.
- `datetime.utcnow()` DeprecationWarning in Discord notifier replaced with
  `datetime.now(timezone.utc)`.
- OIDC-based `publish.yml` replaced with explicit API token approach (OIDC was never
  configured on PyPI/TestPyPI, causing silent publish failures on every version tag).

### Tests
- 124 tests across 5 test files.
- Coverage: 83% overall. `cli.py` 100%, `notifications` 100%, `engine.py` 91%,
  `seer.py` 82%, `sanitizer/core.py` 87%.
- `test_cli.py` (21 tests): argparse correctness, sys.exit codes, error message routing.
- `test_notifications.py` (22 tests): Slack/Discord success, failure, no-op when unconfigured.
- `test_extraction.py` additions: disk-full abort, bad price as null, PermissionError,
  UnicodeDecodeError, sqlite rollback on write failure.

---

## [3.2.0] — 2026-05-15 (approx.)

### Added
- **CLI entry point**: `dih-engine extract` and `dih-engine recon` subcommands.
- **Multi-format output**: extraction engine writes JSONL (default), CSV, or SQLite.
- **`_open_writer()` context manager**: format-agnostic writer. SQLite uses
  `conn.rollback()` + `conn.close()` in finally to prevent corruption on write failure.
- **Disk + memory guardrails in extraction engine**:
  - Abort at start if disk > `disk_threshold` (default 95%).
  - GC pause + 2s sleep when memory > `pause_threshold` (default 80%) mid-run.
  - Disk check at every 10,000 lines during processing.
- **`pyproject.toml` build system**: `setuptools>=70` backend, pinned deps, `[project.scripts]`.
- **Windows UTF-8 fix**: `sys.stdout.reconfigure(encoding="utf-8")` at CLI entry so em dashes
  and accented characters don't crash on cp1252 consoles.
- **`.gitattributes`**: LF line endings enforced for all text files cross-platform.

### Fixed
- `3D` digit not replaced with `e` in product names (OCR ID correction applied to ID field only).
- `TOTALIZER` no longer triggers `TOTAL` blacklist (word boundary regex `\b`).
- `em dash` characters removed from all `print()` paths — Windows cp1252 incompatibility.

### Tests
- Full pytest suite with `conftest.py` factory fixtures.
- `test_extraction.py`: JSONL, CSV, SQLite happy paths + edge cases.
- `test_sanitizer.py`: noise detection, OCR correction, APPROVED/PARTIAL/REJECTED status.

---

## [3.1.0] — 2026-05 (early)

### Added
- **Seer V3** — tech stack identification with `_identify_stack()`:
  Next.js, React CSR, VTEX, Squarespace, Static HTML, Pure JSON API.
- **`locate_gold_mines()`**: DOM density scanner. Counts `<article>`, `<li>`, `<div>` tags.
  More than 10 of any tag = high-probability data payload.
- **`_majority_stack()`**: probes `sample_size` URLs (default 3), votes on dominant tech.
- **Console intelligence report**: architecture, strategy, gold mine, probe summary.
- **`SEER_INPUT_CSV` / `SEER_OUTPUT_FILE` env vars**: override defaults without CLI flags.

---

## [2.0.0] — 2026-05 (initial recon)

### Added
- **`DataSanitizer` class**: `extract_data()` returns `{id, amount, status}` for OCR lines.
  Status: `APPROVED` (id + amount), `PARTIAL` (one field), `REJECTED` (neither).
- **OCR corrections**: `O → 0`, `l → 1`, `I → 1`, `B → 8`, `S → 5` for ID fields only.
- **Amount normalization**: comma-decimal `14,50 → 14.50`.
- **Noise blacklist**: `TOTAL`, `SUBTOTAL`, `TAX`, `CASH`, `CARD`, `DATE:`, etc.
  Word-boundary match — `TOTALIZER` does not trigger `TOTAL`.
- **`RECORD_PATTERN` regex**: `ID: <id> PRODUCT: <name> [PRICE: S/ <price>] [Stock <n>]`.
  Price and Stock are optional capture groups.

---

## [1.0.0] — 2026-05 (initial commit)

### Added
- Repository scaffold: `src/dih_engine/` package layout.
- `DataSanitizer` prototype (single-file, no tests).
- Initial README with project intent.

---

## Coverage by version

| Version | Tests | Coverage |
|---|---|---|
| 1.0.0 | 0 | — |
| 2.0.0 | — | — |
| 3.1.0 | — | — |
| 3.2.0 | ~28 | ~55% |
| 4.0.0 | **124** | **83%** |

## Remaining coverage gaps (as of 4.0.0)

| File | Uncovered lines | Reason |
|---|---|---|
| `engine.py:146-164` | Disk/memory mid-run check | Requires 10,001+ lines in test fixture; not worth the fixture size |
| `curlffi_probe.py:14-15,23-40` | curl_cffi import + probe body | Optional dep not installed in CI env; tested via integration |
| `playwright_probe.py:14-15,23-43` | playwright import + probe body | Optional dep not installed in CI env; tested via integration |
| `sanitizer/core.py:104-115` | `__main__` block | CLI-level demo, not production code |
