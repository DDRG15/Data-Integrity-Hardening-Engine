# Changelog — dih-engine

All version history in reverse-chronological order.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [4.3.0] — 2026-06-11

### Added
- **`dih-engine config` subcommand** (`config_store.py` + CLI wiring): manage `.env`
  credentials without hand-editing — `config list` (status, masked value, set/rotation
  dates, provider), `config set NAME` (hidden `getpass` prompt for secrets), `config unset
  NAME` (expired/rotated-out keys). Metadata lives in `.env.meta.json` (git+docker
  ignored): set date, rotation date, optional provider label, last-4 of secret values.
- Security contract, tested not promised: values never printed/logged/echoed; metadata
  asserted secret-free via `json.dumps`; unknown variable names rejected (typo protection);
  multiline values rejected (injection protection); atomic `.env` writes
  (tempfile + `os.replace`); comments and foreign lines preserved byte-for-byte;
  secrets under 8 chars fully masked; unknown vars found in `.env` reported but masked.
- Logic isolated in `config_store.py` — a future local UI mounts on the same module
  without touching the CLI.

### Tests
- **219 tests, 0 warnings** (was 198). `test_config.py` (21 tests, new file): set/rotate/
  unset lifecycle, comment preservation, secret masking, CLI round-trip, exit codes.

---

## [4.2.0] — 2026-06-10

### Added
- **Tier 2 API service** (`dih_engine.api`, optional extra `[api]`): FastAPI app exposing
  the engine over HTTP. Run with `uvicorn "dih_engine.api:create_app" --factory`.
  - `GET /health` — unauthenticated liveness probe (probes cannot carry secrets).
  - `POST /sanitize` — one OCR line in, one typed record out (`APPROVED`/`PARTIAL`/`REJECTED`/`NOISE`).
  - `POST /extract` — full OCR text in, structured records + reconciliation audit out.
    Reuses `bulletproof_processor` via tempfiles, inheriting disk/memory guardrails.
    Disk abort surfaces as `507`, never a silent `200` with empty records.
  - `POST /extract/async` + `GET /jobs/{id}` — submit large files, poll for completion.
    In-memory `JobStore` (lock-guarded, 2 workers, evicts finished beyond 100, never
    evicts in-flight jobs). Async result honors the same audit contract as sync `/extract`.
  - **Fail-closed auth**: `X-API-Key` header against `DIH_API_KEY`; no server key = `503`
    on every data route. Constant-time comparison via `secrets.compare_digest`.
- **Exponential backoff in `delay_retry`** (`seer.py`): base 5s, multiplier 2x, cap 60s,
  0-1s jitter to desynchronize the 10 parallel workers. Aborts remaining retries when the
  error class changes mid-retry (429 → 403 means a WAF block; waiting cannot help).
- **Per-host circuit breaker** (`seer.py`): after 3 terminal failures from one host
  (`http_403`/`http_401`/`ssl_error`/`connection_error`), remaining URLs of that host are
  written `skipped_circuit_open` without a network call. Protects API credits and IP
  reputation on catalogs with many URLs per domain. Success resets the host's strikes.
- **Locale-aware amount normalization** (`sanitizer/core.py`): handles European `1.234,50`
  and US `1,234.50` grouped formats. The mandatory 2-decimal tail makes the rightmost
  separator the decimal mark — no locale detection needed. Previously these amounts were
  silently dropped to `PARTIAL` with `amount=None`.

### Tests
- **198 tests, 0 warnings. Coverage: 94% overall** (was 162 tests, 93%).
- `test_api.py` (21 tests, new file): auth gate (401/503), `/sanitize`, `/extract` with
  exact audit counts, disk-abort 507, async job lifecycle (queued → done/failed), 404.
- `test_seer.py` additions: `TestExponentialBackoff` (4), `TestHostCircuitBreaker` (5).
- `test_sanitizer.py` additions: `TestAmountLocaleNormalization` (6).

---

## [4.1.1] — 2026-05-24

