"""ACASia_LAW 0.9.11 행정규칙 추출·검증(B5) 및 지시 조항 표기(B6) 단위 테스트.

검증 항목:
1. B5: 행정규칙 이름 인용부호(작은따옴표 '...') 추출 및 공식 조회 결과 반영
   - '국방 생성형 AI 안전성 검증 및 하자담보지침' 작은따옴표 규칙명 추출 확인
   - 규칙명이 없더라도 기관/번호 기반 행정규칙 검색 및 NOT_FOUND finding 정상 생성 확인
2. B6: "동 조항" 등 지시 조항 인용 시 compared_label 반영
   - 조문 미발견 finding 제목에 대상 법령 및 조항 식별자가 병기되는지 확인
"""
from __future__ import annotations

from types import SimpleNamespace
import pytest

from packages.common.enums import AdapterStatus, CitationType, FindingType, VerificationStatus
from packages.common.schemas import Citation
from packages.source_adapters.base import AdapterResponse
from packages.legal_engine.citation_extractor import extract_from_text
from packages.legal_engine.source_review import _article_absent, compared_label, verify_admin_rule_source
from packages.legal_engine.verifier import CitationVerdict, LegalVerifier


def test_admin_rule_single_quote_extraction():
    """작은따옴표로 둘러싸인 행정규칙명이 정상적으로 추출되어야 한다 (B5)."""
    text = (
        "또한 방위사업청 고시 제2025-18호 '국방 생성형 AI 안전성 검증 및 하자담보지침' "
        "제14조(소프트웨어 하자담보 책임의 특례) 제3항에 의하면 하자가 치유된 것으로 간주한다."
    )
    citations = extract_from_text(text)
    admin_citations = [c for c in citations if c.type == CitationType.ADMIN_RULE]
    assert len(admin_citations) >= 1
    c = admin_citations[0]
    assert c.law_name == "국방 생성형 AI 안전성 검증 및 하자담보지침"
    assert c.attributes.get("rule_number") == "2025-18"
    assert c.attributes.get("issuing_agency") == "방위사업청"
    assert c.article == "14"
    assert c.paragraph == "3"


def test_admin_rule_not_found_produces_finding():
    """공식 행정규칙 목록에서 찾지 못한 경우 NOT_FOUND finding이 생성되어야 한다 (B5)."""
    citation = Citation.create(
        CitationType.ADMIN_RULE,
        "방위사업청 고시 제2025-18호 '국방 생성형 AI 안전성 검증 및 하자담보지침'",
        document_id="doc_test",
        law_name="국방 생성형 AI 안전성 검증 및 하자담보지침",
        article="14",
        attributes={"rule_name": "국방 생성형 AI 안전성 검증 및 하자담보지침", "issuing_agency": "방위사업청", "rule_number": "2025-18"}
    )

    class FakeLawAdapter:
        def search_admin_rule(self, name):
            # 검색 결과 0건 (가상 고시이므로 공식 목록에 없음)
            return AdapterResponse(AdapterStatus.READY, [], complete=True)

        def fetch_admin_rule(self, record):
            return AdapterResponse(AdapterStatus.ERROR, [], complete=False)

    verifier = LegalVerifier(SimpleNamespace(law=FakeLawAdapter()))
    verdict = verify_admin_rule_source(verifier, citation)
    assert verdict.status == VerificationStatus.NOT_FOUND
    assert verdict.levels.get("existence") == "NOT_FOUND"
    assert len(verdict.findings) >= 1
    assert verdict.findings[0].type == FindingType.LAW_CITATION_ERROR
    assert "조회 범위 내에서 찾지 못한 행정규칙 인용" in verdict.findings[0].title


def test_referring_provision_compared_label_in_article_absent():
    """'동 조항' 같은 지시 조항의 조문 미발견 finding 제목에 풀린 조항명이 표시되어야 한다 (B6)."""
    citation = Citation.create(
        CitationType.STATUTE,
        "동 조항",
        document_id="doc_test",
        law_name="인공지능 발전과 신뢰 기반 조성 등에 관한 기본법",
        article="47",
        paragraph="2",
        attributes={"resolved_label": "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 제47조 제2항"}
    )
    verdict = CitationVerdict(citation, VerificationStatus.UNVERIFIED)
    official = {"law_name": "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법", "version_id": "282791", "effective_from": "2026-07-21"}
    provision = {"searched_articles": 46}
    _article_absent(verdict, official, provision, as_of="2026-07-21")

    assert verdict.status == VerificationStatus.NOT_FOUND
    assert len(verdict.findings) >= 1
    finding = verdict.findings[0]
    # 제목에 '동 조항'만 덜렁 나오지 않고 푼 법령 및 조문명이 명확히 포함되어야 함
    assert "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 제47조 제2항('동 조항')" in finding.title
    assert "제47조" in finding.detail
