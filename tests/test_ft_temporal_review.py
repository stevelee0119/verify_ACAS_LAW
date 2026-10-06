"""FT(행위시법 검토 보강) 추가 대조군 시험 (메모 42_ft_design.md 5절 및 요청 16).

1. 일반 단어 오인식 방지 대조군 ('제N호 품목', '제N호 과목', '항목')
2. 분할 실패 시 안전 폴백 대조군 (비표준 서식)
3. 동일 시행일 복수 버전 전수 불일치 대조군 (NO_VERSION_MATCH 정상 판정)
4. 현행(today) 경계 동일 시행일 복수 버전 대조군 (결정론적 확인 요청 분기)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pytest

from packages.common.enums import AdapterStatus, Severity, VerificationStatus
from packages.common.schemas import Citation, CitationType
from packages.legal_engine.temporal_review import (
    extract_subitem_info,
    official_versions,
    review_temporal_application,
)
from packages.source_adapters.law_go_kr import LawGoKrAdapter
from packages.source_adapters.local_mirror import LocalLegalMirror

MIRROR = Path(__file__).resolve().parent / "fixtures" / "prepared_brief_mirror"
LAW = "부정경쟁방지 및 영업비밀보호에 관한 법률"


def _mirror() -> LocalLegalMirror:
    return LocalLegalMirror(root=MIRROR)


# --------------------------------------------------------------------------- 대조군 1
def test_contrast_1_general_words_not_recognized_as_subitem():
    """대조군 1: '제N호 품목', '제N호 과목', '항목' 등 일반 명사가 포함된 경우 목으로 오인식되지 않음."""
    # 1) '제1호 품목' 테스트
    c_item_product = Citation(
        citation_id="c1", document_id="doc1", block_id="b1", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제2조 제1호 품목", type=CitationType.STATUTE, law_name=LAW,
        article="2", attributes={"claim_text": "상품의 판매"})
    item, subitem = extract_subitem_info(c_item_product)
    assert subitem is None, f"'품목'의 '품'이 목으로 오인식됨: subitem={subitem}"

    # 2) '제1호 과목' 테스트
    c_item_course = Citation(
        citation_id="c2", document_id="doc1", block_id="b2", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제2조 제1호 과목", type=CitationType.STATUTE, law_name=LAW,
        article="2", attributes={"claim_text": "교육 과정"})
    item, subitem = extract_subitem_info(c_item_course)
    assert subitem is None, f"'과목'의 '과'가 목으로 오인식됨: subitem={subitem}"

    # 3) '확인할 항목은' 테스트
    c_item_entry = Citation(
        citation_id="c3", document_id="doc1", block_id="b3", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제2조 확인할 항목은", type=CitationType.STATUTE, law_name=LAW,
        article="2", attributes={"claim_text": "기타 요건"})
    item, subitem = extract_subitem_info(c_item_entry)
    assert subitem is None, f"'항목'의 '항'이 목으로 오인식됨: subitem={subitem}"

    # 4) 호 표기 없는 단독 '가목'
    c_item_bare = Citation(
        citation_id="c4", document_id="doc1", block_id="b4", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제2조 가목", type=CitationType.STATUTE, law_name=LAW,
        article="2", attributes={"claim_text": "기타 요건"})
    item, subitem = extract_subitem_info(c_item_bare)
    assert subitem is None, f"호 표기 없는 단독 '가목'이 특정됨: subitem={subitem}"

    # 5) '제1호 품목'으로 인용 시 조·항 판정이 유지되고 부존재 소급 오류가 발생하지 않는지 확인
    finding = review_temporal_application(
        c_item_product, _mirror().all_versions(LAW, "2"), {"date": "2020-05-12", "basis": "FACT_DATE"})
    assert finding is None or "RETROACTIVE_APPLICATION_ERROR" not in (finding.tags or [])


# --------------------------------------------------------------------------- 대조군 2
def test_contrast_2_fallback_when_subitem_split_fails():
    """대조군 2: 비표준 서식 등으로 호·목 분할에 실패한 경우 임의의 소급 오류를 내지 않고 조·항 결과 유지."""
    # 목 표기('가.', '나.')가 전혀 없는 비표준 형식의 조문 버전 2개
    non_standard_versions = [
        {"version_id": "1", "effective_from": "2020-01-01", "effective_to": "2023-12-31",
         "text": "제2조 1. 부정경쟁행위란 타인의 상품과 혼동하게 하는 행위를 말한다."},
        {"version_id": "2", "effective_from": "2024-01-01", "effective_to": None,
         "text": "제2조 1. 부정경쟁행위란 타인의 상품과 혼동하게 하거나 영업상 이익을 침해하는 행위를 말한다."},
    ]
    # 서면이 '제1호 가목'으로 인용했으나 조문 본문에 목 분할이 불가능한 경우
    citation = Citation(
        citation_id="c_fallback", document_id="doc1", block_id="b1", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제2조 제1호 가목", type=CitationType.STATUTE, law_name=LAW,
        article="2", item="1", attributes={"claim_text": "타인의 상품과 혼동하게 하는 행위"})

    finding = review_temporal_application(
        citation, non_standard_versions, {"date": "2020-05-12", "basis": "FACT_DATE"})

    # 분할 실패로 인해 신설 목 부존재 오류(RETROACTIVE_APPLICATION_ERROR)가 임의로 발생하지 않아야 함
    assert finding is None or "RETROACTIVE_APPLICATION_ERROR" not in (finding.tags or [])


# --------------------------------------------------------------------------- 대조군 3
def test_contrast_3_same_day_versions_all_disagree_flags_no_version_match():
    """대조군 3: 동일 시행일 두 버전이 모두 청구 문언과 불일치하면 확인 요청이 아닌 NO_VERSION_MATCH로 판정."""
    versions_14_2 = _mirror().all_versions(LAW, "14의2")
    three, five = versions_14_2[0]["text"], versions_14_2[-1]["text"]

    # 2024-08-21 시행일로 3배본, 5배본 두 버전이 존재
    same_day_versions = [
        {"version_id": "100", "effective_from": "2019-07-09", "effective_to": "2024-08-20", "text": three},
        {"version_id": "200", "effective_from": "2024-08-21", "effective_to": None, "text": five},
        {"version_id": "201", "effective_from": "2024-08-21", "effective_to": None, "text": three},
    ]
    # 문서가 어느 버전에도 없는 '손해액의 10배'를 주장
    citation = Citation(
        citation_id="c_ten", document_id="doc1", block_id="b1", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제14조의2 제6항", type=CitationType.STATUTE, law_name=LAW,
        article="14의2", paragraph="6", attributes={"claim_text": "손해액의 10배를 넘지 아니하는 범위"})

    finding = review_temporal_application(
        citation, same_day_versions, {"date": "2025-01-01", "basis": "FACT_DATE"})

    assert finding is not None
    # 두 버전 모두 불일치하므로 결과가 갈리지 않고 전수 불일치(CONTRADICTED)로 판정되어야 함
    assert finding.status == VerificationStatus.CONTRADICTED
    assert finding.severity == Severity.HIGH
    assert finding.confidence_features.get("rule_id") == "TEMPORAL.NO_VERSION_MATCH"


# --------------------------------------------------------------------------- 대조군 4
def test_contrast_4_same_day_versions_at_current_boundary(monkeypatch):
    """대조군 4: 기준일은 단일이나 현행(today) 경계에 동일 시행일 버전이 존재할 때 결과 갈림 시 확인 요청."""
    versions_14_2 = _mirror().all_versions(LAW, "14의2")
    three, five = versions_14_2[0]["text"], versions_14_2[-1]["text"]

    def _history_row(mst: str, effective: str, promulgated: str) -> dict:
        return {"법령명한글": LAW, "법령ID": "000308", "법령일련번호": mst, "공포일자": promulgated,
                "시행일자": effective, "공포번호": mst, "제개정구분명": "일부개정"}

    def _law_body(row: dict, text: str) -> dict:
        return {"법령": {
            "기본정보": {"법령ID": "000308", "법령일련번호": row["법령일련번호"], "법령명_한글": LAW,
                     "시행일자": row["시행일자"], "공포일자": row["공포일자"], "공포번호": row["공포번호"]},
            "조문": {"조문단위": [{"조문번호": "14", "조문가지번호": "2", "조문여부": "조문",
                               "조문시행일자": row["시행일자"], "조문내용": text}]}}}

    rows = [_history_row("100", "20190709", "20190108"),
            _history_row("200", "20240821", "20240220"),
            _history_row("201", "20240821", "20240220")]
    texts = {"100": three, "200": five, "201": three}

    adapter = LawGoKrAdapter(mirror=LocalLegalMirror(Path(tempfile.mkdtemp(prefix="ft_empty_"))))
    monkeypatch.setattr(adapter, "status", lambda: AdapterStatus.READY)
    monkeypatch.setattr(LawGoKrAdapter, "api_key", property(lambda self: "TEST_ONLY_KEY"))

    def request(url, *, params):
        if "MST" in params:
            row = next(r for r in rows if r["법령일련번호"] == params["MST"] and r["시행일자"] == params["efYd"])
            payload = _law_body(row, texts[row["법령일련번호"]])
        else:
            payload = {"LawSearch": {"totalCnt": len(rows), "page": 1, "law": rows}}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(adapter, "_http_get", request)

    # 기준일: 2020-05-12 (단일 버전 100 3배본), 현행일: 2026-01-01 (동일 시행일 200 5배본, 201 3배본)
    # 주장: 5배 배상책임
    citation = Citation(
        citation_id="c_cur_bound", document_id="doc1", block_id="b1", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제14조의2 제6항", type=CitationType.STATUTE, law_name=LAW,
        article="14의2", paragraph="6", attributes={"claim_text": "손해액의 5배를 넘지 아니하는 범위에서 징벌적 배상책임이 인정된다"})

    fetched = official_versions(adapter, citation, "2020-05-12", "2026-01-01")
    assert fetched["status"] == "READY"
    finding = review_temporal_application(citation, fetched["versions"], {"date": "2020-05-12", "basis": "FACT_DATE"})

    # 현행 경계에서 버전 간 판정이 갈리므로(200은 VERIFIED, 201은 CONTRADICTED),
    # 소급 오류 단정이 아닌 확인 요청(TEMPORAL.REVIEW_NEEDED, UNVERIFIED)으로 선행 분기되어야 함
    assert finding is not None
    assert finding.status == VerificationStatus.UNVERIFIED
    assert finding.severity != Severity.HIGH
    assert "RETROACTIVE_APPLICATION_ERROR" not in (finding.tags or [])
    assert finding.confidence_features.get("human_review") is True
    assert finding.confidence_features.get("ambiguity") == "SAME_EFFECTIVE_DATE"
