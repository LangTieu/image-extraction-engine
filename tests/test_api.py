"""P7 API tests: v1 endpoints, in-process worker, review actions, exports.

Runs against a per-test temporary SQLite database + artifact dirs so the real
``service/data/service.db`` is never touched.
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

SEED_IMAGE = Path("benchmark/seed/coil_table/images/coil_table_001.png")


def _seed_result_json(**field_overrides: object) -> dict:
    """A result_json shaped the way the worker pipeline dumps FieldValue rows."""
    field: dict = {
        "name": "THICK",
        "value": "abc",
        "raw_text": "abc",
        "unit": "mm",
        "type": "number",
        "confidence": 0.42,
        "needs_review": True,
        "validation_results": [],
        "proposals": ["1.25"],
    }
    field.update(field_overrides)
    return {
        "source": {"file_name": "coil_table_001.png", "pages": []},
        "category": "industrial",
        "confidence": 0.42,
        "fields": [field],
        "cells": [],
        "tables": [],
        "validation_issues": [],
        "warnings": [],
    }


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient over a fresh temp DB, uploads dir and artifacts dir."""
    from service.api.app import app
    from service.core import db as db_mod
    from service.core.settings import settings

    monkeypatch.setattr(settings, "db_url", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    monkeypatch.setattr(settings, "rate_limit_per_minute", 0)
    settings.ensure_dirs()
    monkeypatch.setattr(db_mod, "_engine", None)
    monkeypatch.setattr(db_mod, "_session_factory", None)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    from service.core import db as db_mod

    yield _make_client(tmp_path, monkeypatch)
    if db_mod._engine is not None:  # close sqlite handles before tmp_path cleanup
        db_mod._engine.dispose()


def _seed_job_with_flagged_field(**field_overrides: object) -> str:
    """Insert a needs_review job + one flagged file directly into the test DB."""
    from service.core.db import JobFileModel, JobModel, get_session

    session = get_session()
    job = JobModel(id="job_test", profile="coil_table", status="needs_review", options={})
    session.add(job)
    session.add(
        JobFileModel(
            id="file_test",
            job_id="job_test",
            file_name="coil_table_001.png",
            stored_path="/tmp/x.png",
            mime_type="image/png",
            size_bytes=100,
            status="needs_review",
            result_json=_seed_result_json(**field_overrides),
        )
    )
    session.commit()
    return "job_test"


def _post_job(client: TestClient) -> str:
    with SEED_IMAGE.open("rb") as fh:
        resp = client.post(
            "/v1/jobs",
            files={"files": ("coil_table_001.png", fh, "image/png")},
            data={"export_formats": "xlsx,json"},
        )
    assert resp.status_code == 202, resp.text
    job_id: str = resp.json()["job_id"]
    return job_id


def _poll_job(client: TestClient, job_id: str, timeout_s: float = 120.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["status"] in ("completed", "needs_review", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in {timeout_s}s")


# ------------------------------------------------------------------ basics


def test_health(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_version(client: TestClient) -> None:
    resp = client.get("/v1/version")
    assert resp.status_code == 200
    assert resp.json()["engine"]


def test_profiles_lists_sample(client: TestClient) -> None:
    resp = client.get("/v1/profiles")
    assert resp.status_code == 200
    body = resp.json()
    assert body["profiles"], "bundled profiles must be listed"
    assert any(p["name"] for p in body["profiles"])
    assert body["default"]


# -------------------------------------------------- POST /jobs + worker E2E


def test_create_job_and_inprocess_worker_completes(client: TestClient) -> None:
    """Real in-process worker on a seed image; 1x1 stub -> empty result is fine."""
    job_id = _post_job(client)
    job = _poll_job(client, job_id)
    assert job["status"] == "completed", job.get("error")

    result = client.get(f"/v1/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.json()["job_id"] == job_id

    review = client.get(f"/v1/jobs/{job_id}/review")
    assert review.status_code == 200
    assert "pending" in review.json()


def test_list_jobs_shows_created(client: TestClient) -> None:
    job_id = _post_job(client)
    _poll_job(client, job_id)
    jobs = client.get("/v1/jobs").json()
    assert any(j["id"] == job_id for j in jobs)


def test_get_unknown_job_404(client: TestClient) -> None:
    assert client.get("/v1/jobs/nope").status_code == 404


# ------------------------------------------------------------- review + PATCH


def test_review_lists_flagged_pipeline_shaped_fields(client: TestClient) -> None:
    """Fields dumped by the pipeline use the key ``name`` — the review endpoint
    must still surface them (regression guard for the P7 review integration)."""
    job_id = _seed_job_with_flagged_field()
    body = client.get(f"/v1/jobs/{job_id}/review").json()
    assert body["pending"], "flagged field must appear in /review pending"
    item = body["pending"][0]
    assert item["field_id"] == "THICK" or item["field_name"] == "THICK"
    assert item["value"] == "abc"


def test_patch_correct_updates_value_and_audit_log(client: TestClient) -> None:
    job_id = _seed_job_with_flagged_field()
    resp = client.patch(
        f"/v1/jobs/{job_id}/fields/THICK", json={"action": "correct", "value": "1.25"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"

    result = client.get(f"/v1/jobs/{job_id}/result").json()
    field = result["files"][0]["result"]["fields"][0]
    assert field["value"] == "1.25"
    assert field["needs_review"] is False
    assert len(result["files"][0]["result"]["audit_log"]) == 1


def test_patch_correct_rejects_invalid_dictionary_value(client: TestClient) -> None:
    """A corrected value failing the industrial dictionary must not be 'ok'."""
    job_id = _seed_job_with_flagged_field()
    resp = client.patch(
        f"/v1/jobs/{job_id}/fields/THICK", json={"action": "correct", "value": "not-a-number"}
    )
    assert resp.status_code == 200
    result = client.get(f"/v1/jobs/{job_id}/result").json()
    field = result["files"][0]["result"]["fields"][0]
    assert field.get("validation") != "ok"


def test_patch_accept_clears_flag(client: TestClient) -> None:
    job_id = _seed_job_with_flagged_field()
    resp = client.patch(f"/v1/jobs/{job_id}/fields/THICK", json={"action": "accept"})
    assert resp.status_code == 200
    field = client.get(f"/v1/jobs/{job_id}/result").json()["files"][0]["result"]["fields"][0]
    assert field["needs_review"] is False
    assert field["value"] == "abc"


def test_patch_reject_nulls_value(client: TestClient) -> None:
    job_id = _seed_job_with_flagged_field()
    resp = client.patch(f"/v1/jobs/{job_id}/fields/THICK", json={"action": "reject"})
    assert resp.status_code == 200
    field = client.get(f"/v1/jobs/{job_id}/result").json()["files"][0]["result"]["fields"][0]
    assert field["value"] is None
    assert field["rejected"] is True


def test_patch_unknown_field_404(client: TestClient) -> None:
    job_id = _seed_job_with_flagged_field()
    resp = client.patch(f"/v1/jobs/{job_id}/fields/NOPE", json={"action": "accept"})
    assert resp.status_code == 404


def test_patch_invalid_action_422(client: TestClient) -> None:
    job_id = _seed_job_with_flagged_field()
    resp = client.patch(f"/v1/jobs/{job_id}/fields/THICK", json={"action": "delete"})
    assert resp.status_code == 422


def test_patch_correct_without_value_422(client: TestClient) -> None:
    job_id = _seed_job_with_flagged_field()
    resp = client.patch(f"/v1/jobs/{job_id}/fields/THICK", json={"action": "correct"})
    assert resp.status_code == 422


# ----------------------------------------------------------------- exports


def test_exports_json_and_xlsx(client: TestClient) -> None:
    job_id = _seed_job_with_flagged_field(needs_review=False, value="1.25")
    # exports require a finished job status; PATCH accept flips it to completed
    resp = client.patch(f"/v1/jobs/{job_id}/fields/THICK", json={"action": "accept"})
    assert resp.status_code == 200

    created = client.post(f"/v1/jobs/{job_id}/exports", json={"formats": ["xlsx", "json"]})
    assert created.status_code == 202, created.text

    js = client.get(f"/v1/jobs/{job_id}/exports/json")
    assert js.status_code == 200
    payload = json.loads(js.content)
    assert payload

    xl = client.get(f"/v1/jobs/{job_id}/exports/xlsx")
    assert xl.status_code == 200
    wb = openpyxl.load_workbook(BytesIO(xl.content))
    assert wb.sheetnames


def test_exports_before_finish_409(client: TestClient) -> None:
    from service.core.db import JobModel, get_session

    session = get_session()
    session.add(JobModel(id="job_queued", profile="coil_table", status="queued", options={}))
    session.commit()
    resp = client.post("/v1/jobs/job_queued/exports", json={"formats": ["json"]})
    assert resp.status_code == 409


# ------------------------------------------------------------------- auth


@pytest.fixture()
def api_key_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    from service.core import db as db_mod

    monkeypatch.setenv("IMAGE_ENGINE_API_KEY", "test-key-123")
    yield _make_client(tmp_path, monkeypatch)
    if db_mod._engine is not None:
        db_mod._engine.dispose()


def test_auth_missing_wrong_and_correct_key(api_key_client: TestClient) -> None:
    assert api_key_client.get("/v1/version").status_code == 401
    assert (
        api_key_client.get("/v1/version", headers={"X-API-Key": "wrong"}).status_code == 401
    )
    assert (
        api_key_client.get("/v1/version", headers={"X-API-Key": "test-key-123"}).status_code
        == 200
    )


def test_auth_health_still_open_without_key(api_key_client: TestClient) -> None:
    assert api_key_client.get("/v1/health").status_code == 200
