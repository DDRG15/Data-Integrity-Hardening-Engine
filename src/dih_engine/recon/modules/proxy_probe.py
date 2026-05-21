"""
Probe module: proxy -- residential proxy rotation for persistent WAF blocks.

Third-level fallback for sites that block both requests and curl_cffi
(Cloudflare Enterprise, Akamai, advanced bot protection).

Supported backends (priority order):
  1. DIH_PROXY_URL      -- any HTTP/SOCKS5 proxy (Oxylabs, BrightData, Smartproxy, etc.)
  2. SCRAPFLY_API_KEY   -- Scrapfly API (has a free tier at scrapfly.io)

Setup in .env:
  DIH_PROXY_URL=http://user:pass@proxy.provider.com:8080
  SCRAPFLY_API_KEY=scp-live-...

SOCKS5 support requires: pip install "dih-engine[proxy]"
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

_SCRAPFLY_ENDPOINT = "https://api.scrapfly.io/scrape"


def _via_generic_proxy(url: str, proxy_url: str, timeout: int) -> dict:
    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        response = requests.get(url, proxies=proxies, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        logger.info("proxy_success url=%s", url)
        return {"status": "ok", "html": response.text, "content_type": content_type, "error_detail": ""}
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code
        logger.warning("proxy_http_error url=%s status=%d", url, code)
        return {"status": f"http_{code}", "html": "", "content_type": "", "error_detail": f"proxy: HTTP {code}"}
    except requests.exceptions.RequestException as exc:
        logger.warning("proxy_failed url=%s reason=%s", url, exc)
        return {"status": "http_other", "html": "", "content_type": "", "error_detail": f"proxy: {str(exc)[:120]}"}


def _via_scrapfly(url: str, api_key: str, timeout: int) -> dict:
    try:
        response = requests.get(
            _SCRAPFLY_ENDPOINT,
            params={"key": api_key, "url": url, "render_js": "false"},
            timeout=timeout + 30,
        )
        response.raise_for_status()
        data = response.json()
        html = data.get("result", {}).get("content", "")
        headers = data.get("result", {}).get("response_headers", {})
        content_type = headers.get("content-type", "text/html")
        if not html:
            return {"status": "http_other", "html": "", "content_type": "", "error_detail": "scrapfly: empty content"}
        logger.info("scrapfly_success url=%s", url)
        return {"status": "ok", "html": html, "content_type": content_type, "error_detail": ""}
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code
        logger.warning("scrapfly_http_error url=%s status=%d", url, code)
        if code == 401:
            return {"status": "http_other", "html": "", "content_type": "", "error_detail": "scrapfly: invalid API key"}
        if code == 429:
            return {"status": "http_429", "html": "", "content_type": "", "error_detail": "scrapfly: quota exceeded"}
        return {"status": "http_other", "html": "", "content_type": "", "error_detail": f"scrapfly: HTTP {code}"}
    except Exception as exc:
        logger.warning("scrapfly_failed url=%s reason=%s", url, exc)
        return {"status": "http_other", "html": "", "content_type": "", "error_detail": f"scrapfly: {str(exc)[:120]}"}


def probe(url: str, timeout: int = 10) -> dict:
    """
    Fetches url via a configured proxy backend.
    Priority: DIH_PROXY_URL -> SCRAPFLY_API_KEY -> module_unavailable.
    Returns same dict shape as requests_probe.probe().
    """
    proxy_url = os.getenv("DIH_PROXY_URL", "").strip()
    if proxy_url:
        logger.info("proxy_attempt url=%s via=generic", url)
        return _via_generic_proxy(url, proxy_url, timeout)

    scrapfly_key = os.getenv("SCRAPFLY_API_KEY", "").strip()
    if scrapfly_key:
        logger.info("proxy_attempt url=%s via=scrapfly", url)
        return _via_scrapfly(url, scrapfly_key, timeout)

    logger.warning("proxy_unavailable url=%s -- set DIH_PROXY_URL or SCRAPFLY_API_KEY in .env", url)
    return {
        "status": "module_unavailable",
        "html": "",
        "content_type": "",
        "error_detail": "no proxy configured -- set DIH_PROXY_URL or SCRAPFLY_API_KEY in .env",
    }
