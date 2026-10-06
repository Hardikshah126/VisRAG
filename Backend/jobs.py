"""In-memory registry of ingestion jobs (processing / ready / failed).

Single-process only. After a restart the registry is empty, so callers fall
back to asking Qdrant whether a document has points."""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

_RETENTION_SECONDS = 2 * 60 * 60


@dataclass
class Job:
    doc_id: str
    filename: str
    status: str = "processing"  # processing | ready | failed
    stage: str = "queued"
    blocks: Optional[int] = None
    error: Optional[str] = None
    updated: float = field(default_factory=time.time)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, doc_id: str, filename: str) -> Job:
        with self._lock:
            self._prune()
            job = self._jobs[doc_id] = Job(doc_id=doc_id, filename=filename)
            return job

    def update(self, doc_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs.get(doc_id)
            if job:
                for key, value in changes.items():
                    setattr(job, key, value)
                job.updated = time.time()

    def get(self, doc_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(doc_id)

    def remove(self, doc_id: str) -> None:
        with self._lock:
            self._jobs.pop(doc_id, None)

    def _prune(self) -> None:
        cutoff = time.time() - _RETENTION_SECONDS
        stale = [k for k, j in self._jobs.items() if j.status != "processing" and j.updated < cutoff]
        for key in stale:
            del self._jobs[key]
