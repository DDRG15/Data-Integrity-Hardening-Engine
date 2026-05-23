# Progress Log — dih-engine

Cross-session record of what was done, when, and why. Read this first when resuming work.
Each session entry is self-contained — no need to read earlier entries to understand the current state.

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
- `docs/AUDIT_2026-05-23.md` — 5W+How implementation log for all 6 audit findings

---

## Current State (end of 2026-05-23 session)

### Git log (local, not pushed)
```
aab9254  test: expand coverage 67% -> 83% across all modules
f49214d  audit(v4): fix 6 findings from MODE A review + 48-test suite
8457d69  chore: untrack NEXT_SESSION.md + rewrite ROADMAP to V4.0
d9c4133  docs(readme): add Roadmap section -- deliberate next steps, not gaps
7cbbc69  docs: update README + NEXT_SESSION for V4 final state
f3758dc  feat(recon): http_401/521 error codes + parallel probing via ThreadPoolExecutor
6f5e8a8  feat(recon): flaresolverr_probe -- self-hosted Cloudflare bypass
3aa562b  feat(recon): proxy_probe -- third-level fallback for persistent WAF blocks
65a99aa  feat(notifications): Slack + Discord notifiers wired into Seer V4
26a2dc8  feat(recon): Seer V4 -- error diagnostics + modular fallback chain
...     [earlier commits — see CHANGELOG.md]
```

**~15 commits ahead of origin/main.** Not pushed. User reviewing before GitHub push.

### Test suite
```
124 passed, 0 warnings — 41s on Python 3.12.10 / Windows 10
```

### Coverage summary
```
cli.py                        100%
extraction/engine.py           91%   (146-164 requires 10k+ line fixture, acceptable gap)
notifications/__init__.py      100%
notifications/discord.py       100%
notifications/slack.py         100%
recon/seer.py                   82%
sanitizer/core.py               87%   (104-115 = __main__ demo block)
curlffi_probe.py                30%   (optional dep, not in CI env)
playwright_probe.py             26%   (optional dep, not in CI env)
TOTAL                           83%
```

---

## What to do next (priority order)

### Before pushing to GitHub (must-do)
1. **Add secrets to GitHub repo** — Settings → Secrets → Actions:
   - `TEST_PYPI_API_TOKEN` — from test.pypi.org/manage/account/token/
   - `PYPI_API_KEY` — from pypi.org/manage/account/token/ (after deciding to publish)
2. **User reviews all commits** — `git log --oneline` shows 15+ commits; review diffs
3. **Push** — `git push origin main`
4. **CI badge** — goes green ~3 min after push (GitHub Actions runs pytest)
5. **Real PyPI publish** — only after CI badge is green; requires new `PYPI_API_TOKEN` secret

### Nice-to-have before GitHub push
- [ ] `test_extraction.py`: the `i % 10_000 == 0` disk/memory branch (146-164).
  Approach: refactor threshold to injectable parameter, or write 10,001 lines with `make_input_file`.
- [ ] `curlffi_probe.py` tests: mock `curl_cffi` at the module level with `sys.modules` injection.
- [ ] `playwright_probe.py` tests: same approach as curlffi.

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
