"""
Probe module: standard requests library (default, always available).

Returns a raw fetch dict consumed by the Seer orchestrator.
Dict keys: status, html, content_type, error_detail
"""
import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

_JS_SHELL_THRESHOLD = 500


def _is_js_shell(html: str, content_type: str) -> bool:
    """Detects a CSR-only page that has no server-rendered content."""
    if "application/json" in content_type:
        return False
    return len(html.strip()) < _JS_SHELL_THRESHOLD and "<div id=" in html


def probe(
    url: str,
    timeout: int = 10,
    session: "requests.Session | None" = None,
    _sleep_fn=time.sleep,
) -> dict:
    """
    Fetches url using requests. Returns:
      {"status": "ok"|<error_code>, "html": str, "content_type": str, "error_detail": str}
    """
    _sleep_fn(random.uniform(1.2, 3.5))
    _own_session = session is None
    s = session or requests.Session()
    if _own_session:
        s.headers.update({"User-Agent": random.choice(USER_AGENTS)})

    try:
        response = s.get(url, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        html = response.text

        if _is_js_shell(html, content_type):
            logger.info("js_shell_detected url=%s body_len=%d", url, len(html.strip()))
            return {"status": "js_required", "html": html, "content_type": content_type, "error_detail": "empty CSR shell -- no server-rendered content"}

        return {"status": "ok", "html": html, "content_type": content_type, "error_detail": ""}

    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code
        logger.warning("http_error url=%s status=%d", url, code)
        if code == 403:
            return {"status": "http_403", "html": "", "content_type": "", "error_detail": "HTTP 403 Forbidden -- likely WAF or geo-block"}
        if code == 429:
            return {"status": "http_429", "html": "", "content_type": "", "error_detail": "HTTP 429 Rate Limited"}
        return {"status": "http_other", "html": "", "content_type": "", "error_detail": f"HTTP {code}"}

    except requests.exceptions.SSLError as exc:
        logger.warning("ssl_error url=%s", url)
        return {"status": "ssl_error", "html": "", "content_type": "", "error_detail": str(exc)[:120]}

    except requests.exceptions.Timeout:
        logger.warning("timeout url=%s threshold=%ds", url, timeout)
        return {"status": "timeout", "html": "", "content_type": "", "error_detail": f"timeout after {timeout}s"}

    except requests.exceptions.ConnectionError as exc:
        logger.warning("connection_error url=%s", url)
        return {"status": "connection_error", "html": "", "content_type": "", "error_detail": str(exc)[:120]}

    except requests.exceptions.RequestException as exc:
        logger.warning("request_failed url=%s reason=%s", url, exc)
        return {"status": "http_other", "html": "", "content_type": "", "error_detail": str(exc)[:120]}

    finally:
        if _own_session:
            s.close()
