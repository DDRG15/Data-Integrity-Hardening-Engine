"""
FastAPI application factory for the dih-engine API service.

Endpoints (Tier 2, phase 3a):
    GET  /health    -- liveness probe, unauthenticated (probes cannot carry secrets)
    POST /sanitize  -- one raw OCR line in, one typed record out (X-API-Key required)

Coming in later phases: POST /extract (file-level), GET /jobs/{id} (async polling).
"""
import logging
from importlib.metadata import PackageNotFoundError, version

from fastapi import Depends, FastAPI

from ..sanitizer.core import DataSanitizer
from .auth import require_api_key
from .schemas import HealthResponse, SanitizeRequest, SanitizeResponse

logger = logging.getLogger(__name__)

try:
    _VERSION = version("dih-engine")
except PackageNotFoundError:
    _VERSION = "0.0.0-dev"


def create_app() -> FastAPI:
    """
    Application factory -- run with:
        uvicorn "dih_engine.api:create_app" --factory
    """
    app = FastAPI(
        title="dih-engine API",
        version=_VERSION,
        description="Deterministic OCR sanitization and extraction as a service",
    )

    # One sanitizer per app: stateless after __init__, compiled regexes are
    # immutable and thread-safe, so concurrent requests share it safely.
    sanitizer = DataSanitizer()

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict:
        return {"status": "ok", "version": _VERSION}

    @app.post(
        "/sanitize",
        response_model=SanitizeResponse,
        dependencies=[Depends(require_api_key)],
    )
    def sanitize(req: SanitizeRequest) -> dict:
        result = sanitizer.extract_data(req.line)
        if result is None:
            logger.info("sanitize_noise line_len=%d", len(req.line))
            return {"id": None, "amount": None, "status": "NOISE"}
        logger.info("sanitize_ok status=%s", result["status"])
        return {"id": result["id"], "amount": result["amount"], "status": result["status"]}

    return app
