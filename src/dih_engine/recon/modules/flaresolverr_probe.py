"""
Probe module: FlareSolverr -- self-hosted Cloudflare challenge solver.

Handles: persistent 403s from Cloudflare and Akamai that block both
requests and curl_cffi. Runs a real Chrome browser server-side to
solve JS challenges before returning the HTML.

No account needed. Runs locally via Docker (free, open-source).

Setup:
  docker run -d --name=flaresolverr -p 8191:8191 \\
    ghcr.io/flaresolverr/flaresolverr:latest

  Add to .env:
    FLARE_SOLVER_URL=http://localhost:8191/v1

Or via docker-compose (already in docker-compose.yml):
  docker compose up -d flaresolverr
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "http://localhost:8191/v1"
_CHALLENGE_TIMEOUT_BUFFER = 60  # FlareSolverr may spend up to 60s on hard challenges


def probe(url: str, timeout: int = 10) -> dict:
    """
    Submits url to a running FlareSolverr instance and returns the solved HTML.
    Returns same dict shape as requests_probe.probe().

    If FLARE_SOLVER_URL is not set, returns module_unavailable silently.
    If the Docker container is not running, returns module_unavailable with instructions.
    """
    endpoint = os.getenv("FLARE_SOLVER_URL", "").strip()
    if not endpoint:
        logger.debug("flaresolverr_skipped -- FLARE_SOLVER_URL not set")
        return {
            "status": "module_unavailable",
            "html": "",
            "content_type": "",
            "error_detail": (
                "FlareSolverr not configured -- add FLARE_SOLVER_URL=http://localhost:8191/v1 "
                "to .env and start: docker compose up -d flaresolverr"
            ),
        }

    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": (timeout + _CHALLENGE_TIMEOUT_BUFFER) * 1000,
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout + _CHALLENGE_TIMEOUT_BUFFER)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "ok":
            message = data.get("message", "unknown error")
            logger.warning("flaresolverr_error url=%s message=%s", url, message)
            return {"status": "http_other", "html": "", "content_type": "", "error_detail": f"flaresolverr: {message}"}

        solution = data.get("solution", {})
        status_code = solution.get("status", 200)
        html = solution.get("response", "")

        if status_code >= 400:
            logger.warning("flaresolverr_http_error url=%s status=%d", url, status_code)
            return {"status": f"http_{status_code}", "html": "", "content_type": "", "error_detail": f"flaresolverr: HTTP {status_code}"}

        logger.info("flaresolverr_success url=%s body_len=%d", url, len(html))
        return {"status": "ok", "html": html, "content_type": "text/html", "error_detail": ""}

    except requests.exceptions.ConnectionError:
        logger.warning("flaresolverr_not_running url=%s", url)
        return {
            "status": "module_unavailable",
            "html": "",
            "content_type": "",
            "error_detail": "FlareSolverr unreachable -- start with: docker compose up -d flaresolverr",
        }
    except Exception as exc:
        logger.warning("flaresolverr_failed url=%s reason=%s", url, exc)
        return {"status": "http_other", "html": "", "content_type": "", "error_detail": f"flaresolverr: {str(exc)[:120]}"}
