"""End-to-end progress and degradation with synthetic documents and source outages."""
from dataclasses import replace

import httpx
import pytest

from apps.api.job_control import JobOwnershipLost
from packages.common.enums import ExternalAIPolicy, FindingType, JobState
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.source_adapters import SourceRegistry, transport
from packages.source_adapters.local_mirror import LocalLegalMirror
from packages.verification_engine import pipeline as module


def synthetic_document(identifier, text):
    return NormalizedDocument(identifier, identifier + ".txt", "text/plain", "synthetic",
                              pages=[Page(1, blocks=[Block("b-" + identifier, text, 1)])])


def test_many_citations_and_three_documents_finish_during_source_outage(monkeypatch, tmp_path):
    registry = SourceRegistry()
    registry.law.mirror = LocalLegalMirror(tmp_path / "empty-mirror")
    registry.law.settings = replace(registry.law.settings, allow_network=True, law_go_kr_oc="test-only")
    requests = []
    async def fail(url, **kwargs):
        requests.append(url)
        raise httpx.ReadTimeout("synthetic outage")
    monkeypatch.setattr(transport, "_fetch", fail)
    monkeypatch.setattr(transport, "_wait", lambda session, seconds: session.check_active())
    text = "\n".join(f"대법원 2024. 1. 1. 선고 2023다{10000 + index} 판결" for index in range(46))
    documents = {"one": synthetic_document("one", text),
                 "two": synthetic_document("two", "민법 제390조"),
                 "three": synthetic_document("three", "계약서 본문입니다.")}
    monkeypatch.setattr(module, "parse_document", lambda *args, document_id, **kwargs: documents[document_id])
    events = []
    result = module.VerificationPipeline(registry=registry).run(
        "outage-run", module.ProjectContext("outage-project", external_ai_policy=ExternalAIPolicy.LOCAL_ONLY),
        [module.DocumentInput(identifier, "synthetic.txt", doc.filename) for identifier, doc in documents.items()],
        progress=lambda *event: events.append(event))
    assert result.state == JobState.PARTIAL_COMPLETED and not result.errors
    # 판례 문서: 두 번의 제한된 묶음 + 보류 후 회복 확인 1회 = 9.
    # 두 번째 문서의 "민법 제390조" 조회 3회(문서마다 조회 한도를 따로 둔다). 두 글자 법령명(민법·형법·헌법)이
    # 예전 정규식에서 추출되지 않아 이 조회가 빠져 있었다.
    assert len(requests) == 12
    assert len(result.documents) == 3
    assert len(result.documents[0].citations) == 46
    assert all(verdict["status"] == "UNVERIFIED" for verdict in result.documents[0].engine_data["legal_verdicts"])
    assert result.documents[0].ai_hallucination_table == []
    assert not any("가공의 판례" in reason for reason in result.documents[0].ai_detector_result["reasons"])
    progress = [event[2] for event in events]
    assert all(b >= a - 1e-12 for a, b in zip(progress, progress[1:])) and progress[-1] == 1
    for expected in ("인용 항목 추출", "법률 인용 확인 46/46건", "주장·사건·금액 분석", "작성 이력 분석", "AI 작성 정황 분석", "문서 분석 완료"):
        assert any(expected in message for _, message, _ in events)
    assert any("외부 출처 재조회" in message for _, message, _ in events)
    assert any("지연된 인용 다시 확인" in message for _, message, _ in events)
    assert result.documents[0].engine_data["source_lookup"]["recovery_used"]


def test_cancel_between_citations_escapes_document_failure_handler(monkeypatch):
    doc = synthetic_document("one", "대법원 2024. 1. 1. 선고 2023다10000 판결")
    monkeypatch.setattr(module, "parse_document", lambda *args, **kwargs: doc)
    events = []
    def progress(state, message, ratio):
        events.append(message)
        if "법률 인용 확인 0/" in message:
            raise JobOwnershipLost("cancelled")
    with pytest.raises(JobOwnershipLost):
        module.VerificationPipeline().run("cancel-run", module.ProjectContext("cancel-project"),
                                         [module.DocumentInput("one", "synthetic.txt", "one.txt")], progress=progress)
    assert not any("문서 분석 완료" in event for event in events)
    assert transport._session.get() is None


def test_unreadable_hwp_is_partial_not_clean(tmp_path):
    path = tmp_path / "unreadable.hwp"
    path.write_bytes(b"not an HWP document")
    result = module.VerificationPipeline().run(
        "unreadable-run", module.ProjectContext("unreadable-project"),
        [module.DocumentInput("unreadable", str(path), path.name)])
    assert result.state == JobState.PARTIAL_COMPLETED
    assert any(item["kind"] == "document_body" for item in result.unverified_items)
    assert any(f.type == FindingType.PARSE_ERROR and str(f.status) == "UNVERIFIED" for f in result.all_findings)
