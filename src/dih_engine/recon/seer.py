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
from .error_taxonomy import FALLBACK_MAP
from .modules import curlffi_probe, flaresolverr_probe, playwright_probe, proxy_probe, requests_probe

load_dotenv()

logger = logging.getLogger(__name__)

USER_AGENTS = requests_probe.USER_AGENTS


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
    """Maps HTML fingerprints to a (tech_stack, extraction_strategy) tuple."""
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
            delay = random.uniform(5, 12)
            logger.info("delay_retry url=%s delay=%.1fs", url, delay)
            _sleep_fn(delay)
            retry_fetch = requests_probe.probe(url, timeout=timeout, session=session, _sleep_fn=lambda _: None)
            retry = _build_probe_result(url, retry_fetch)
            if retry.status == "ok":
                logger.info("delay_retry_success url=%s", url)
                return retry
            result.error_detail += f" | retry: {retry.error_detail}"

    logger.info("probe_result url=%s status=%s tech=%r", url, result.status, result.tech)
    return result


def _majority_stack(results: list[ProbeResult]) -> ProbeResult:
    """Returns the most commonly detected stack from a list of successful ProbeResults."""
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
    request_timeout = request_timeout or int(os.getenv("SEER_REQUEST_TIMEOUT", "10"))
    sample_size = sample_size or int(os.getenv("SEER_SAMPLE_SIZE", "3"))

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

    df["Nombre Categoria"] = df.apply(_extract_name, axis=1)
    df = df.drop_duplicates(subset=["URL"])

    sample_urls = df["URL"].dropna().drop_duplicates().head(sample_size).tolist()
    if not sample_urls:
        logger.error("no_urls_to_probe dataframe is empty after dedup")
        return

    logger.info("probing_sample size=%d urls=%s", len(sample_urls), sample_urls)

    # Each thread gets its own session -- requests.Session is not thread-safe.
    def _probe(url: str) -> ProbeResult:
        return analyze_tech_stack(url, session=None, timeout=request_timeout)

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
        print("\n[SEER V4] All probes failed -- saving diagnostic CSV anyway.")
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

    try:
        notify_all(
            tech=winner.tech,
            strategy=winner.strategy,
            gold_mine=winner.mines[0] if winner.mines else "n/a",
            status_counts=status_counts,
            fallback_counts=fallback_counts,
            output_file=output_file,
        )
    except Exception as exc:
        logger.error("notify_all_failed reason=%s -- CSV will still be saved", exc)

    df.to_csv(output_file, index=False)
    logger.info("master_plan_saved path=%s rows=%d", output_file, len(df))


if __name__ == "__main__":
    clean_and_optimize_map()
