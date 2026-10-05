"""F2 통합 검토 항목(ReviewItem) 및 단일 판정 단위 시험.

- T1 단일 판정: 1인용 1행, 순수 파생 심각도, item_id 고유성
- T2 손실 없음: 모든 검토 대상 Finding이 검토 행에 도달
- T4 AI 탭 배타성: AI·보안 Finding은 검토 행에 일체 미포함
- 근거 사다리 2축 분리: official_status / reference_status 독립성
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.finding_category_map import ScreenTab, get_finding_tab
from packages.common.schemas import (
    Finding,
    OfficialConfirmationStatus,
    ReferenceSupportStatus,
    ReviewItem,
    ReviewItemKind,
)
from packages.verification_engine.review_items import (
    build_document_review_items,
    derive_item_severity,
)


@dataclass
class DummyDocResult:
    """단위 시험용 Mock DocumentResult."""
    document_id: str = "doc_test_1"
    findings: List[Finding] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    ai_hallucination_table: List[Dict[str, Any]] = field(default_factory=list)
    engine_data: Dict[str, Any] = field(default_factory=dict)


def _make_finding(
    fid: str,
    ftype: FindingType,
    sev: Severity,
    citation_id: Optional[str] = None,
) -> Finding:
    features = {}
    if citation_id:
        features["citation_id"] = citation_id
    f = Finding.create(
        type=ftype,
        status=VerificationStatus.CONTRADICTED,
        severity=sev,
        evidence_grade=EvidenceGrade.A,
        title=f"테스트 지적 {fid}",
        detail=f"상세 내용 {fid}",
        confidence=0.9,
        confidence_features=features,
        document_id="doc_test_1",
    )
    f.finding_id = fid
    return f




def test_derive_item_severity_logic():
    """심각도 순수 파생 규칙 단위 시험 (T1)."""
    # 1. Finding 없을 때 INFO
    assert derive_item_severity([]) == Severity.INFO

    # 2. 단일 Finding
    f_low = _make_finding("f1", FindingType.CASE_NOT_FOUND, Severity.LOW)
    assert derive_item_severity([f_low]) == Severity.LOW

    # 3. 복수 Finding 혼합 시 최고 순위 파생
    f_high = _make_finding("f2", FindingType.CASE_HOLDING_DISTORTION, Severity.HIGH)
    f_med = _make_finding("f3", FindingType.CASE_CITATION_ERROR, Severity.MEDIUM)
    assert derive_item_severity([f_low, f_med, f_high]) == Severity.HIGH

    f_crit = _make_finding("f4", FindingType.FACT_CONTRADICTION, Severity.CRITICAL)
    assert derive_item_severity([f_low, f_med, f_high, f_crit]) == Severity.CRITICAL


def test_build_review_items_single_verdict_and_no_loss():
    """인용 1행 원칙(T1) 및 Finding 누락 0(T2), AI 배타성(T4) 통합 검증."""
    # 2개 인용 준비
    citations = [
        {"citation_id": "cit_1", "raw_text": "대법원 판결 A"},
        {"citation_id": "cit_2", "raw_text": "민법 제1조"},
    ]

    # Findings 준비
    # cit_1에 연결된 법률 Finding 2개
    f1 = _make_finding("f1", FindingType.CASE_NOT_FOUND, Severity.MEDIUM, citation_id="cit_1")
    f2 = _make_finding("f2", FindingType.CASE_HOLDING_DISTORTION, Severity.CRITICAL, citation_id="cit_1")

    # cit_2에는 연결 Finding 없음 (순수 인용)

    # 인용에 연결되지 않은 사실관계 및 품질 Finding 2개 (T2 대상)
    f3 = _make_finding("f3", FindingType.MODEL_FACT_REMARK, Severity.LOW)
    f4 = _make_finding("f4", FindingType.OCR_LOW_QUALITY, Severity.MEDIUM)

    # AI·보안 Finding 1개 (T4 대상: ReviewItem에 절대 들어가면 안 됨)
    f_ai = _make_finding("f_ai", FindingType.PROMPT_INJECTION_SUSPECTED, Severity.HIGH, citation_id="cit_1")

    doc = DummyDocResult(
        document_id="doc_test_1",
        findings=[f1, f2, f3, f4, f_ai],
        citations=citations,
        engine_data={
            "legal_verdicts": [
                {"citation_id": "cit_1", "status": "NOT_FOUND"},
                {"citation_id": "cit_2", "status": "CONFIRMED"},
            ]
        },
    )

    items = build_document_review_items(doc)

    # T1: 인용당 1행, 중복 없음
    cit_items = [i for i in items if i.citation_id]
    assert len(cit_items) == 2
    assert {i.citation_id for i in cit_items} == {"cit_1", "cit_2"}

    # T1: cit_1의 심각도는 f1(MEDIUM), f2(CRITICAL) 중 최고값인 CRITICAL이어야 함
    cit_1_item = next(i for i in items if i.citation_id == "cit_1")
    assert cit_1_item.severity == Severity.CRITICAL
    assert set(cit_1_item.finding_ids) == {"f1", "f2"}
    assert cit_1_item.official_status == OfficialConfirmationStatus.OFFICIAL_NOT_FOUND

    # cit_2의 심각도는 연결 Finding이 없으므로 INFO이어야 함
    cit_2_item = next(i for i in items if i.citation_id == "cit_2")
    assert cit_2_item.severity == Severity.INFO
    assert cit_2_item.finding_ids == []
    assert cit_2_item.official_status == OfficialConfirmationStatus.OFFICIAL_CONFIRMED

    # T4: f_ai(AI·보안 Finding)는 어떤 ReviewItem의 finding_ids에도 없어야 함
    all_linked_fids = {fid for i in items for fid in i.finding_ids}
    assert "f_ai" not in all_linked_fids

    # T2: 검토 대상 Finding (f1, f2, f3, f4)은 100% 매핑되어야 함
    assert {"f1", "f2", "f3", "f4"} <= all_linked_fids

    # f3(FACT), f4(PROCESSING_QUALITY)는 개별 검토 행으로 존재해야 함
    f3_item = next(i for i in items if "f3" in i.finding_ids)
    assert f3_item.kind == ReviewItemKind.FACT
    assert f3_item.severity == Severity.LOW
    assert f3_item.citation_id is None

    f4_item = next(i for i in items if "f4" in i.finding_ids)
    assert f4_item.kind == ReviewItemKind.PROCESSING_QUALITY
    assert f4_item.severity == Severity.MEDIUM
    assert f4_item.citation_id is None


def test_review_item_to_dict_structure():
    """ReviewItem.to_dict() 직렬화 명세 검증."""
    item = ReviewItem(
        item_id="doc1_CITATION_cit1",
        kind=ReviewItemKind.CITATION,
        document_id="doc1",
        claim_text="주장 문구",
        official_status=OfficialConfirmationStatus.OFFICIAL_CONFIRMED,
        reference_status=ReferenceSupportStatus.NOT_CHECKED,
        verdict_label="공식 원문 일치",
        severity=Severity.INFO,
        citation_id="cit1",
    )
    d = item.to_dict()
    assert d["item_id"] == "doc1_CITATION_cit1"
    assert d["kind"] == "CITATION"
    assert d["official_status"] == "OFFICIAL_CONFIRMED"
    assert d["reference_status"] == "NOT_CHECKED"
    assert d["severity"] == "INFO"
    assert d["citation_id"] == "cit1"


from test_api import client, project


def test_api_save_false_positive_workflow(client, project):
    """실제 API 기반 '오탐 저장 -> FALSE_POSITIVE' 워크플로우 계약 검증 (TK-60)."""
    from uuid import uuid4
    from apps.api.db import Document, FindingRow, VerificationRun, get_session_factory

    project_id = project["id"]
    prefix = uuid4().hex[:8]
    doc_id = f"doc_{prefix}"
    run_id = f"run_{prefix}"
    fid = f"fid_{prefix}"

    with get_session_factory()() as session:
        session.add(Document(id=doc_id, project_id=project_id, filename="test.pdf",
                             sha256="0" * 64, storage_key=f"test/{doc_id}", included_in_verification=True))
        session.flush()
        session.add(VerificationRun(id=run_id, project_id=project_id, state="COMPLETED",
                                    document_ids=[doc_id], verification_key=prefix,
                                    input_snapshot={"scope_revision": 0}))
        session.flush()
        session.add(FindingRow(id=fid, run_id=run_id, project_id=project_id, document_id=doc_id,
                               type="LEGAL_CITATION", status="UNVERIFIED", severity="HIGH",
                               evidence_grade="C", title="테스트 판례 지적", engine="legal", page=1,
                               review_status="NEEDS_REVIEW"))
        session.commit()

    # 1. 초기 워크플로우 조회 (revision 0, NOT_STARTED, UNDECIDED)
    wf_url = f"/api/findings/{fid}/workflow"
    init_res = client.get(wf_url)
    assert init_res.status_code == 200
    init_wf = init_res.json()
    assert init_wf["revision"] == 0
    assert init_wf["workflow_state"] == "NOT_STARTED"
    assert init_wf["decision"] == "UNDECIDED"

    # 2. 오탐 저장 (COMPLETED, FALSE_POSITIVE)
    put_res = client.put(wf_url, json={
        "workflow_state": "COMPLETED",
        "decision": "FALSE_POSITIVE",
        "priority": 1,
        "assignee": "테스트담당자",
        "note": "오탐 사유 검토 완료",
        "revision": 0,
    })
    assert put_res.status_code == 200, put_res.text
    saved = put_res.json()
    assert saved["revision"] == 1
    assert saved["workflow_state"] == "COMPLETED"
    assert saved["decision"] == "FALSE_POSITIVE"

    # 3. finding row의 review_status가 FALSE_POSITIVE로 동기화되었는지 확인
    f_res = client.get(f"/api/findings/{fid}")
    assert f_res.status_code == 200
    f_data = f_res.json()
    assert f_data["review_status"] == "FALSE_POSITIVE"
    assert f_data["review_note"] == "오탐 사유 검토 완료"


def test_api_multi_finding_row_preserves_individual_metadata(client, project):
    """메모·담당자·우선순위가 서로 다른 2건 행에서 상태를 바꾼 뒤 실제 API로 각자 값이 보존되는지 검증 (TK-60 7절)."""
    from uuid import uuid4
    from apps.api.db import Document, FindingRow, VerificationRun, get_session_factory

    project_id = project["id"]
    prefix = uuid4().hex[:8]
    doc_id = f"doc_{prefix}"
    run_id = f"run_{prefix}"
    fid_1 = f"f_{prefix}_1"
    fid_2 = f"f_{prefix}_2"

    with get_session_factory()() as session:
        session.add(Document(id=doc_id, project_id=project_id, filename="test.pdf",
                             sha256="0" * 64, storage_key=f"test/{doc_id}", included_in_verification=True))
        session.flush()
        session.add(VerificationRun(id=run_id, project_id=project_id, state="COMPLETED",
                                    document_ids=[doc_id], verification_key=prefix,
                                    input_snapshot={"scope_revision": 0}))
        session.flush()
        session.add(FindingRow(id=fid_1, run_id=run_id, project_id=project_id, document_id=doc_id,
                               type="LEGAL_CITATION", status="UNVERIFIED", severity="HIGH",
                               evidence_grade="C", title="테스트 판례 지적 1", engine="legal", page=1,
                               review_status="NEEDS_REVIEW"))
        session.add(FindingRow(id=fid_2, run_id=run_id, project_id=project_id, document_id=doc_id,
                               type="CASE_HOLDING_DISTORTION", status="UNVERIFIED", severity="CRITICAL",
                               evidence_grade="B", title="테스트 판례 지적 2", engine="legal", page=1,
                               review_status="NEEDS_REVIEW"))
        session.commit()

    # 1. 두 finding에 메모·담당자·우선순위를 서로 다르게 초기 저장
    # fid_1: priority=1 (우선 검토), assignee="변호사A", note="메모1"
    res1 = client.put(f"/api/findings/{fid_1}/workflow", json={
        "workflow_state": "NOT_STARTED",
        "decision": "UNDECIDED",
        "priority": 1,
        "assignee": "변호사A",
        "note": "메모1",
        "revision": 0,
    })
    assert res1.status_code == 200

    # fid_2: priority=3 (후순위), assignee="변호사B", note="메모2"
    res2 = client.put(f"/api/findings/{fid_2}/workflow", json={
        "workflow_state": "NOT_STARTED",
        "decision": "UNDECIDED",
        "priority": 3,
        "assignee": "변호사B",
        "note": "메모2",
        "revision": 0,
    })
    assert res2.status_code == 200

    # 2. 행 안 저장 로직 시뮬레이션:
    # 2개 finding이 연결된 행에서 검토 상태를 '지적 수용'(COMPLETED / AGREED)으로 변경
    # 각 finding마다 GET으로 현재 값과 revision을 읽고, 바꾼 칸(workflow_state, decision)만 덮어 PUT 전송
    for fid in [fid_1, fid_2]:
        cur = client.get(f"/api/findings/{fid}/workflow").json()
        payload = {
            "workflow_state": "COMPLETED",
            "decision": "AGREED",
            "priority": cur["priority"],
            "assignee": cur["assignee"],
            "note": cur["note"],
            "revision": cur["revision"],
        }
        saved = client.put(f"/api/findings/{fid}/workflow", json=payload)
        assert saved.status_code == 200

    # 3. 각 finding의 메모·담당자·우선순위가 서로 덮어써지지 않고 각자 보존되었는지 단언
    wf_1 = client.get(f"/api/findings/{fid_1}/workflow").json()
    assert wf_1["workflow_state"] == "COMPLETED"
    assert wf_1["decision"] == "AGREED"
    assert wf_1["priority"] == 1
    assert wf_1["assignee"] == "변호사A"
    assert wf_1["note"] == "메모1"
    assert wf_1["revision"] == 2

    wf_2 = client.get(f"/api/findings/{fid_2}/workflow").json()
    assert wf_2["workflow_state"] == "COMPLETED"
    assert wf_2["decision"] == "AGREED"
    assert wf_2["priority"] == 3
    assert wf_2["assignee"] == "변호사B"
    assert wf_2["note"] == "메모2"
    assert wf_2["revision"] == 2

    # finding row의 review_status도 둘 다 ACCEPTED로 정상 동기화됨 확인
    assert client.get(f"/api/findings/{fid_1}").json()["review_status"] == "ACCEPTED"
    assert client.get(f"/api/findings/{fid_2}").json()["review_status"] == "ACCEPTED"


