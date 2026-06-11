"""
Seer V4 -- Web Recon Strategist with Error Diagnostics + Fallback Chain

Probes a set of URLs, identifies their tech stack, and produces a master
strategy plan for downstream data extraction.

Fallback chain (Option B):
  http_403, ssl_error  -> curl_cffi   (TLS fingerprint bypass)
  http_429, timeout    -> delay_retry  (exponential backoff + retry)
  js_required          -> playwright   (headless browser)

Install optional extras to activate fallback modules:
  pip install "dih-engine[tls]"      # curl_cffi
  pip install "dih-engine[browser]"  # playwright
  pip install "dih-engine[full]"     # both
"""
import concurrent.futures
import logging
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import pandas as pd
import psutil
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from ..notifications import notify_all
from . import loading_messages
from .error_taxonomy import FALLBACK_MAP
from .modules import curlffi_probe, flaresolverr_probe, playwright_probe, proxy_probe, requests_probe

load_dotenv()

logger = logging.getLogger(__name__)

USER_AGENTS = requests_probe.USER_AGENTS

# delay_retry exponential backoff: 5s -> 10s -> 20s (+0-1s jitter), capped at 60s.
# Jitter desynchronizes the 10 parallel workers so retries don't hit a rate-limited
# site in a synchronized burst, which would re-trigger the 429.
BACKOFF_BASE = 5.0
BACKOFF_MULTIPLIER = 2.0
BACKOFF_CAP = 60.0
BACKOFF_MAX_RETRIES = 3

# Statuses that prove the host itself is blocking or dead, not a transient glitch.
# http_403 here means the full fallback chain was already exhausted for that URL.
_CIRCUIT_STRIKE_STATUSES = frozenset({"http_403", "http_401", "ssl_error", "connection_error"})
CIRCUIT_BREAKER_THRESHOLD = 3


