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

import dataclasses
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from service.core.db import JobFileModel, JobModel, get_session, session_scope
from service.core.settings import settings
from service.core.status import derive_job_status

logger = logging.getLogger(__name__)

# Maps a JobFileModel row to the exports dict entry written after extraction.
DEFAULT_EXPORT_FORMATS = ("xlsx", "json", "csv")

# Cancel flags for in-process jobs; retry/timeout knobs.
CANCELLED: set[str] = set()
FILE_TIMEOUT_S = 300  # per-file extraction budget
JOB_TIMEOUT_S = 1800  # whole-job budget; overruns are marked failed
MAX_RETRIES = 2  # retry a failing file before marking it failed

# Per in-process worker run: a token the zombie thread's writes must still own
# to be allowed to commit. When a file times out, the token is revoked so the
# abandoned daemon thread cannot later mark the file completed / dump results.
_WORKER_TOKENS: dict[str, str] = {}  # job_id -> current valid token


def process_job(job_id: str) -> None:
    """Run one job: extract every file, then export per-file artifacts."""
    with session_scope() as session:
        _run_job(job_id, session)


def _run_job(job_id: str, session: Session) -> None:
    job = session.get(JobModel, job_id)
    if job is None:
        logger.error("job %s not found", job_id)
        return
    job.status = "processing"
    job.progress = 5
    session.commit()

    files = session.query(JobFileModel).filter(JobFileModel.job_id == job_id).all()
    total = len(files) or 1
    deadline = time.monotonic() + JOB_TIMEOUT_S
    token = uuid4().hex
    _WORKER_TOKENS[job_id] = token
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
                    _process_file_with_timeout(jf, job, token)
                    break
                except WorkerSuperseded:
                    # A timeout revoked this run's token: stop retrying and let
                    # the sweep below record the timeout, not a phantom success.
                    jf.status = "failed"
                    jf.error = f"extraction exceeded {FILE_TIMEOUT_S}s"[:1900]
                    session.commit()
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
            if time.monotonic() > deadline:
                logger.error("job %s exceeded %ss; marking failed", job_id, JOB_TIMEOUT_S)
                _revoke_token(job_id)
                job.status = "failed"
                job.error = f"job exceeded {JOB_TIMEOUT_S}s processing budget"
                job.progress = 100
                session.commit()
                return
        statuses = {jf.status for jf in files}
        job.status = derive_job_status(statuses)  # same derivation as the API
        job.progress = 100
        session.commit()
    except Exception as exc:  # job-level crash
        logger.exception("job %s crashed", job_id)
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.progress = 100
        session.commit()
    finally:
        _revoke_token(job_id)
        CANCELLED.discard(job_id)  # prune the cancel flag once the run is over


class WorkerSuperseded(RuntimeError):
    """Raised in a zombie worker thread once its run's token was revoked."""


def _revoke_token(job_id: str) -> None:
    _WORKER_TOKENS.pop(job_id, None)


def _check_token(job_id: str, token: str) -> None:
    """Zombie-thread gate: only the current run of a job may commit."""
    if _WORKER_TOKENS.get(job_id) != token:
        raise WorkerSuperseded(f"worker run for job {job_id} was superseded (timeout/cancel)")


def _process_file_with_timeout(jf: JobFileModel, job: JobModel, token: str) -> None:
    """Run _process_file under a hard wall-clock budget (daemon thread join).

    On timeout the run's token is revoked first, so the abandoned thread
    cannot commit ``completed`` status or results afterwards (review finding
    #5: timeout zombie threads).
    """
    import threading

    box: dict[str, Any] = {}

    def run():
        try:
            _check_token(job.id, token)  # cancelled/retimed-out before we even start
            _process_file(jf, job, token)
        except Exception as exc:  # propagate to the timeout wrapper
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(FILE_TIMEOUT_S)
    if t.is_alive():
        _revoke_token(job.id)  # zombie thread's later commits now raise
        raise TimeoutError(f"extraction exceeded {FILE_TIMEOUT_S}s")
    if "exc" in box:
        raise box["exc"]


