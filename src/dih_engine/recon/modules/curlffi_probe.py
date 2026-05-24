"""
Probe module: curl_cffi -- TLS fingerprinting bypass for WAF-protected sites.

Handles: http_403 (Cloudflare, Akamai), ssl_error (TLS handshake mismatch).
Install:  pip install "dih-engine[tls]"
"""
import logging

logger = logging.getLogger(__name__)

try:
    from curl_cffi import requests as cffi_requests
    _AVAILABLE = True
except ImportError:
    cffi_requests = None  # type: ignore[assignment]
    _AVAILABLE = False


def probe(url: str, timeout: int = 10) -> dict:
    """
    Fetches url using curl_cffi (mimics Chrome TLS fingerprint to bypass WAFs).
    Returns same dict shape as requests_probe.probe().
    """
    if not _AVAILABLE:
        logger.warning("curl_cffi_unavailable url=%s -- install dih-engine[tls]", url)
        return {
            "status": "module_unavailable",
            "html": "",
            "content_type": "",
            "error_detail": "curl_cffi not installed -- run: pip install \"dih-engine[tls]\"",
        }

    try:
        response = cffi_requests.get(url, timeout=timeout, impersonate="chrome120")
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        logger.info("curlffi_success url=%s", url)
        return {"status": "ok", "html": response.text, "content_type": content_type, "error_detail": ""}
    except Exception as exc:
        logger.warning("curlffi_failed url=%s reason=%s", url, exc)
        return {"status": "http_other", "html": "", "content_type": "", "error_detail": str(exc)[:120]}
