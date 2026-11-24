"""Worker (P7): turns uploaded files into ExtractionResults and exports.

Two modes (``service.core.settings.Settings.worker_mode``):

* ``inprocess`` (default): the API runs the job in a background thread —
  no Redis needed, results land in the same SQLite/Postgres database.
* ``rq``: the same ``process_job`` function is enqueued through RQ on the
  configured Redis URL, for multi-worker deployments.

Every per-file failure is isolated: the file is marked ``failed`` with the
message and the job continues; only a job-level crash marks the job ``failed``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from service.core.db import JobFileModel, JobModel, get_session
from service.core.settings import settings

logger = logging.getLogger(__name__)

# Maps a JobFileModel row to the exports dict entry written after extraction.
DEFAULT_EXPORT_FORMATS = ("xlsx", "json", "csv")

# Cancel flags for in-process jobs; retry/timeout knobs.
CANCELLED: set[str] = set()
FILE_TIMEOUT_S = 300  # per-file extraction budget
MAX_RETRIES = 2  # retry a failing file before marking it failed


def process_job(job_id: str) -> None:
    """Run one job: extract every file, then export per-file artifacts."""
    session = get_session()
    job = session.get(JobModel, job_id)
    if job is None:
        logger.error("job %s not found", job_id)
        return
    job.status = "processing"
    job.progress = 5
    session.commit()

    files = session.query(JobFileModel).filter(JobFileModel.job_id == job_id).all()
    total = len(files) or 1
    try:
        for i, jf in enumerate(files):
            if job_id in CANCELLED:
                job.status = "failed"
                job.error = "cancelled"
                job.progress = 100
                session.commit()
                return
            attempts = 0
            while True:
                try:
                    _process_file_with_timeout(jf, job)
                    break
                except Exception as exc:
                    attempts += 1
                    logger.warning("file %s attempt %d failed: %s", jf.id, attempts, exc)
                    if attempts > MAX_RETRIES:
                        jf.status = "failed"
                        jf.error = f"{type(exc).__name__}: {exc}"[:1900]
                        session.commit()
                        break
            job.progress = 5 + int(90 * (i + 1) / total)
            session.commit()
        statuses = {jf.status for jf in files}
        if statuses <= {"completed"}:
            job.status = "completed"
        elif "failed" not in statuses:
            job.status = "needs_review"
        else:
            job.status = "needs_review" if statuses & {"completed", "needs_review"} else "failed"
        job.progress = 100
        session.commit()
    except Exception as exc:  # job-level crash
        logger.exception("job %s crashed", job_id)
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.progress = 100
        session.commit()


def _process_file_with_timeout(jf: JobFileModel, job: JobModel) -> None:
    """Run _process_file under a hard wall-clock budget (daemon thread join)."""
    import threading

    box: dict[str, Any] = {}

    def run():
        try:
            _process_file(jf, job)
        except Exception as exc:  # propagate to the timeout wrapper
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(FILE_TIMEOUT_S)
    if t.is_alive():
        raise TimeoutError(f"extraction exceeded {FILE_TIMEOUT_S}s")
    if "exc" in box:
        raise box["exc"]


def cancel_job(job_id: str) -> None:
    """Best-effort cancellation for the in-process worker mode."""
    CANCELLED.add(job_id)
    session = get_session()
    job = session.get(JobModel, job_id)
    if job is not None and job.status in ("queued", "processing"):
        job.status = "failed"
        job.error = "cancelled"
        job.progress = 100
        session.commit()


def build_exports(job_id: str, formats: list[str]) -> list[str]:
    """(Re)build export artifacts for every finished file of a job."""
    from engine.export import ExportOptions, export_batch

    session = get_session()
    job = session.get(JobModel, job_id)
    job_options: dict[str, Any] = (job.options if job is not None else None) or {}
    done: list[str] = []
    for jf in session.query(JobFileModel).filter(JobFileModel.job_id == job_id).all():
        if jf.result_json is None:
            continue
        from engine.schema.models import ExtractionResult

        result = ExtractionResult.model_validate(jf.result_json)
        out_dir = settings.artifacts_dir / jf.id
        out_dir.mkdir(parents=True, exist_ok=True)
        options = ExportOptions(values_only=bool(job_options.get("values_only", False)))
        manifest = export_batch([result], out_dir, formats=formats, options=options)
        jf.exports = {
            entry["format"]: {
                "path": entry["path"],
                "mime": entry["mime"],
                "checksum": entry["sha256"],
                "size": (out_dir / entry["path"]).stat().st_size,
            }
            for entry in manifest.get("files", [])
        }
        session.commit()
        done.append(jf.id)
    return done


def _load_image(path: Path):
    from engine.preprocessing.io import load_input

    loaded = load_input(path)
    return loaded[0].data


def _process_file(jf: JobFileModel, job: JobModel) -> None:
    from engine.export import ExportOptions, export_batch
    from engine.industrial.pipeline import IndustrialVision
    from engine.ocr.pipeline import GeneralOCR
    from engine.ocr.tesseract_backend import TesseractEngine
    from engine.preprocessing.pipeline import PreprocessingPipeline
    from engine.validation.validate_result import validate_result

    session = get_session()
    try:
        jf.status = "processing"
        session.commit()

        profile = job.profile or settings.profile
        options: dict[str, Any] = dict(job.options or {})

        preprocessing = PreprocessingPipeline.from_dict(
            profile, options.get("preprocessing", {})
        )
        ocr_engine = TesseractEngine()
        if options.get("languages"):
            ocr_engine = TesseractEngine(lang=options["languages"])
        vision = IndustrialVision(
            preprocessing=preprocessing,
            ocr=GeneralOCR([ocr_engine]),
        )
        image = _load_image(Path(jf.stored_path))
        result = vision.process(image, file_name=jf.file_name)
        if options.get("category"):  # forced document category
            result.document_type = options["category"]
        result = validate_result(result)

        jf.result_json = result.model_dump(mode="json")
        field_conf = [f.confidence for f in result.fields if f.confidence is not None]
        jf.confidence = float(sum(field_conf) / len(field_conf)) if field_conf else None
        flagged = any(f.needs_review for f in result.fields)
        needs = result.extraction_status.value == "needs_review"
        jf.status = "needs_review" if flagged or needs else "completed"

        out_dir = settings.artifacts_dir / jf.id
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = export_batch(
            [result],
            out_dir,
            formats=list(options.get("export_formats", DEFAULT_EXPORT_FORMATS)),
            options=ExportOptions(values_only=bool(options.get("values_only", False))),
        )
        jf.exports = {
            entry["format"]: {
                "path": entry["path"],  # file name inside artifacts_dir/<file id>/
                "mime": entry["mime"],
                "checksum": entry["sha256"],
                "size": (out_dir / entry["path"]).stat().st_size,
            }
            for entry in manifest.get("files", [])
        }
        session.commit()
    except Exception as exc:
        logger.exception("file %s failed", jf.id)
        jf.status = "failed"
        jf.error = f"{type(exc).__name__}: {exc}"[:1900]
        session.commit()


def enqueue_job(job_id: str) -> None:
    """Hand the job to the configured worker mode."""
    if settings.worker_mode == "rq":
        try:
            from redis import Redis  # type: ignore
            from rq import Queue  # type: ignore

            queue = Queue("iee", connection=Redis.from_url(settings.redis_url))
            queue.enqueue("service.worker.runner.process_job", job_id)
            return
        except Exception as exc:  # Redis down -> fall back per brief
            logger.warning("RQ enqueue failed (%s); running in-process", exc)
    import threading

    threading.Thread(target=process_job, args=(job_id,), daemon=True).start()
