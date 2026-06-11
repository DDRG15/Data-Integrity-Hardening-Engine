"""
In-memory job store for async extraction.

Deliberately process-local: one Railway/Render instance, one store. The day a
second instance is added behind a load balancer, GET /jobs/{id} starts
returning 404 for jobs created on the other instance -- that is the exact
trigger for replacing this with Redis, and not one day earlier. Documented in
the ROADMAP as the Tier 3 scale path.
"""
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Completed jobs kept for polling before eviction. At 100 jobs of typical
# result size this is a few MB of RAM -- not a leak vector.
MAX_STORED_JOBS = 100


@dataclass
class Job:
    id: str
    status: str  # "queued" | "running" | "done" | "failed"
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)


class JobStore:
    """Thread-safe job registry. All mutations go through the lock."""

    def __init__(self, max_jobs: int = MAX_STORED_JOBS):
        self._max_jobs = max_jobs
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex, status="queued")
        with self._lock:
            self._evict_if_needed()
            self._jobs[job.id] = job
        logger.info("job_created id=%s", job.id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def mark_running(self, job_id: str) -> None:
        self._set(job_id, status="running")

    def mark_done(self, job_id: str, result: dict) -> None:
        self._set(job_id, status="done", result=result)
        logger.info("job_done id=%s", job_id)

    def mark_failed(self, job_id: str, error: str) -> None:
        self._set(job_id, status="failed", error=error[:300])
        logger.error("job_failed id=%s error=%s", job_id, error[:120])

    def _set(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in changes.items():
                setattr(job, key, value)

    def _evict_if_needed(self) -> None:
        # Caller holds the lock. Evict oldest *finished* jobs first; never
        # evict queued/running jobs -- losing an in-flight job means a client
        # polls a 404 for work the server accepted.
        if len(self._jobs) < self._max_jobs:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.status in ("done", "failed")),
            key=lambda j: j.created_at,
        )
        for job in finished:
            if len(self._jobs) < self._max_jobs:
                break
            del self._jobs[job.id]
            logger.info("job_evicted id=%s", job.id)
