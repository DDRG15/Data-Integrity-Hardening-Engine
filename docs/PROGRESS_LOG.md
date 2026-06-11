# Progress Log — dih-engine

Cross-session record of what was done, when, and why. Read this first when resuming work.
Each session entry is self-contained — no need to read earlier entries to understand the current state.

---

## Session 2026-06-10 (Wednesday) — Tier 1 Closeout begins

**Status when session started:** V4.1.1 pushed, CI green. 17-day gap (user studying).
PyPI publication blocked: user locked out of PyPI account, password reset email pending.
Not a blocker for any code work.

**Working protocol for this session (token-budget safety):** small atomic phases.
Each phase = code + tests green + local commit + PROGRESS_LOG entry. Heavy docs
(README/CHANGELOG/ROADMAP/version) updated at milestone close, not per phase.
If tokens run out mid-phase, max loss = minutes of work, never context.
**NO PUSH this session** until file audit against remote is done (user request).

### Phase 0 — ROADMAP.md restore
ROADMAP.md had 5 lines accidentally deleted in the working tree (IDE mishap).
Restored via `git restore` — committed version was correct. No commit needed.

### Co-author audit
Full `git log` scan for Co-Authored-By / Claude / Anthropic: **clean, zero traces.**

### Phase 1 — Exponential backoff in delay_retry (commit `510f69d`)
- `seer.py`: BACKOFF_BASE=5.0, BACKOFF_MULTIPLIER=2.0, BACKOFF_CAP=60.0, BACKOFF_MAX_RETRIES=3
- Sequence 5s -> 10s -> 20s + 0-1s jitter (desyncs the 10 parallel workers)
- Abort on error class change (429 -> 403 means WAF block; waiting cannot help)
- 4 new tests (`TestExponentialBackoff`). **166 tests, 93% coverage, 0 warnings.**
- ROADMAP Tier 1 checkbox flipped to done.

### Housekeeping (same session)
- Copilot residual artifacts deleted (claude_builder_plan.md + 2 .apply_patch.txt) —
  their changes live in commit history; the files were dead weight. User decision.
- Note: Copilot's May audit downgraded to low-trust by user. Its committed code stays
  (tested, green) but its findings carry no authority in future decisions.
- File audit vs remote done: nothing private tracked; .env / PRIVATE_README / PITCH /
  NEXT_SESSION correctly ignored. Co-author audit: full history clean, zero traces.

### Phase 1b — Per-host circuit breaker (commit `f863ffe`)
- `_HostCircuitBreaker` in seer.py: after 3 terminal failures (http_403/401,
  ssl_error, connection_error) from one host, remaining URLs of that host get
  `skipped_circuit_open` in the CSV without a network call. Lock-guarded (10 workers).
  Success resets strikes; transient statuses (429/timeout/js_required) never strike.
- Rationale: catalog CSVs carry many URLs per domain; without the breaker every URL
  of a blocked host re-pays the full exhausted fallback chain + IP reputation damage.
- 5 new tests (TestHostCircuitBreaker incl. end-to-end serial-executor skip).
  **171 tests, 93% coverage, 0 warnings.**

### Phase 2 — Locale-aware amount normalization (commit `3f73a78`)
- Old pattern silently rejected grouped amounts (`1.234,50` fell to PARTIAL with
  amount=None — silent data loss). New pattern accepts EU + US grouped shapes.
- No locale detection: the 2-decimal tail contract makes the rightmost separator
  the decimal mark, always. Normalization is pure position.
- 6 new tests (TestAmountLocaleNormalization incl. date-like 12.06.26 exclusion).
  **177 tests, 93% coverage, 0 warnings. All Tier 1 code items now closed.**

### Phase 3a — FastAPI scaffold: auth + /sanitize (commit `f120fde`) — TIER 2 BEGINS
- New `dih_engine.api` package: `create_app()` factory, `GET /health` (no auth),
  `POST /sanitize` behind `X-API-Key` (env `DIH_API_KEY`, compare_digest).
