"""
Header-based API key authentication.

Fail-closed design: if DIH_API_KEY is not configured on the server, every
authenticated route returns 503 instead of running open. An operator who
forgets to set the key gets a loud, immediate error on the first request --
not a publicly writable API discovered three weeks later.
"""
import logging
import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


async def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """
    FastAPI dependency. Reads DIH_API_KEY at request time (not import time)
    so the key can be rotated without a process restart.
    """
    expected = os.getenv("DIH_API_KEY", "")
    if not expected:
        logger.error("auth_misconfigured DIH_API_KEY is not set -- refusing request")
        raise HTTPException(
            status_code=503,
            detail="server has no DIH_API_KEY configured -- refusing to serve an open API",
        )
    # compare_digest: constant-time comparison, no timing side channel.
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        logger.warning("auth_rejected missing_or_invalid_key")
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key header")
