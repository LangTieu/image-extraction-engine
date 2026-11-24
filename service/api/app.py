"""FastAPI application (P7): v1 endpoints for jobs, review actions and exports.

Auth: when ``IMAGE_ENGINE_API_KEY`` is set in the environment, every /v1 call
(except /v1/health) requires header ``X-API-Key``. A basic per-IP rate limit
and upload type/size validation are always applied. External vision APIs stay
off unless ``SERVICE_EXTERNAL_VISION_APIS=true``; ``/v1/version`` reports the
flag so the UI can show the indicator.

Serves the built web UI (``service/web/dist``) as static files when present.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm.attributes import flag_modified

from service.api.schemas import JobCreated, JobOut, JobStatus
from service.core.db import JobFileModel, JobModel, get_session, new_id
from service.core.settings import settings
from service.worker.runner import cancel_job, enqueue_job

app = FastAPI(title=settings.app_name, version="7.0.0")
_origins = [o for o in settings.cors_origins.split(",") if o]
if _origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"]
    )
router = APIRouter(prefix=settings.api_prefix)

ENGINE_VERSION = "7.0.0"

# ---------------------------------------------------------------- middleware


@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    try:
        path = request.url.path
        if path.startswith(settings.api_prefix) and not path.endswith("/health"):
            key = os.environ.get(settings.api_key_env, "")
            if key and request.headers.get("X-API-Key") != key:
                raise HTTPException(401, "missing or invalid X-API-Key header")
            limit = settings.rate_limit_per_minute
            if limit > 0:
                client = request.client.host if request.client else "?"
                bucket = _RATE[client]
                now = time.time()
                while bucket and bucket[0] < now - 60:
                    bucket.popleft()
                if len(bucket) >= limit:
                    raise HTTPException(429, "rate limit exceeded")
                bucket.append(now)
        return await call_next(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


_RATE: dict[str, deque] = defaultdict(deque)


# ---------------------------------------------------------------- helpers


def _job_or_404(job_id: str) -> JobModel:
    job = get_session().get(JobModel, job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} not found")
    return job


def _file_or_404(job_id: str, file_id: str) -> JobFileModel:
    jf = get_session().get(JobFileModel, file_id)
    if jf is None or jf.job_id != job_id:
        raise HTTPException(404, f"file {file_id} not found in job {job_id}")
    return jf


def _job_out(job: JobModel) -> JobOut:
    session = get_session()
    files = (
        session.query(JobFileModel)
        .filter(JobFileModel.job_id == job.id)
        .order_by(JobFileModel.created_at)
        .all()
    )
    from service.api.schemas import JobFileOut, JobStatus

    return JobOut(
        id=job.id,
        status=cast(JobStatus, job.status),
        profile=job.profile,
        options=job.options or {},
        progress=job.progress,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        files=[
            JobFileOut(
                id=f.id,
                file_name=f.file_name,
                status=cast(JobStatus, f.status),
                mime_type=f.mime_type,
                size_bytes=f.size_bytes,
                confidence=f.confidence,
                error=f.error,
                result=f.result_json,
                exports=f.exports or {},
            )
            for f in files
        ],
    )


def _refresh_job_status(job_id: str) -> None:
    session = get_session()
    job = session.get(JobModel, job_id)
    if job is None:
        return
    statuses = {
        f.status
        for f in session.query(JobFileModel).filter(JobFileModel.job_id == job_id).all()
    }
    job.status = (
        "completed"
        if statuses <= {"completed"}
        else ("failed" if statuses == {"failed"} else "needs_review")
    )
    session.commit()


# ---------------------------------------------------------------- endpoints


@router.post("/jobs", response_model=JobCreated, status_code=202)
def create_job(
    files: list[UploadFile] = File(...),
    profile: str | None = Query(default=None),
    category: str | None = Query(default=None, description="forced document category"),
    languages: str | None = Query(default=None, description="OCR languages, e.g. vi+en"),
    export_formats: str | None = Query(default="xlsx,json", description="comma separated"),
):
    """Upload one or more images/PDFs and queue an extraction job."""
    if not files:
        raise HTTPException(422, "at least one file is required")
    allowed_types = {t.strip() for t in settings.allowed_upload_types.split(",")}
    max_bytes = settings.max_upload_mb * 1024 * 1024
    settings.ensure_dirs()

    session = get_session()
    options: dict = {
        "category": category,
        "languages": languages,
        "export_formats": [f for f in (export_formats or "").split(",") if f],
    }
    job = JobModel(
        id=new_id("job"), profile=profile or settings.profile, status="queued", options=options
    )
    session.add(job)
    session.flush()
    count = 0
    for up in files:
        if up.content_type not in allowed_types:
            raise HTTPException(415, f"{up.filename}: unsupported type {up.content_type!r}")
        data = up.file.read()
        if len(data) > max_bytes:
            raise HTTPException(413, f"{up.filename}: exceeds {settings.max_upload_mb} MB limit")
        jf = JobFileModel(
            id=new_id("file"),
            job_id=job.id,
            file_name=up.filename or "upload",
            stored_path="",
            mime_type=up.content_type,
            size_bytes=len(data),
        )
        suffix = Path(up.filename or "upload.bin").suffix.lower() or ".bin"
        stored = settings.uploads_dir / f"{jf.id}{suffix}"
        stored.write_bytes(data)
        jf.stored_path = str(stored)
        session.add(jf)
        count += 1
    session.commit()
    enqueue_job(job.id)
    return JobCreated(
        job_id=job.id, status=cast(JobStatus, job.status), files=count
    )


@router.get("/jobs", response_model=list[JobOut])
def list_jobs():
    session = get_session()
    jobs = session.query(JobModel).order_by(JobModel.created_at.desc()).limit(100).all()
    return [_job_out(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str):
    return _job_out(_job_or_404(job_id))


@router.get("/jobs/{job_id}/result")
def get_result(job_id: str):
    """Unified JSON result of every file in the job."""
    job = _job_or_404(job_id)
    out = _job_out(job)
    return {
        "job_id": job.id,
        "status": job.status,
        "files": [
            {
                "file_id": f.id,
                "file_name": f.file_name,
                "status": f.status,
                "confidence": f.confidence,
                "result": f.result,
            }
            for f in out.files
        ],
    }


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    """Cancel a queued/running job (best effort for the in-process worker)."""
    job = _job_or_404(job_id)
    if job.status in ("completed", "failed"):
        raise HTTPException(409, f"job already {job.status}")
    cancel_job(job.id)
    return {"job_id": job.id, "status": "cancel_requested"}


@router.get("/jobs/{job_id}/review")
def pending_review(job_id: str):
    """Fields and cells flagged for review, per file."""
    _job_or_404(job_id)
    session = get_session()
    files = session.query(JobFileModel).filter(JobFileModel.job_id == job_id).all()
    items = []
    for f in files:
        for field in (f.result_json or {}).get("fields", []):
            if field.get("needs_review"):
                items.append(
                    {
                        "file_id": f.id,
                        "field_id": field.get("field_id") or field.get("field_name"),
                        "field_name": field.get("field_name"),
                        "value": field.get("value"),
                        "confidence": field.get("confidence"),
                        "reasons": field.get("review_reasons") or field.get("parse_notes"),
                    }
                )
    return {"job_id": job_id, "pending": items}


@router.patch("/jobs/{job_id}/fields/{field_id}")
def review_field(job_id: str, field_id: str, body: dict):
    """accept | correct | reject one field; re-validates and appends audit log."""
    action = body.get("action")
    value = body.get("value")
    if action not in ("accept", "correct", "reject"):
        raise HTTPException(422, "body.action must be accept|correct|reject")
    if action == "correct" and value is None:
        raise HTTPException(422, "correct requires body.value")

    session = get_session()
    target: dict[str, Any] | None = None
    jf: JobFileModel | None = None
    for f in session.query(JobFileModel).filter(JobFileModel.job_id == job_id).all():
        for field in (f.result_json or {}).get("fields", []):
            fid = field.get("field_id") or field.get("field_name")
            if fid == field_id:
                target, jf = field, f
                break
        if target is not None:
            break
    if target is None:
        raise HTTPException(404, f"field {field_id} not found in job {job_id}")
    assert jf is not None and jf.result_json is not None

    if action == "accept":
        target["needs_review"] = False
    elif action == "reject":
        target["value"] = None
        target["needs_review"] = False
        target["rejected"] = True
    else:
        target["value"] = value
        target["needs_review"] = False
        # Re-validate the corrected value against the industrial dictionary.
        try:
            from engine.schema.industrial_fields import validate_value

            if target.get("field_name") and value is not None:
                validate_value(target["field_name"], value)
            target["validation"] = "ok"
        except Exception as exc:
            target["validation"] = f"failed: {exc}"
    audit = jf.result_json.setdefault("audit_log", [])
    audit.append({"field_id": field_id, "action": action, "value": value, "at": time.time()})
    fields = jf.result_json.get("fields", [])
    # In-place edits of a JSON column are not detected by SQLAlchemy.
    flag_modified(jf, "result_json")
    jf.status = "needs_review" if any(x.get("needs_review") for x in fields) else "completed"
    session.commit()
    _refresh_job_status(job_id)
    return {"job_id": job_id, "field_id": field_id, "action": action, "status": jf.status}


@router.post("/jobs/{job_id}/exports", status_code=202)
def create_exports(job_id: str, body: dict | None = None):
    """(Re)build exports for all files of the job in the requested formats."""
    formats = (body or {}).get("formats") or ["xlsx", "json"]
    from service.worker.runner import build_exports

    job = _job_or_404(job_id)
    if job.status not in ("completed", "needs_review"):
        raise HTTPException(409, "job has no finished results to export yet")
    done = build_exports(job_id, formats)
    return {"job_id": job_id, "formats": formats, "files": done}


@router.get("/jobs/{job_id}/exports/{fmt}")
def export_file(job_id: str, fmt: str):
    """Download one exported artifact (xlsx|csv|json|pdf) for one file."""
    if fmt not in ("xlsx", "csv", "json", "pdf"):
        raise HTTPException(422, "fmt must be one of xlsx|csv|json|pdf")
    _job_or_404(job_id)
    session = get_session()
    for f in session.query(JobFileModel).filter(JobFileModel.job_id == job_id).all():
        info = (f.exports or {}).get(fmt)
        if info is None:
            continue
        path = settings.artifacts_dir / f.id / info["path"]
        if not path.exists():
            raise HTTPException(410, f"artifact missing on disk: {info['path']}")
        download_name = Path(f.file_name).stem + "." + fmt
        return FileResponse(path, media_type=info["mime"], filename=download_name)
    raise HTTPException(404, f"no {fmt} export in job {job_id}")


@router.get("/profiles")
def list_profiles():
    from engine.industrial.profiles import bundled_profiles

    profiles = bundled_profiles()
    return {
        "profiles": [
            {"name": p.name, "category": getattr(p, "category", None)} for p in profiles
        ],
        "default": settings.profile,
    }


@router.get("/health")
def health():
    session = get_session()
    return {
        "status": "ok",
        "jobs": session.query(JobModel).count(),
        "worker_mode": settings.worker_mode,
    }


@router.get("/version")
def version():
    return {
        "engine": ENGINE_VERSION,
        "external_vision_apis": settings.external_vision_apis,
        "profile": settings.profile,
    }


app.include_router(router)


# Static web UI (built by service/web: npm run build -> service/web/dist).
_dist = Path(__file__).resolve().parents[1] / "web" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
