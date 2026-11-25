"""Job status derivation shared by the API and the worker."""

from __future__ import annotations


def derive_job_status(statuses: set[str]) -> str:
    """Single source of truth for job status (API and runner).

    Empty set (no files) stays ``queued`` instead of flipping to ``completed``
    (review finding #9: ``set() <= {"completed"}`` is True).
    """
    if not statuses:
        return "queued"
    if statuses <= {"completed"}:
        return "completed"
    if statuses == {"failed"}:
        return "failed"
    return "needs_review" if statuses & {"completed", "needs_review"} else "failed"
