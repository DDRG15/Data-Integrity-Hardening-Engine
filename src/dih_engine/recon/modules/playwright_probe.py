"""
Probe module: Playwright -- headless browser for JS-rendered pages.

Handles: js_required (React CSR, Vue SPA, Angular apps with empty SSR body).
Install:  pip install "dih-engine[browser]" && playwright install chromium
"""
import logging

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    _AVAILABLE = True
except ImportError:
    sync_playwright = None  # type: ignore[assignment]
    _AVAILABLE = False


def probe(url: str, timeout: int = 10) -> dict:
    """
    Fetches url using a headless Chromium browser and waits for network idle.
    Returns same dict shape as requests_probe.probe().
    """
    if not _AVAILABLE:
        logger.warning("playwright_unavailable url=%s -- install dih-engine[browser]", url)
        return {
            "status": "module_unavailable",
            "html": "",
            "content_type": "",
            "error_detail": "playwright not installed -- run: pip install \"dih-engine[browser]\" && playwright install chromium",
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            html = page.content()
            browser.close()
        logger.info("playwright_success url=%s body_len=%d", url, len(html))
        return {"status": "ok", "html": html, "content_type": "text/html", "error_detail": ""}
    except Exception as exc:
        logger.warning("playwright_failed url=%s reason=%s", url, exc)
        return {"status": "http_other", "html": "", "content_type": "", "error_detail": str(exc)[:120]}
