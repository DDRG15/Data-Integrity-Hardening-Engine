"""
Seer V3 — Web Recon Strategist
Probes a set of URLs, identifies their tech stack, and produces a master
strategy plan for downstream data extraction.

Known limitations (V3 scope):
  - Synchronous HTTP — see ROADMAP.md for the async V4 Swarm Protocol.
  - No robots.txt enforcement — operators must verify compliance before use.
  - TLS fingerprinting: 'requests' library is detectable by enterprise WAFs
    (Akamai, Cloudflare). Production use against protected sites requires
    curl_cffi or a managed proxy service.
"""
import logging
import os
import random
import sys
import time
from typing import Optional

import pandas as pd
import psutil
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("SEER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

INPUT_FILE = os.getenv("SEER_INPUT_CSV", "seer_mapa_v2.csv")
OUTPUT_FILE = os.getenv("SEER_OUTPUT_FILE", "seer_mapa_master_plan.csv")
REQUEST_TIMEOUT = int(os.getenv("SEER_REQUEST_TIMEOUT", "10"))
SAMPLE_SIZE = int(os.getenv("SEER_SAMPLE_SIZE", "3"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]


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
            mines.append(f"Found {count} <{tag}> elements — high probability data payload.")
    return mines if mines else ["No obvious structural arrays found."]


def _identify_stack(html: str, content_type: str) -> tuple[str, str]:
    """Maps HTML fingerprints to a (tech_stack, extraction_strategy) tuple."""
    if "application/json" in content_type:
        return "Pure JSON API", "requests — direct JSON parse"
    if '"props":{"pageProps":' in html or '<script id="__NEXT_DATA__"' in html:
        return "Next.js (SSR)", "Parse __NEXT_DATA__ JSON or Selenium for dynamic routes"
    if "data-reactroot" in html or "react-dom" in html:
        return "React.js (CSR)", "Selenium with dynamic waits"
    if "vtex.cmc" in html or "vtex-" in html:
        return "VTEX Commerce", "requests if API exposed, else Selenium"
    return "Static HTML", "BeautifulSoup — fast and direct"


def analyze_tech_stack(
    url: str,
    session: requests.Session,
) -> Optional[tuple[str, str, list[str]]]:
    """
    Probes a single URL and returns (tech_stack, strategy, gold_mines).
    Returns None on any network or HTTP failure.
    """
    logger.info("probing url=%s", url)
    entropy_delay = random.uniform(1.2, 3.5)
    time.sleep(entropy_delay)

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        tech, strategy = _identify_stack(response.text, content_type)
        mines = locate_gold_mines(response.text)
        logger.info("probe_result url=%s tech=%r strategy=%r", url, tech, strategy)
        return tech, strategy, mines
    except requests.exceptions.HTTPError as exc:
        logger.warning("http_error url=%s status=%s", url, exc.response.status_code)
    except requests.exceptions.ConnectionError as exc:
        logger.warning("connection_error url=%s reason=%s", url, exc)
    except requests.exceptions.Timeout:
        logger.warning("timeout url=%s threshold=%ds", url, REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        logger.warning("request_failed url=%s reason=%s", url, exc)
    return None


def _majority_stack(results: list[tuple[str, str, list[str]]]) -> tuple[str, str, list[str]]:
    """Returns the most commonly detected stack from a list of probe results."""
    stacks = [r[0] for r in results]
    majority = max(set(stacks), key=stacks.count)
    if stacks.count(majority) < len(stacks) / 2:
        logger.warning(
            "no_majority_stack detections=%s — using most frequent: %s", stacks, majority
        )
    return next(r for r in results if r[0] == majority)


def _extract_name(row: pd.Series) -> str:
    if row.get("Nombre Categoria", "Sin Nombre") != "Sin Nombre":
        return row["Nombre Categoria"]
    try:
        return row["URL"].rstrip("/").split("/")[-1].replace("-", " ").title()
    except (KeyError, AttributeError, IndexError):
        return "Unknown Category"


def clean_and_optimize_map() -> None:
    logger.info("seer_v3_start input=%s", INPUT_FILE)

    if not os.path.exists(INPUT_FILE):
        logger.error("missing_input_file path=%s", INPUT_FILE)
        raise FileNotFoundError(f"Input CSV not found: {INPUT_FILE}")

    initial_disk = psutil.disk_usage(_disk_path()).percent
    if initial_disk > 95.0:
        logger.critical("disk_full disk=%.1f%% — aborting", initial_disk)
        return

    logger.info("loading_csv path=%s", INPUT_FILE)
    df = pd.read_csv(INPUT_FILE)

    if "URL" not in df.columns:
        raise ValueError(f"CSV missing required 'URL' column. Found: {list(df.columns)}")

    df["Nombre Categoria"] = df.apply(_extract_name, axis=1)
    df = df.drop_duplicates(subset=["URL"])

    sample_urls = df["URL"].dropna().drop_duplicates().head(SAMPLE_SIZE).tolist()
    if not sample_urls:
        logger.error("no_urls_to_probe dataframe is empty after dedup")
        return

    logger.info("probing_sample size=%d urls=%s", len(sample_urls), sample_urls)

    results = []
    with requests.Session() as session:
        session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        for url in sample_urls:
            result = analyze_tech_stack(url, session)
            if result:
                results.append(result)

    if not results:
        logger.error("all_probes_failed no tech stack detected from sample")
        return

    tech, strategy, mines = _majority_stack(results)

    logger.info("intelligence_report tech=%r strategy=%r mines=%s", tech, strategy, mines[0])
    print("\n" + "=" * 60)
    print("   INTELLIGENCE REPORT")
    print("   " + "-" * 53)
    print(f"   Architecture:  {tech}")
    print(f"   Strategy:      {strategy}")
    print(f"   Gold Mines:    {mines[0]}")
    print("=" * 60 + "\n")

    df.to_csv(OUTPUT_FILE, index=False)
    logger.info("master_plan_saved path=%s rows=%d", OUTPUT_FILE, len(df))


if __name__ == "__main__":
    clean_and_optimize_map()