def cancel_job(job_id: str) -> None:
    """Best-effort cancellation for the in-process worker mode."""
    CANCELLED.add(job_id)
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        if job is not None and job.status in ("queued", "processing"):
            job.status = "failed"
            job.error = "cancelled"
            job.progress = 100
            session.commit()


def build_exports(job_id: str, formats: list[str]) -> list[str]:
    """(Re)build export artifacts for every finished file of a job."""
    with session_scope() as session:
        return _build_exports(job_id, formats, session)


def _build_exports(
    job_id: str, formats: list[str], session: Session
) -> list[str]:
    from engine.export import ExportOptions, export_batch

    job = session.get(JobModel, job_id)
    job_options: dict[str, Any] = (job.options if job is not None else None) or {}
    done: list[str] = []
    for jf in session.query(JobFileModel).filter(JobFileModel.job_id == job_id).all():
        if jf.result_json is None:
            continue
        from engine.schema.models import ExtractionResult

        # result_json from the pipeline / review PATCH is a partial dict:
        # backfill required top-level keys the exporters need before validating.
        raw = jf.result_json
        raw.setdefault("document_type", "unknown")
        raw.setdefault("extraction_status", "completed")
        result = ExtractionResult.model_validate(raw)
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


def _load_image(path: Path, dpi: int = 300):
    from engine.preprocessing.io import load_input

    return load_input(path, dpi=dpi)[0].data


def _process_file(jf: JobFileModel, job: JobModel, token: str | None = None) -> None:
    from engine.export import ExportOptions, export_batch
    from engine.industrial.pipeline import IndustrialVision
    from engine.ocr.pipeline import GeneralOCR
    from engine.ocr.tesseract_backend import TesseractEngine
    from engine.options import OcrOptions, PreprocessOptions
    from engine.preprocessing.pipeline import PreprocessingPipeline
    from engine.validation.validate_result import validate_result

    session = get_session()
    try:
        if token is not None:
            _check_token(job.id, token)  # zombie guard before any write
        jf.status = "processing"
        session.commit()

        profile = job.profile or settings.profile
        options: dict[str, Any] = dict(job.options or {})

        # The API's `profile` is a routing label (e.g. "industrial"), not a
        # bundled preprocessing YAML name; map it to the default profile the
        # old from_dict path effectively ran with.
        available = set(PreprocessingPipeline.bundled_profiles())
        preprocessing_name = profile if profile in available else "industrial_screen_photo"
        preprocess_options = PreprocessOptions(
            profile=preprocessing_name,
            overrides=options.get("preprocessing", {}),
            dpi=int(options.get("dpi", PreprocessOptions.dpi)),
        )
        preprocessing = PreprocessingPipeline.from_options(preprocess_options)
        ocr_options = OcrOptions(
            tesseract_lang=options.get("languages", OcrOptions.tesseract_lang),
            pdf_dpi=int(options.get("pdf_dpi", OcrOptions.pdf_dpi)),
        )
        ocr_engine = TesseractEngine.from_options(ocr_options)
        logger.info(
            "file %s effective options: preprocess=%s ocr=%s",
            jf.id,
            dataclasses.asdict(preprocess_options),
            dataclasses.asdict(ocr_options),
        )
        vision = IndustrialVision(
            preprocessing=preprocessing,
            ocr=GeneralOCR.from_options([ocr_engine], ocr_options),
        )
        image = _load_image(Path(jf.stored_path), dpi=preprocess_options.dpi)
        if token is not None:
            _check_token(job.id, token)  # zombie guard after the slow OCR/vision step
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
    except WorkerSuperseded:
        # Timed-out zombie thread: drop the results instead of committing them.
        logger.warning("file %s: superseded worker thread discarded its result", jf.id)
    except Exception as exc:
        logger.exception("file %s failed", jf.id)
        jf.status = "failed"
        jf.error = f"{type(exc).__name__}: {exc}"[:1900]
        session.commit()
    finally:
        session.close()


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