class _HostCircuitBreaker:
    """
    Per-host circuit breaker, scoped to a single recon run.

    A catalog CSV routinely carries dozens of URLs on one domain. Once a host
    has produced CIRCUIT_BREAKER_THRESHOLD terminal failures, every further
    probe against it buys the same answer at full price: another exhausted
    fallback chain, more wall-clock time, and a worse IP reputation with that
    WAF. The breaker stops paying; remaining URLs of that host are written to
    the CSV as "skipped_circuit_open" without a single network call.

    With 10 parallel workers the first wave of URLs for a blocked host may all
    launch before any strike lands -- the breaker cannot prevent that first
    wave, it caps the damage from the second wave onward.
    """

    def __init__(self, threshold: int = CIRCUIT_BREAKER_THRESHOLD):
        self._threshold = threshold
        self._strikes: dict[str, int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _host(url: str) -> str:
        return urlparse(url).netloc.lower()

    def is_open(self, url: str) -> bool:
        with self._lock:
            return self._strikes.get(self._host(url), 0) >= self._threshold

    def record(self, url: str, status: str) -> None:
        host = self._host(url)
        with self._lock:
            if status in _CIRCUIT_STRIKE_STATUSES:
                self._strikes[host] = self._strikes.get(host, 0) + 1
                if self._strikes[host] == self._threshold:
                    logger.warning("circuit_open host=%s strikes=%d", host, self._threshold)
            elif status == "ok":
                self._strikes.pop(host, None)


@dataclass
class ProbeResult:
    url: str
    status: str  # "ok" | "http_401" | "http_403" | "http_429" | "http_521" | "http_other"
                 # "timeout" | "connection_error" | "ssl_error" | "js_required" | "module_unavailable"
    tech: str = ""
    strategy: str = ""
    mines: list[str] = field(default_factory=list)
    error_detail: str = ""
    fallback_module: str = ""


def _is_valid_url(url: str) -> bool:
    """Returns False for entries that would cause requests to raise InvalidSchema/MissingSchema."""
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _disk_path() -> str:
    """Returns OS-appropriate disk root path for psutil.disk_usage()."""
    if sys.platform == "win32":
        drive = os.path.splitdrive(sys.executable)[0]
        return (drive + "\\") if drive else "C:\\"
    return "/"


def locate_gold_mines(html: str) -> list[str]:
    """
    Heuristic DOM density scanner. Finds structural tag clusters that
    indicate repeating data payloads (product grids, listing arrays).
    """
    soup = BeautifulSoup(html, "lxml")
    mines = []
    for tag in ["article", "li", "div"]:
        count = len(soup.find_all(tag))
        if count > 10:
            mines.append(f"Found {count} <{tag}> elements -- high probability data payload.")
    return mines if mines else ["No obvious structural arrays found."]


def _identify_stack(html: str, content_type: str) -> tuple[str, str]:
    """
    Maps HTML fingerprints to a (tech_stack, extraction_strategy) tuple.

    Check ORDER is load-bearing -- do not alphabetize:
      1. content_type first: a JSON API can contain any string in its body,
         so header evidence beats body heuristics.
      2. Next.js BEFORE React: every Next.js page also carries React markers;
         checking React first would misclassify all Next.js sites as CSR and
         route them to a headless browser they do not need.
      3. Static HTML is the fall-through, never an explicit match.
    """
    if "application/json" in content_type:
        return "Pure JSON API", "requests -- direct JSON parse"
    if '"props":{"pageProps":' in html or '<script id="__NEXT_DATA__"' in html:
        return "Next.js (SSR)", "Parse __NEXT_DATA__ JSON or Selenium for dynamic routes"
    if "data-reactroot" in html or "react-dom" in html:
        return "React.js (CSR)", "Selenium with dynamic waits"
    if "vtex.cmc" in html or "vtex-" in html:
        return "VTEX Commerce", "requests if API exposed, else Selenium"
    if "squarespace" in html.lower() or "static1.squarespace.com" in html:
        return "Squarespace", "BeautifulSoup -- SSR HTML, structure varies by template"
    return "Static HTML", "BeautifulSoup -- fast and direct"


def _build_probe_result(url: str, fetch: dict) -> ProbeResult:
    """Converts a raw fetch dict from a probe module into a ProbeResult."""
    if fetch["status"] != "ok":
        fallback = FALLBACK_MAP.get(fetch["status"], "")
        return ProbeResult(
            url=url,
            status=fetch["status"],
            error_detail=fetch["error_detail"],
            fallback_module=fallback,
        )
    html = fetch["html"]
    content_type = fetch["content_type"]
    tech, strategy = _identify_stack(html, content_type)
    mines = locate_gold_mines(html)
    return ProbeResult(url=url, status="ok", tech=tech, strategy=strategy, mines=mines)


def analyze_tech_stack(
    url: str,
    session: Optional[requests.Session] = None,
    timeout: int = 10,
    _sleep_fn=time.sleep,
) -> ProbeResult:
    """
    Probes a single URL and returns a ProbeResult with full error classification.
    On failure, automatically attempts the appropriate fallback module per FALLBACK_MAP.
    _sleep_fn is injectable for testing -- production callers use the default.
    """
    logger.info("probing url=%s", url)

    if not _is_valid_url(url):
        logger.warning("invalid_url url=%s -- skipping probe", url)
        return ProbeResult(url=url, status="invalid_url", error_detail="malformed URL -- missing scheme or host")

    fetch = requests_probe.probe(url, timeout=timeout, session=session, _sleep_fn=_sleep_fn)
    result = _build_probe_result(url, fetch)

    if result.status != "ok":
        module_name = result.fallback_module
        logger.info("fallback_triggered url=%s status=%s module=%s", url, result.status, module_name)

        if module_name == "curl_cffi":
            # Three-level escalation: curl_cffi -> FlareSolverr -> proxy.
            # Each level that is not installed/configured returns
            # "module_unavailable" instead of raising, so the chain walks
            # through whatever the operator actually has -- a bare install
            # degrades to documented failure, never to a crash. Every level's
            # error is appended to error_detail: the CSV tells the full story
            # of what was tried, in order, without reading any logs.
            fb_fetch = curlffi_probe.probe(url, timeout=timeout)
            fb = _build_probe_result(url, fb_fetch)
            if fb.status == "ok":
                logger.info("fallback_success url=%s module=curl_cffi", url)
                return fb
            result.error_detail += f" | curl_cffi: {fb.error_detail}"
            # Second-level: FlareSolverr (self-hosted Cloudflare solver, no account needed)
            logger.info("fallback_triggered url=%s status=%s module=flaresolverr", url, fb.status)
            fs_fetch = flaresolverr_probe.probe(url, timeout=timeout)
            fs = _build_probe_result(url, fs_fetch)
            if fs.status == "ok":
                logger.info("fallback_success url=%s module=flaresolverr", url)
                return fs
            result.error_detail += f" | flaresolverr: {fs.error_detail}"
            # Third-level: proxy rotation (generic HTTP/SOCKS5 or Scrapfly)
            logger.info("fallback_triggered url=%s status=%s module=proxy", url, fs.status)
            px_fetch = proxy_probe.probe(url, timeout=timeout)
            px = _build_probe_result(url, px_fetch)
            if px.status == "ok":
                logger.info("fallback_success url=%s module=proxy", url)
                return px
            result.error_detail += f" | proxy: {px.error_detail}"

        elif module_name == "playwright":
            fb_fetch = playwright_probe.probe(url, timeout=timeout)
            fb = _build_probe_result(url, fb_fetch)
            if fb.status == "ok":
                logger.info("fallback_success url=%s module=playwright", url)
                return fb
            result.error_detail += f" | playwright: {fb.error_detail}"

        elif module_name == "delay_retry":
            for attempt in range(BACKOFF_MAX_RETRIES):
                delay = min(BACKOFF_BASE * (BACKOFF_MULTIPLIER ** attempt), BACKOFF_CAP)
                delay += random.uniform(0, 1)
                logger.info(
                    "delay_retry url=%s attempt=%d/%d delay=%.1fs",
                    url, attempt + 1, BACKOFF_MAX_RETRIES, delay,
                )
                _sleep_fn(delay)
                retry_fetch = requests_probe.probe(url, timeout=timeout, session=session, _sleep_fn=lambda _: None)
                retry = _build_probe_result(url, retry_fetch)
                if retry.status == "ok":
                    logger.info("delay_retry_success url=%s attempt=%d", url, attempt + 1)
                    return retry
                result.error_detail += f" | retry {attempt + 1}: {retry.error_detail}"
                if retry.status not in ("http_429", "timeout"):
                    # Error class changed (e.g. 429 -> 403): more waiting won't help.
                    logger.info("delay_retry_abort url=%s status=%s", url, retry.status)
                    break

    logger.info("probe_result url=%s status=%s tech=%r", url, result.status, result.tech)
    return result


def _majority_stack(results: list[ProbeResult]) -> ProbeResult:
    """
    Returns the most commonly detected stack from a list of successful ProbeResults.

    Why a vote at all: one sampled URL can be an outlier (a static error page
    on a React site, a CDN redirect) and would misclassify the whole list.
    Why warning and not error when no absolute majority exists: a split vote
    still has a best candidate, and aborting the run over a tie would throw
    away every other probe's work -- the operator gets the warning plus the
    most frequent answer, and decides.
    """
    stacks = [r.tech for r in results]
    majority = max(set(stacks), key=stacks.count)
    if stacks.count(majority) < len(stacks) / 2:
        logger.warning(
            "no_majority_stack detections=%s -- using most frequent: %s", stacks, majority
        )
    return next(r for r in results if r.tech == majority)


def _extract_name(row: pd.Series) -> str:
    if row.get("Nombre Categoria", "Sin Nombre") != "Sin Nombre":
        return row["Nombre Categoria"]
    try:
        return row["URL"].rstrip("/").split("/")[-1].replace("-", " ").title()
    except (KeyError, AttributeError, IndexError):
        return "Unknown Category"


def clean_and_optimize_map(
    input_file: Optional[str] = None,
    output_file: Optional[str] = None,
    request_timeout: Optional[int] = None,
    sample_size: Optional[int] = None,
) -> None:
    input_file = input_file or os.getenv("SEER_INPUT_CSV", "seer_mapa_v2.csv")
    output_file = output_file or os.getenv("SEER_OUTPUT_FILE", "seer_mapa_master_plan.csv")
    if request_timeout is None:
        request_timeout = int(os.getenv("SEER_REQUEST_TIMEOUT", "10"))
    if sample_size is None:
        sample_size = int(os.getenv("SEER_SAMPLE_SIZE", "3"))

    if request_timeout <= 0:
        raise ValueError("request_timeout must be a positive integer")
    if sample_size <= 0:
        raise ValueError("sample_size must be a positive integer")

    logger.info("seer_v4_start input=%s", input_file)

    if not os.path.exists(input_file):
        logger.error("missing_input_file path=%s", input_file)
        raise FileNotFoundError(f"Input CSV not found: {input_file}")

    initial_disk = psutil.disk_usage(_disk_path()).percent
    if initial_disk > 95.0:
        logger.critical("disk_full disk=%.1f%% -- aborting", initial_disk)
        return

    logger.info("loading_csv path=%s", input_file)
    df = pd.read_csv(input_file)

    if "URL" not in df.columns:
        raise ValueError(f"CSV missing required 'URL' column. Found: {list(df.columns)}")

    df["URL"] = df["URL"].astype(str).str.strip()
    df["URL"] = df["URL"].replace({"nan": ""})
    df["URL"] = df["URL"].replace("", pd.NA)
    if df["URL"].isna().all():
        raise ValueError("CSV 'URL' column contains no valid URLs")

    # Strict URL schema validation: fail fast on malformed URL entries to
    # avoid producing noisy diagnostic plans when input CSV rows are corrupted
    # or missing schemes (e.g. "example.com"). This makes the failure
    # explicit for the caller/CI instead of emitting 'not_probed' rows.
    invalid_mask = ~df["URL"].astype(str).str.match(r"^https?://", na=False)
    if invalid_mask.any():
        sample_bad = df.loc[invalid_mask, "URL"].head(5).astype(str).tolist()
        raise ValueError(f"CSV 'URL' column contains malformed URLs: {sample_bad}")

    df["Nombre Categoria"] = df.apply(_extract_name, axis=1)
    df = df.drop_duplicates(subset=["URL"])

    sample_urls = df["URL"].dropna().drop_duplicates().head(sample_size).tolist()
    if not sample_urls:
        logger.error("no_urls_to_probe dataframe is empty after dedup")
        return

    logger.info("probing_sample size=%d urls=%s", len(sample_urls), sample_urls)

    _flavor_wait = loading_messages.waiting()
    print(f"\n  {_flavor_wait}\n")

    breaker = _HostCircuitBreaker()

    # Each thread gets its own session -- requests.Session is not thread-safe.
    def _probe(url: str) -> ProbeResult:
        if breaker.is_open(url):
            host = urlparse(url).netloc
            logger.info("circuit_skip url=%s host=%s", url, host)
            return ProbeResult(
                url=url,
                status="skipped_circuit_open",
                error_detail=f"circuit open for {host}: {CIRCUIT_BREAKER_THRESHOLD} terminal failures this run",
            )
        result = analyze_tech_stack(url, session=None, timeout=request_timeout)
        breaker.record(url, result.status)
        return result

    # Worst-case per-URL: requests(T) + curl_cffi(T) + flaresolverr(T+60) + proxy(T+30) + jitter
    # Divide by workers (parallel), add buffer. Prevents a hung socket from freezing the process.
    _wall_clock = max(120, (len(sample_urls) * (request_timeout * 4 + 100)) // min(10, len(sample_urls)) + 60)

    all_results: list[ProbeResult] = []
    max_workers = min(10, len(sample_urls))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_probe, url): url for url in sample_urls}
        try:
            for future in as_completed(futures, timeout=_wall_clock):
                url = futures[future]
                try:
                    all_results.append(future.result())
                except Exception as exc:
                    logger.error("probe_thread_failed url=%s reason=%s", url, exc)
                    all_results.append(ProbeResult(url=url, status="http_other", error_detail=str(exc)[:120]))
        except concurrent.futures.TimeoutError:
            logger.error("probe_pool_timeout wall_clock=%ds -- collecting partial results", _wall_clock)
            done_urls = {r.url for r in all_results}
            for future, url in futures.items():
                if url in done_urls:
                    continue
                if future.done():
                    try:
                        all_results.append(future.result())
                    except Exception as exc:
                        all_results.append(ProbeResult(url=url, status="http_other", error_detail=str(exc)[:120]))
                else:
                    all_results.append(ProbeResult(
                        url=url, status="timeout",
                        error_detail=f"probe thread exceeded wall-clock limit of {_wall_clock}s",
                    ))

    # Attach per-URL diagnostics to every row that was probed
    status_map = {r.url: r.status for r in all_results}
    error_map = {r.url: r.error_detail for r in all_results}
    fallback_map_col = {r.url: r.fallback_module for r in all_results}
    df["Status"] = df["URL"].map(status_map).fillna("not_probed")
    df["Error_Detail"] = df["URL"].map(error_map).fillna("")
    df["Fallback_Module"] = df["URL"].map(fallback_map_col).fillna("")

    # Probe breakdown for console
    status_counts: dict[str, int] = {}
    for r in all_results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    fallback_counts: dict[str, int] = {}
    for r in all_results:
        if r.fallback_module:
            fallback_counts[r.fallback_module] = fallback_counts.get(r.fallback_module, 0) + 1

    ok_results = [r for r in all_results if r.status == "ok"]
    if not ok_results:
        logger.error("all_probes_failed no tech stack detected from sample")
        _flavor_fail = loading_messages.failure()
        print(f"\n[SEER V4] All probes failed -- saving diagnostic CSV anyway.")
        print(f"  {_flavor_fail}")
        print(f"  Status breakdown: {status_counts}")
        df.to_csv(output_file, index=False)
        logger.info("diagnostic_plan_saved path=%s rows=%d", output_file, len(df))
        return

    winner = _majority_stack(ok_results)

    summary_str = ", ".join(f"{v} {k}" for k, v in status_counts.items())
    fallback_str = (
        ", ".join(f"{m} ({n})" for m, n in fallback_counts.items())
        if fallback_counts else "none"
    )

    logger.info(
        "intelligence_report tech=%r strategy=%r mines=%s",
        winner.tech, winner.strategy, winner.mines[0] if winner.mines else "",
    )
    print("\n" + "=" * 60)
    print("   INTELLIGENCE REPORT  (Seer V4)")
    print("   " + "-" * 53)
    print(f"   Architecture:    {winner.tech}")
    print(f"   Strategy:        {winner.strategy}")
    print(f"   Gold Mines:      {winner.mines[0] if winner.mines else 'n/a'}")
    print(f"   Probe summary:   {summary_str}")
    print(f"   Fallback needed: {fallback_str}")
    print("=" * 60 + "\n")

    _flavor_success = loading_messages.success()
    print(f"  {_flavor_success}\n")

    try:
        notify_all(
            tech=winner.tech,
            strategy=winner.strategy,
            gold_mine=winner.mines[0] if winner.mines else "n/a",
            status_counts=status_counts,
            fallback_counts=fallback_counts,
            output_file=output_file,
            flavor=_flavor_success,
        )
    except Exception as exc:
        logger.error("notify_all_failed reason=%s -- CSV will still be saved", exc)

    df.to_csv(output_file, index=False)
    logger.info("master_plan_saved path=%s rows=%d", output_file, len(df))


if __name__ == "__main__":
    clean_and_optimize_map()
