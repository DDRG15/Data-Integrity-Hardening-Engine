"""
FastAPI application factory for the dih-engine API service.

Endpoints (Tier 2, phase 3a):
    GET  /health    -- liveness probe, unauthenticated (probes cannot carry secrets)
    POST /sanitize  -- one raw OCR line in, one typed record out (X-API-Key required)

Coming in later phases: POST /extract (file-level), GET /jobs/{id} (async polling).
"""
import json
import logging
import os
import tempfile
from importlib.metadata import PackageNotFoundError, version

from fastapi import Depends, FastAPI, HTTPException

from ..extraction.engine import bulletproof_processor
from ..sanitizer.core import DataSanitizer
from .auth import require_api_key
from .schemas import (
    ExtractRequest,
    ExtractResponse,
    HealthResponse,
    SanitizeRequest,
    SanitizeResponse,
)

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

    @app.post(
        "/extract",
        response_model=ExtractResponse,
        dependencies=[Depends(require_api_key)],
    )
    def extract(req: ExtractRequest) -> dict:
        # The battle-tested file engine does the work -- tempfiles bridge the
        # HTTP payload to it, so the API inherits every guardrail (disk abort,
        # memory pause, audit counts) instead of reimplementing them.
        with tempfile.TemporaryDirectory(prefix="dih_api_") as tmp:
            in_path = os.path.join(tmp, "input.txt")
            out_path = os.path.join(tmp, "output.jsonl")
            with open(in_path, "w", encoding="utf-8") as f:
                f.write(req.text)

            audit = bulletproof_processor(in_path, out_path, output_format="jsonl")

            if audit.get("aborted"):
                logger.error("extract_aborted disk_threshold_exceeded")
                raise HTTPException(
                    status_code=507,
                    detail="extraction aborted: server disk usage above threshold",
                )

            records: list[dict] = []
            with open(out_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))

        logger.info(
            "extract_ok total=%d matched=%d skipped=%d",
            audit["total"], audit["matched"], audit["skipped"],
        )
        return {
            "records": records,
            "audit": {
                "total": audit["total"],
                "matched": audit["matched"],
                "skipped": audit["skipped"],
            },
        }

    return app
