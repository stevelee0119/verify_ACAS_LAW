"""v4 P0: 실행 매니페스트(run_manifest)와 구현 감사 하네스.

'0건'이 '실행했는데 없음'인지 '실행하지 않음'인지 결과만 보고 구분할 수 있어야 한다.
합성 문서(민사 서면·진단서·소장, 인젝션 PDF, 스캔 PDF)를 실제 파이프라인에 넣어 확인한다.
"""
from __future__ import annotations

import pytest

from packages.verification_engine.manifest import RunManifest


@pytest.fixture(scope="module")
def audit_run(tmp_path_factory):
    from scripts.audit.runner import run_synthetic
    return run_synthetic(tmp_path_factory.mktemp("audit"))


def test_manifest_records_every_engine_with_counts_and_reasons(audit_run):
    manifest = audit_run["result"].run_manifest
    engines = manifest["engines"]
    for name in ("parsing", "ocr", "adversarial_scan", "citation_verification", "citation_format_check",
                 "claim_review", "evidence_consistency", "fact_store", "cross_document_events"):
        assert name in engines, name
        record = engines[name]
        assert {"executed", "runs", "inputs", "findings", "seconds", "skip_reasons", "errors"} <= set(record)
    assert engines["fact_store"]["executed"] and engines["fact_store"]["findings"] >= 3
    assert engines["citation_format_check"]["findings"] >= 3
    # 스캔 PDF 한 건에서만 OCR이 실행되고, 텍스트 문서는 사유와 함께 건너뛴 것으로 남는다.
    assert engines["ocr"]["runs"] == 1 and engines["ocr"]["skip_reasons"]
    # AI 공급자가 없는 실행에서는 의미 검토가 '실행하지 않음'과 그 사유로 남는다(0건과 구분).
    assert not engines["semantic_review"]["executed"] and "semantic_review" in manifest["not_executed"]
    assert engines["semantic_review"]["skip_reasons"]


def test_manifest_is_in_the_verification_json(audit_run):
    payload = audit_run["payload"]
    assert payload["run_manifest"]["engines"]["fact_store"]["findings"] >= 3


def test_cross_document_issues_axis_counts_fact_store(audit_run):
    axis = audit_run["result"].scores["axes"]["internal_consistency"]
    assert axis["cross_document_issues"] >= 3


def test_stage_records_skip_error_and_finding_delta():
    manifest, findings = RunManifest(), []
    with manifest.stage("a", findings, inputs=2, document_id="d1"):
        findings.extend([1, 2])
    manifest.skip("b", "입력 없음", document_id="d1")
    with pytest.raises(ValueError):
        with manifest.stage("c", findings, document_id="d2"):
            raise ValueError("x")
    data = manifest.to_dict()
    assert data["engines"]["a"]["findings"] == 2 and data["engines"]["a"]["inputs"] == 2
    assert data["engines"]["b"]["executed"] is False and data["engines"]["b"]["skip_reasons"] == ["입력 없음"]
    assert data["engines"]["c"]["errors"] == ["d2: ValueError"]
    assert data["not_executed"] == ["b"]
