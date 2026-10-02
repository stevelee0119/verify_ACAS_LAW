"""사용자 참고자료(Drive) 일치 판정 가드(평가 에이전트 소관, 보호 경로). 인계 티켓 TK-29.

4차 구현(S3, 0123213)은 법령 목록에 없는 규범을 사용자 참고자료에서 찾으면 CRITICAL '존재하지 않는 법령'을 내지 않고 `PARTIALLY_VERIFIED`로 올린다.
독립 감사(Astra 4차)가 "참고자료 목록의 파일명 일부 일치만으로 NOT_FOUND→PARTIALLY_VERIFIED가 된다"고 보고했고, 평가 측이 4차 코드에서 재현했다.
`_find_matching_user_reference`는 (a) `inventory`(목록에 보인 모든 파일, 읽기 실패·미처리 포함)의 이름까지 보고 (b) 양방향 부분 문자열로 비교하며 (c) 인용 규범이 법령 형태여도 적용한다.

설계 원칙(불확실성 단조): 본문을 읽은 참고자료(`summary["sources"]`)의 제목이 **내부 규범 형태 인용**과 일치할 때만 참고자료 대조로 넘긴다.
읽지 못한 파일, 법령 형태 인용(법·시행령·시행규칙…)은 파일명이 겹쳐도 CRITICAL 부존재 판정을 유지한다(해설서·판례집 제목에 가공 법령명이 들어 있어도 그 법령이 존재하는 것이 아니다).

참고자료 라이브러리는 실제 `summary` 구조의 대역으로 만든다(Drive 접속 없음). 미해결은 strict xfail이다.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.common.enums import FindingType, Severity, VerificationStatus  # noqa: E402
from packages.common.schemas import Citation, CitationType  # noqa: E402
from packages.legal_engine.source_review import _law_absent  # noqa: E402
from packages.legal_engine.verifier import CitationVerdict  # noqa: E402

# TK-29는 5차(c6a9dc0, U1)에서 해결됐다(평가 측 독립 재현 2026-10-02, 독립 감사 Astra 5차 18/18과 일치). 이제 일반 회귀 시험이다.


class _Library:
    def __init__(self, inventory, sources):
        self.summary = {"sources": sources, "inventory": inventory}
        self.eligible = {}


class _Verifier:
    def __init__(self, inventory, sources):
        self.references = _Library(inventory, sources)


def _run(law_name: str, *, inventory, sources):
    citation = Citation(citation_id="c", document_id="d", block_id="b", page=1, span=(0, 10), raw_text=law_name,
                        type=CitationType.STATUTE, law_name=law_name, article="1")
    verdict = CitationVerdict(citation, VerificationStatus.UNVERIFIED)
    verdict.source_records = []
    _law_absent(verdict, types.SimpleNamespace(message="EXACT_LAW_NOT_FOUND:[]"), verifier=_Verifier(inventory, sources))
    return verdict


def _entry(name, status="SELECTED_PENDING", reason="NOT_PROCESSED"):
    return {"file_id": "x", "name": name, "status": status, "reason": reason}


INTERNAL = "육군 야외 기동훈련 안전통제 및 사고조사 규정"
FAKE_STATUTE = "국가배상 특례법"


def test_internal_norm_with_read_reference_of_same_title_goes_to_reference_comparison():
    """대조군: 본문을 읽은 참고자료와 제목이 일치하는 내부 규정은 CRITICAL을 내지 않는다(요청 14 설계 그대로)."""
    title = f"[RAG참고자료] {INTERNAL}"
    verdict = _run(INTERNAL, inventory=[_entry(title, "READ", "OK")], sources=[{"name": title}])
    assert not any(f.severity == Severity.CRITICAL for f in verdict.findings)


def test_unread_file_with_same_title_does_not_raise_verification_status():
    """읽기 실패(HTTP 403)·미처리 파일은 제목이 같아도 확인으로 보지 않는다."""
    verdict = _run(INTERNAL, inventory=[_entry(f"[RAG참고자료] {INTERNAL}", "UNAVAILABLE", "DRIVE_HTTP_403")], sources=[])
    assert verdict.status != VerificationStatus.PARTIALLY_VERIFIED
    assert verdict.levels.get("existence") != "FOUND_IN_USER_REFERENCES"


def test_fabricated_statute_name_inside_a_commentary_title_keeps_critical():
    """가공 법률명이 해설서 제목에 들어 있어도 그 법률이 존재하는 것이 아니다(법령 형태 인용은 참고자료로 면책하지 않는다)."""
    title = f"{FAKE_STATUTE} 비판 해설.pdf"
    verdict = _run(FAKE_STATUTE, inventory=[_entry(title, "READ", "OK")], sources=[{"name": title}])
    assert any(f.type == FindingType.STATUTE_NONEXISTENT and f.severity == Severity.CRITICAL for f in verdict.findings)


def test_short_statute_name_contained_in_a_reference_title_keeps_critical():
    title = "행정법 표준판례.pdf"
    verdict = _run("행정법", inventory=[_entry(title, "READ", "OK")], sources=[{"name": title}])
    assert any(f.type == FindingType.STATUTE_NONEXISTENT and f.severity == Severity.CRITICAL for f in verdict.findings)


def test_statute_form_without_any_reference_keeps_critical():
    """대조군: 참고자료가 없으면 법령 형태의 미등록 법령은 CRITICAL을 유지한다."""
    verdict = _run(FAKE_STATUTE, inventory=[_entry("행정법 표준판례.pdf")], sources=[])
    assert any(f.type == FindingType.STATUTE_NONEXISTENT and f.severity == Severity.CRITICAL for f in verdict.findings)


def test_internal_norm_form_without_reference_is_below_high():
    """대조군(4차 S3 동작): 참고자료가 없는 내부 규정 형태는 HIGH 미만으로 알린다. 가공 규정이 이 경로로 약해지는 정책은 사용자 결정(TK-23 B 인접)."""
    verdict = _run("국가배상 중상해 특례 규정", inventory=[], sources=[])
    assert verdict.findings and all(f.severity in (Severity.LOW, Severity.INFO) for f in verdict.findings)