### Fixed
- **CI green on all Python versions** (`curlffi_probe.py`, `playwright_probe.py`): Optional library
  names (`cffi_requests`, `sync_playwright`) were only defined when the library was installed.
  `unittest.mock.patch()` raised `AttributeError` in CI environments where `curl-cffi` and
  `playwright` are absent — the name doesn't exist in the module namespace, so `patch()` has
  nothing to target. Added `= None` sentinel in each `except ImportError` block so `patch()` can
  always locate and replace the attribute regardless of installation state.
- **pytest `pythonpath` setting** (`pyproject.toml`): Added `pythonpath = ["."]` to
  `[tool.pytest.ini_options]` so the project root is explicitly on `sys.path` in all runner
  environments, making `from src.dih_engine...` imports reliable in CI (not just locally).

---

## [4.1.0] — 2026-05-23

### Added
- **Loading-screen flavor text** (`recon/loading_messages.py`): 41 waiting phrases, 8 success
  phrases, 9 failure phrases — hamsters, pylons, Vim interns, and rubber ducks. Displayed in the
  CLI at three moments: while the ThreadPoolExecutor probes, on success after the Intelligence
  Report, and on all-probes-failed. Success phrase forwarded to Slack (`:sparkles:` context block)
  and Discord (embed footer text).
- **Strict URL schema validation** in `clean_and_optimize_map()`: rejects any URL not matching
  `^https?://` before sampling. `ValueError` lists the first 5 bad values so the caller/CI sees
  exactly what's wrong.

### Hardened
- **CLI input validation** (`cli.py`): `--timeout ≤ 0`, `--sample-size ≤ 0`,
  `--pause-threshold` outside (0, 100), `--disk-threshold` outside (0, 100) now exit 1 with a
  clear `error:` message instead of silently misbehaving or causing division-by-zero downstream.
- **Programmatic input validation** (`seer.py`): `clean_and_optimize_map()` raises `ValueError`
  for `request_timeout ≤ 0` or `sample_size ≤ 0` when called directly (not via CLI).
- **URL column pre-filter** (`seer.py`): strips whitespace, replaces `"nan"` strings with
  `pd.NA`, raises `ValueError` when the entire URL column is blank after normalization.

### Tests
- **162 tests, 0 warnings. Coverage: 93% overall** (was 124 tests, 83%).
- `test_probe_modules.py` (19 tests, new file): direct `probe()` calls on `requests_probe`,
  `curlffi_probe`, `playwright_probe` with patched library internals. `requests_probe` 87% → 100%,
  `curlffi_probe` 30% → 90%, `playwright_probe` 26% → 91%.
- `test_seer_followups.py` (2 tests, new file): thread-pool timeout partial-result path via
  `FakeExecutor` + `concurrent.futures.TimeoutError`; FlareSolverr JSON `status=error` path.
- `test_seer.py` additions (+12 tests): playwright fallback success, delay_retry success,
  full curl_cffi → flaresolverr → proxy three-level chain; Scrapfly 401/429/503/exception error
  branches; proxy routing preference; invalid URL in CSV now expects `ValueError`.
- `proxy_probe.py`: 74% → **100%**. `seer.py`: 83% → **90%**.

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
| 4.0.0 | 124 | 83% |
| 4.1.0 | 162 | 93% |
| 4.1.1 | 162 | 93% |
| 4.2.0 | 198 | 94% |
| 4.3.0 | **219** | **94%** |

## Remaining coverage gaps (as of 4.1.1)

| File | Uncovered lines | Reason |
|---|---|---|
| `engine.py:146-164` | Disk/memory mid-run check | Requires 10,001+ lines in test fixture; not worth the fixture size |
| `curlffi_probe.py:14-16` | ImportError branch (local only) | `curl-cffi` is installed locally so the except block never runs; covered in CI where the library is absent |
| `playwright_probe.py:14-16` | ImportError branch (local only) | `playwright` is installed locally so the except block never runs; covered in CI where the library is absent |
| `sanitizer/core.py:104-115` | `__main__` block | CLI-level demo, not production code |
| `seer.py` (~10%) | Various fallback/console branches | Wall-clock timeout partial-result path + some print branches |