- Fail-closed auth: missing server key = 503 on data routes, never an open API.
  Health stays unauthenticated (probes can't carry secrets; 503 = restart loop).
- Response taxonomy adds NOISE. Line cap 10k chars (bigger belongs to /extract).
- Deps: `[api]` extra; fastapi/httpx in requirements-dev (CI collection lesson).
  Targeted filterwarnings for starlette's legacy multipart shim.
- Run server: `uvicorn "dih_engine.api:create_app" --factory`
- 11 new tests (test_api.py). **188 tests, 0 warnings.**

### Phase 3b — POST /extract (commit `7f6a4ab`)
- Tempfile bridge to `bulletproof_processor`: API inherits disk abort, memory
  pause and audit counts from the CLI engine -- zero reimplementation.
- Disk abort -> 507 (never a silent 200 with empty records). 5 MB sync cap.
- 5 new tests. **193 tests, 0 warnings.**

### Phase 3c — Async jobs (commit `101cb29`)
- POST /extract/async (202 + job_id) + GET /jobs/{id}. In-memory JobStore,
  2 workers, evicts finished >100, never evicts in-flight. Redis = Tier 3
  trigger (second instance behind LB), documented in jobs.py.

### Phase 3c VERIFIED (not assumed) + Milestone 4.2.0 close (commit `268f581`)
- Per user instruction "no se asume nada": ran the FULL suite after 3c, not just
  the API tests. Result: **198 passed, 94% coverage, 0 warnings.** 3c integrates
  clean -- no rewrite needed.
- Version 4.1.1 -> 4.2.0 (pyproject). CHANGELOG [4.2.0] entry. README: new API
  Service section, structure/roadmap/changelog/config updated, European-separator
  limitation resolved into a documented capability. ROADMAP: Tier 2 scaffold
  shipped, Tier 1 backoff/breaker/locale marked done.
- Dockerfile.api (uvicorn server, port 8000, /health healthcheck, [api] extra,
  non-root) + docker-compose `api` service (fail-closed DIH_API_KEY) + .env.example.
- PRIVATE_README.md and PITCH.md refreshed to 4.2.0 (gitignored, not committed).
- Working tree clean. Private files confirmed ignored via git check-ignore.

### Docker verified (2026-06-11, commit `bdee81c`)
- Docker Desktop update to 4.77.0 had hung LxssManager (WSL service) -- fixed by a
  full Windows restart, not antivirus. Then built and ran the API image for real.
- `.dockerignore` hardened: PRIVATE_README.md, PITCH.md, .claude/, data/, session
  notes, and Docker/compose files now excluded. README.md kept (build COPYs it).
- End-to-end against running container `dih-api:4.2.0`: build OK, healthcheck
  healthy, /health 200, /sanitize 401-without-key + APPROVED-with-EU-amount,
  /extract audit 3/2/1, async job queued->done. The one "not verified" item from
  the milestone is now verified. Test container removed.

### Session state (2026-06-10/11, autonomous run while user away)
- **15 commits ahead of origin/main, NOT pushed.** Awaiting user green light.
- NOT done (needs user / external): real PyPI publish (account locked), deploy to
  Railway/Render (needs hosting account).
- **RESUME POINT next session:** decide push; then deploy path or Tier 3 (Redis
  job store, aiohttp async, --retry flag, live smoke tests).

### Next phases (planned order)
- Tier 1 backlog (added 2026-06-10): `--retry` second-pass flag (re-probe only non-ok
  rows of a previous output CSV — deferred re-run instead of in-process standby);
  `@pytest.mark.live` smoke tests against httpbin.org (excluded from CI, run manually)
- Phase 3a-3e: FastAPI scaffold (Tier 2): app + /sanitize -> /extract -> job store +
  /jobs/{id} -> API key auth -> Docker + docs
- Milestone close: version 4.2.0 + CHANGELOG/README/ROADMAP/PRIVATE_README/PITCH refresh
- Pending user: PyPI password reset -> GitHub secrets -> publish. NO PUSH this session
  without explicit green light (file audit done, ready when user is).

---

## Session 2026-05-24 (Saturday) — CI Fix (V4.1.1)

**Status when session started:** V4.1.0 pushed to GitHub. All 3 CI matrix jobs failed immediately
(exit code 1, ~30s total — too fast for 162 tests, indicating a collection-time crash).

**Root cause:** Two bugs that only surface when optional deps (`curl-cffi`, `playwright`) are absent.

1. `curlffi_probe.py` / `playwright_probe.py`: The `except ImportError` block only set `_AVAILABLE = False`.
   The library name (`cffi_requests` / `sync_playwright`) was never assigned in that branch.
   When CI runs without the deps, `unittest.mock.patch("...curlffi_probe.cffi_requests")` raises
   `AttributeError` — the attribute doesn't exist in the module namespace so `patch()` has nothing
   to target. All probe tests in `test_probe_modules.py` fail at test setup.

2. `pyproject.toml`: No `pythonpath = ["."]` in `[tool.pytest.ini_options]`. Without this the
   project root is not guaranteed to be on `sys.path`, making `from src.dih_engine...` imports
   unreliable on CI runners vs. local (where CWD happens to be the root).

**Fix (commit `3e020d5`):**
- `curlffi_probe.py`: `cffi_requests = None` in `except ImportError`
- `playwright_probe.py`: `sync_playwright = None` in `except ImportError`
- `pyproject.toml`: `pythonpath = ["."]` added to `[tool.pytest.ini_options]`

162 tests pass locally (unchanged). Pushed. CI re-triggered.

---

**Docs updated this session:** CHANGELOG.md (V4.1.1 entry + gaps table), README.md (Changelog
section), pyproject.toml (version 4.1.0 → 4.1.1), PROGRESS_LOG.md (this entry).

---

## Session 2026-05-23 (Sunday) — Audit + Coverage Expansion

**Status when session started:** V4.0.0 fully implemented and committed. Seer had parallel
probing, FlareSolverr, proxy rotation, and Slack/Discord notifications. 48 tests passing.

**What was done:**

### Phase 1 — MODE A Audit (6 personas: SEC, SRE, SDET, ARCH, DEV, DATA)

Six findings identified and fixed. Full 5W+How details in [AUDIT_2026-05-23.md](AUDIT_2026-05-23.md).

| # | Finding | File | Fix |
|---|---|---|---|
| 1 | Proxy credentials in error_detail/logs | `proxy_probe.py` | `_redact()` regex strips `user:pass` |
| 2 | Malformed URLs classified as `http_other` | `seer.py` | `_is_valid_url()` + `invalid_url` status |
| 3 | ThreadPoolExecutor hangs indefinitely | `seer.py` | Wall-clock timeout + partial result collection |
| 4 | Non-probed URLs show empty Status | `seer.py` | `fillna("not_probed")` sentinel |
| 5 | Notification failure aborts CSV write | `seer.py` | `notify_all()` wrapped in try/except |
| 6 | publish.yml used unconfigured OIDC | `.github/workflows/publish.yml` | Rewrote to twine + API tokens |

Supplementary (not audit findings): `http_401` (terminal) and `http_521` (→ curl_cffi) added
to `requests_probe.py` and `error_taxonomy.py`.

Commit: `f49214d` — `audit(v4): fix 6 findings from MODE A review + 48-test suite`

### Phase 2 — Coverage Expansion

| Module | Before | After | New tests |
|---|---|---|---|
| `cli.py` | 0% | 100% | 21 (new `test_cli.py`) |
| `notifications/slack_notifier.py` | 26% | 100% | 12 (new `test_notifications.py`) |
| `notifications/discord_notifier.py` | 31% | 100% | 10 (new `test_notifications.py`) |
| `notifications/__init__.py` | 50% | 100% | 2 (new `test_notifications.py`) |
| `extraction/engine.py` | 77% | 91% | 6 (added to `test_extraction.py`) |
| **Total** | **67%** | **83%** | **+49 tests (75 → 124)** |

Bug fixed during coverage expansion: `discord_notifier.py` used `datetime.utcnow()` which is
deprecated in Python 3.12 and emitted a `DeprecationWarning` in the test run. Replaced with
`datetime.now(datetime.timezone.utc)`.

Commit: `aab9254` — `test: expand coverage 67% -> 83% across all modules`

### Phase 3 — Documentation

- `CHANGELOG.md` — full version history from 1.0.0 to 4.0.0 with per-release notes
- `docs/PROGRESS_LOG.md` — this file, cross-session tracking
- `docs/AUDIT_2026-05-23.md` — 5W+How audit log for all 6 MODE A findings

### Phase 4 — GitHub Copilot Second Audit (3 findings)

A second AI audit ran while the session was in progress. Copilot implemented SRE and DATA
fixes directly; Claude implemented the SDET fix. All 3 findings closed same session.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | HIGH (SDET) | curlffi_probe 30%, playwright_probe 26% | `tests/test_probe_modules.py` — 19 tests, direct probe() calls, _AVAILABLE patching |
| 2 | HIGH (SRE) | No input validation: --timeout 0 / --sample-size 0 silently accepted | Guards in `cli.py` (sys.exit 1) + `seer.py` (ValueError) |
| 3 | MEDIUM (DATA) | CSV URL column not pre-filtered (nan strings, whitespace, blanks) | strip → replace nan→"" → replace ""→pd.NA → raise if all invalid |

Full 5W+How for all 3 findings: [AUDIT_2026-05-23.md](AUDIT_2026-05-23.md#github-copilot-second-audit--2026-05-23-afternoon-cycle)

### Phase 5 — Copilot Second-Pass Coverage Push

After hitting its rate limit, Copilot produced `claude_full_fix.apply_patch.txt` for Claude to apply.
Claude verified and committed the changes.

**Changes applied (commit `a3b4594`):**
- `seer.py` — strict URL schema validation (regex `^https?://`); rejects malformed URLs before probing, raises `ValueError` with first 5 bad values listed
- `tests/test_seer.py` (+12 tests):
  - `test_playwright_fallback_success`, `test_delay_retry_success`, `test_curl_cffi_flaresolverr_proxy_success` (full 3-level fallback chain)
  - Scrapfly error branches: 401→invalid key, 429→quota exceeded, 503→http_other, exception→http_other
  - `test_proxy_probe_prefers_generic_proxy`, `test_proxy_probe_uses_scrapfly_when_generic_proxy_missing`
  - `test_invalid_url_in_csv_gets_invalid_url_status` rewritten to expect `ValueError("malformed URLs")`
- `tests/test_seer_followups.py` (new, 2 tests):
  - `test_clean_and_optimize_map_handles_threadpool_timeout` — FakeExecutor + TimeoutError → Status=timeout in CSV
  - `test_flaresolverr_error_path_returns_http_other` — JSON status=error response → http_other

---

## Current State (end of 2026-05-23 session — after all audit cycles)

### Git log (local, not pushed)
```
a3b4594  feat+test: strict URL schema validation + expanded fallback/proxy branch coverage
0206ee5  docs: record Copilot audit findings and resolution in AUDIT log and PROGRESS_LOG
69646c1  test(SDET): probe module branch coverage -- requests_probe, curlffi, playwright
0dfc514  feat(validation): SRE + DATA hardening from Copilot MODE A audit
7c749f7  docs: add CHANGELOG.md + docs/PROGRESS_LOG.md
aab9254  test: expand coverage 67% -> 83% across all modules
f49214d  audit(v4): fix 6 findings from MODE A review + 48-test suite
...     [see CHANGELOG.md for full history]
```

**~23 commits ahead of origin/main.** Not pushed. User reviewing before GitHub push.

### Test suite
```
162 passed, 0 warnings — 28.78s on Python 3.12.10 / Windows 10
```

### Coverage summary
```
cli.py                        100%
extraction/engine.py           91%   (146-164 requires 10k+ line fixture, acceptable gap)
notifications/__init__.py      100%
notifications/discord.py       100%
notifications/slack.py         100%
recon/seer.py                   90%   (was 83%)
sanitizer/core.py               87%   (104-115 = __main__ demo block)
requests_probe.py              100%
curlffi_probe.py                90%   (lines 14-15 = ImportError, acceptable)
playwright_probe.py             91%   (lines 14-15 = ImportError, acceptable)
proxy_probe.py                 100%   (was 74%)
flaresolverr_probe.py           85%   (lines 73-74, 87-89 = rare HTTP errors)
TOTAL                           93%   (was 89%)
```

---

## What to do next (priority order)

### Before pushing to GitHub (must-do)
1. **Add secrets to GitHub repo** — Settings → Secrets → Actions:
   - `TEST_PYPI_API_TOKEN` — from test.pypi.org/manage/account/token/
   - `PYPI_API_KEY` — from pypi.org/manage/account/token/ (after deciding to publish)
2. **User reviews all commits** — `git log --oneline` shows 17+ commits; review diffs
3. **Push** — `git push origin main`
4. **CI badge** — goes green ~3 min after push (GitHub Actions runs pytest)
5. **Real PyPI publish** — only after CI badge is green; requires new `PYPI_API_TOKEN` secret

### Nice-to-have before GitHub push
- [x] `curlffi_probe.py` tests — done (90% coverage, ImportError branch acceptable gap)
- [x] `playwright_probe.py` tests — done (91% coverage, ImportError branch acceptable gap)
- [ ] `test_extraction.py`: the `i % 10_000 == 0` disk/memory branch (lines 146-164).
  Approach: refactor threshold to injectable parameter, or write 10,001 lines with `make_input_file`.

### Post-push roadmap (from ROADMAP.md Tier 1)
- FlareSolverr live test: `docker compose up -d flaresolverr` + add `FLARE_SOLVER_URL` to `.env`,
  run recon against stackoverflow.com, etsy.com, centauro.com.br.
- Rate-limiting: exponential backoff with jitter instead of fixed 5-12s sleep in `delay_retry`.
- Scrapfly async: Scrapfly supports concurrent requests; proxy_probe currently does one at a time.
- Real PyPI: upload after CI is green. Token scope: project-scoped (not account-scoped) for security.

---

## Environment notes (for future sessions)

- **Python**: 3.12.10
- **OS**: Windows 10 Home (cp1252 console — UTF-8 reconfigure in `cli.py` is mandatory)
- **Shell**: PowerShell + Bash via WSL/Git Bash available
- **Optional deps installed locally**: `curl-cffi` installed. `playwright` not installed.
- **`.env`**: Slack + Discord webhooks configured and tested (working as of 2026-05-23).
  File is gitignored and must never be committed.
- **FlareSolverr**: not running locally. Start with `docker compose up -d flaresolverr`.
- **Proxy**: no proxy configured. Set `DIH_PROXY_URL` or `SCRAPFLY_API_KEY` in `.env` to activate.

---

## Files created/modified this session

| File | Change |
|---|---|
| `src/dih_engine/recon/modules/proxy_probe.py` | Added `_redact()`, applied to error_detail |
| `src/dih_engine/recon/seer.py` | URL validation, wall-clock timeout, sentinel, notify try/except |
| `src/dih_engine/recon/modules/requests_probe.py` | Added http_401, http_521 classification |
| `src/dih_engine/recon/error_taxonomy.py` | Added http_521 → curl_cffi; http_401 documented as terminal |
| `src/dih_engine/notifications/discord_notifier.py` | Fixed utcnow() deprecation |
| `.github/workflows/publish.yml` | Replaced OIDC with twine + API token secrets |
| `tests/test_seer.py` | +12 tests: TestUrlValidation, TestCleanAndOptimizeMap |
| `tests/test_cli.py` | New file — 21 tests for cli.py (was 0%) |
| `tests/test_notifications.py` | New file — 22 tests for Slack/Discord notifiers (was 26-31%) |
| `tests/test_extraction.py` | +6 tests for missing engine.py branches (77% → 91%) |
| `docs/AUDIT_2026-05-23.md` | New — 5W+How audit log for all 6 findings |
| `CHANGELOG.md` | New — full version history V1.0.0 → V4.0.0 |
| `docs/PROGRESS_LOG.md` | New — this file |
| `ROADMAP.md` | Rewritten: V4.0 as current, V3.x as history, Tier 1-3 next steps |
| `README.md` | Roadmap section, error table (401/521), live test results, V4 changelog |
