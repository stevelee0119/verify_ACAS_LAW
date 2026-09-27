"""Manual reanalysis survives deployments without changing the user's inputs."""
import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from apps.api.db import Document, VerificationRun
from apps.api.job_control import DurableJob, JobConflict, JobStore, enqueue_run
from apps.api.services import execute_run
from packages.common.config import get_settings
from packages.verification_engine import VerificationPipeline
from test_operations_completion import completed, ops, ops_client, seeded_run


def test_manual_retry_after_deployment_reaches_the_pipeline(ops, monkeypatch):
    run = seeded_run(ops)
    store = JobStore(ops)
    store.cancel(run.id)
    monkeypatch.setattr(get_settings(), "rule_version", "retry-regression-new-rules")
    monkeypatch.setattr(get_settings(), "ocr_max_pages", get_settings().ocr_max_pages + 1)
    called = []

    def pipeline(self, run_id, context, documents, **kwargs):
        called.append(run_id)
        assert context.issue_dates == {"issue-a": "2020-01-02"}
        assert documents[0].filename == "original.txt"
        assert self.settings.rule_version == "retry-regression-new-rules"
        return completed(run)

    monkeypatch.setattr(VerificationPipeline, "run", pipeline)
    child_id = store.retry(run.id)
    execute_run(child_id, store=store)
    assert called == [child_id]
    assert store.status(child_id)["state"] == "COMPLETED"
    with ops() as session:
        parent = session.get(DurableJob, run.id)
        child = session.get(DurableJob, child_id)
        assert child.snapshot["documents"] == parent.snapshot["documents"]
        assert child.snapshot["context"] == parent.snapshot["context"]
        assert child.snapshot["security"] == parent.snapshot["security"]
        assert child.snapshot["execution"]["budget"] == parent.snapshot["execution"]["budget"]
        assert child.budget_run_id == parent.budget_run_id
        assert child.snapshot["execution"]["settings"]["rule_version"] != parent.snapshot["execution"]["settings"]["rule_version"]
        saved = session.get(VerificationRun, child_id)
        assert saved.input_snapshot == child.snapshot
        assert saved.verification_key != run.verification_key


def test_retry_from_old_history_does_not_return_a_failed_child(ops):
    run = seeded_run(ops)
    store = JobStore(ops)
    store.cancel(run.id)
    first = store.retry(run.id)
    with ops() as session:
        session.get(DurableJob, first).state = "FAILED"
        session.get(VerificationRun, first).state = "FAILED"
        session.commit()
    second = store.retry(run.id)
    assert second not in {run.id, first}
    assert store.retry(run.id) == second
    assert store.retry(first) == second
    assert store.status(second)["retry_of"] == first


def test_configuration_drift_stops_without_useless_automatic_retries(ops, monkeypatch):
    run = seeded_run(ops)
    monkeypatch.setattr(get_settings(), "rule_version", "retry-regression-new-rules")
    store = JobStore(ops)
    execute_run(run.id, store=store)
    status = store.status(run.id)
    assert status["state"] == "FAILED"
    assert status["attempts"] == 1
    assert status["last_error"] == "EXECUTION_SETTINGS_CHANGED"
    assert status["history"][0]["error"] == "EXECUTION_SETTINGS_CHANGED"


def test_retry_rejects_tampered_snapshot_instead_of_signing_it_again(ops):
    run = seeded_run(ops)
    store = JobStore(ops)
    store.cancel(run.id)
    with ops() as session:
        job = session.get(DurableJob, run.id)
        changed = copy.deepcopy(job.snapshot)
        changed["context"]["issue_dates"] = {"tampered": "2099-01-01"}
        job.snapshot = changed
        session.commit()
    with pytest.raises(JobConflict, match="무결성"):
        store.retry(run.id)
    with ops() as session:
        assert len(session.scalars(select(VerificationRun)).all()) == 1


def test_retries_from_different_history_entries_share_one_active_child(ops):
    run = seeded_run(ops)
    store = JobStore(ops)
    store.cancel(run.id)
    first = store.retry(run.id)
    store.cancel(first)
    with ThreadPoolExecutor(max_workers=4) as pool:
        children = list(pool.map(lambda parent: JobStore(ops).retry(parent), [run.id, first] * 4))
    assert len(set(children)) == 1
    assert children[0] not in {run.id, first}
    with ops() as session:
        assert session.get(DurableJob, children[0]).budget_run_id == run.id


def test_retry_keeps_original_network_restriction_and_budget(ops, monkeypatch):
    monkeypatch.setenv("LV_RUN_BUDGET_USD", "1")
    run = seeded_run(ops)
    store = JobStore(ops)
    store.cancel(run.id)
    monkeypatch.setattr(get_settings(), "allow_network", True)
    monkeypatch.setenv("LV_RUN_BUDGET_USD", "100")
    child_id = store.retry(run.id)
    with ops() as session:
        execution = session.get(DurableJob, child_id).snapshot["execution"]
        assert execution["settings"]["allow_network"] is False
        assert execution["budget"]["run_limit"] == "1"


def test_retry_api_executes_real_docx_and_saves_new_result(ops, ops_client, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from apps.api.routers import jobs
    from helpers import make_docx
    from packages.common.storage import get_storage, sha256_bytes

    run = seeded_run(ops, enqueue=False)
    original = make_docx(tmp_path / "retry.docx", "<w:p><w:r><w:t>재분석 원본 자료입니다.</w:t></w:r></w:p>").read_bytes()
    key = get_storage().put_original(run.project_id + "/retry.docx", original)
    with ops() as session:
        document = session.get(Document, run.document_ids[0])
        document.storage_key, document.filename = key, "retry.docx"
        document.sha256 = sha256_bytes(original)
        document.mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        snapshot = copy.deepcopy(run.input_snapshot)
        snapshot["documents"][0].update(filename=document.filename, sha256=document.sha256)
        run.input_snapshot = snapshot
        session.flush()
        run, _ = enqueue_run(session, run)
        session.commit()
    store = JobStore(ops)
    store.cancel(run.id)
    monkeypatch.setattr(get_settings(), "rule_version", "retry-docx-new-rules")
    monkeypatch.setattr(jobs, "get_runner", lambda: SimpleNamespace(submit=lambda child: execute_run(child, store=store)))
    client, _ = ops_client
    response = client.post(f"/api/verification-runs/{run.id}/retry")
    assert response.status_code == 202, response.text
    child_id = response.json()["id"]
    assert child_id != run.id
    status = store.status(child_id)
    assert status["state"] in {"COMPLETED", "PARTIAL_COMPLETED"}, status
    result = client.get(f"/api/verification-runs/{child_id}/result")
    assert result.status_code == 200
    document = result.json()["documents"][0]
    assert document["filename"] == "retry.docx"
    assert document["sha256"] == sha256_bytes(original)
    assert any("재분석 원본 자료입니다." in block["text"]
               for page in document["pages"] for block in page["blocks"])
    assert result.json()["input_snapshot"]["execution"]["settings"]["rule_version"] == "retry-docx-new-rules"
    assert store.status(run.id)["state"] == "CANCELLED"
