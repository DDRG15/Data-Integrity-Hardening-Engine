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
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import PackageNotFoundError, version

from fastapi import Depends, FastAPI, HTTPException

from ..extraction.engine import bulletproof_processor
from ..sanitizer.core import DataSanitizer
from .auth import require_api_key
from .jobs import JobStore
from .schemas import (
    ExtractRequest,
    ExtractResponse,
    HealthResponse,
    JobStatusResponse,
    JobSubmitResponse,
    SanitizeRequest,
    SanitizeResponse,
)


class DiskAbortError(RuntimeError):
    """Extraction refused to start: server disk above threshold."""


def _run_extraction(text: str) -> dict:
    """
    Bridges an HTTP payload to the file engine via tempfiles, so the API
    inherits every CLI guardrail (disk abort, memory pause, audit counts).
    Shared by the sync endpoint and the async job worker.
    """
    with tempfile.TemporaryDirectory(prefix="dih_api_") as tmp:
        in_path = os.path.join(tmp, "input.txt")
        out_path = os.path.join(tmp, "output.jsonl")
        with open(in_path, "w", encoding="utf-8") as f:
            f.write(text)

        audit = bulletproof_processor(in_path, out_path, output_format="jsonl")

        if audit.get("aborted"):
            raise DiskAbortError("extraction aborted: server disk usage above threshold")

        records: list[dict] = []
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))

    return {
        "records": records,
        "audit": {
            "total": audit["total"],
            "matched": audit["matched"],
            "skipped": audit["skipped"],
        },
    }

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
        try:
            payload = _run_extraction(req.text)
        except DiskAbortError as exc:
            logger.error("extract_aborted disk_threshold_exceeded")
            raise HTTPException(status_code=507, detail=str(exc))
        logger.info(
            "extract_ok total=%d matched=%d skipped=%d",
            payload["audit"]["total"], payload["audit"]["matched"], payload["audit"]["skipped"],
        )
        return payload

    # Async jobs: 2 workers is deliberate -- extraction is CPU+disk bound, and
    # an API instance that saturates itself with background jobs stops
    # answering /health, which gets it restarted mid-job by the orchestrator.
    job_store = JobStore()
    job_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dih-job")

    def _execute_job(job_id: str, text: str) -> None:
        job_store.mark_running(job_id)
        try:
            payload = _run_extraction(text)
            job_store.mark_done(job_id, payload)
        except Exception as exc:  # noqa: BLE001 -- a job must never kill its worker thread
            job_store.mark_failed(job_id, str(exc))

    @app.post(
        "/extract/async",
        response_model=JobSubmitResponse,
        status_code=202,
        dependencies=[Depends(require_api_key)],
    )
    def extract_async(req: ExtractRequest) -> dict:
        job = job_store.create()
        job_pool.submit(_execute_job, job.id, req.text)
        return {"job_id": job.id, "status": "queued"}

    @app.get(
        "/jobs/{job_id}",
        response_model=JobStatusResponse,
        dependencies=[Depends(require_api_key)],
    )
    def job_status(job_id: str) -> dict:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job id")
        return {"job_id": job.id, "status": job.status, "result": job.result, "error": job.error}

    return app
