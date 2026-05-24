# Progress Log — dih-engine

Cross-session record of what was done, when, and why. Read this first when resuming work.
Each session entry is self-contained — no need to read earlier entries to understand the current state.

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
