"""v4 검토 5항: 모델의 사실 모순 지적을 결정론 판정과 값(날짜·금액·조문)으로 잇는다.

AI 공급자를 켠 실행(docs/run_manifest_with_models.json, 2026-09-25)에서 모델 지적 12건 중 9건이 '재계산으로 확인하지
못함'으로 남았다. 결정론 엔진은 같은 모순을 이미 판정했다(한글·숫자 금액 불일치, 달력에 없는 선고일, 만료일 계산,
조문 수치). 원인은 두 가지였다.
- 지적 종류별 규칙 접두어 표(CONFIRMING_RULES)에 AMOUNT.·FMT.·EXPIRY 등이 없었다.
- 종류를 알 수 없는 지적(OTHER)은 대조하지 않았다.
문장·금액·법령은 시험용 합성이다.
"""
from __future__ import annotations

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Block, Finding, NormalizedDocument, Page
from packages.verification_engine.ai_document_detector import (_fact_category, _fact_remark_finding,
                                                               reconcile_model_fact_remarks, value_anchors)


def _doc():
    page = Page(page_number=1, blocks=[Block(block_id="b0", text="본문", page=1)])
    return NormalizedDocument(document_id="d", filename="d.pdf", mime_type="application/pdf", sha256="0", pages=[page])


def remark(text):
    return _fact_remark_finding(_doc(), text, _fact_category(text) or "OTHER")


def decided(rule, title, status=VerificationStatus.CONTRADICTED):
    return Finding.create(type=FindingType.ARITHMETIC_MISMATCH, status=status, severity=Severity.HIGH,
                          evidence_grade=EvidenceGrade.A, title=title, detail="",
                          confidence_features={"rule_id": rule}, document_id="d")


def run(findings):
    stats = {}
    return reconcile_model_fact_remarks(findings, stats), stats


def left(out):
    return [f for f in out if f.type == FindingType.MODEL_FACT_REMARK]


def test_anchors_are_dates_won_amounts_and_articles():
    got = value_anchors("가상형사법 제5조, 2021. 4. 31. 선고, 금 21,000,000원, 사건 2020두12345")
    assert got == {"L:가상형사법:5", "D:2021-4-31", "A:21000000"}


def test_administrative_impossible_date_remark_is_folded_into_the_format_verdict():
    fmt = decided("FMT.DATE_NOT_ON_CALENDAR", "날짜 불가능(INVALID_FORMAT): 대법원 2021. 4. 31. 선고 2020두12345 판결")
    out, stats = run([fmt, remark("[m] 원용 판례의 선고일 '2021. 4. 31.'은 4월에 31일이 없어 존재할 수 없는 날짜임. "
                                  "오기 또는 허위 인용 가능성이 있음")])
    assert not left(out) and fmt.confidence_features["model_remarks"] and stats["confirmed"] == 1


def test_family_amount_remark_spanning_two_verdicts_is_confirmed_by_both():
    words = decided("AMOUNT.WORDS_MISMATCH", "한글 금액과 숫자 금액이 다르다: '삼억일천만'=310,000,000원 / 숫자 301,000,000원")
    listed = decided("EVI.LIST_AMOUNT_MISMATCH", "증거목록 금액과 첨부 원문의 금액이 다르다: 갑 제3호증 — 목록 4,500,000원, 원문 금 5,400,000원")
    out, _ = run([words, listed, remark("[m] 청구취지 '삼억일천만원'과 '301,000,000원', 입증방법 '4,500,000원'과 확인서 '5,400,000원'이 다름")])
    assert not left(out) and words.confidence_features["model_remarks"] and listed.confidence_features["model_remarks"]


def test_civil_expiry_remark_is_confirmed_by_the_expiry_recalculation():
    expiry = decided("CALC.EXPIRY_DATE", "기간 만료일이 계산과 다르다: 문서 2027. 8. 1. / 계산 2027. 2. 1. — 2024. 2. 1.부터 3년")
    out, _ = run([expiry, remark("[m] 2024. 2. 1.부터 3년 경과 시점을 2027. 8. 1.로 계산하였으나 다른 곳에서는 2027. 2. 1.로 기재")])
    assert not left(out) and expiry.confidence_features["model_remarks"]


def test_criminal_article_remark_is_confirmed_by_the_statute_comparison():
    law = decided("legal_engine:LAW_CITATION_ERROR", "조문 본문과 수치가 다르다: 가상절도법 제3조 (문서 8년 / 조문 6년)")
    out, _ = run([law, remark("[m] 가상절도법 제3조의 법정형을 한 곳에서는 6년, 다른 곳에서는 8년 이하로 적어 서로 다름")])
    assert not left(out) and law.confidence_features["model_remarks"]


def test_unverified_part_stays_for_human_review_with_the_confirmed_rule():
    words = decided("AMOUNT.WORDS_MISMATCH", "한글 금액과 숫자 금액이 다르다: '일억'=100,000,000원 / 숫자 110,000,000원")
    out, stats = run([words, remark("[m] 청구 금액이 한글로는 일억원, 숫자로는 110,000,000원으로 서로 다릅니다. "
                                    "원고 성명도 김○○과 최○○으로 혼재되어 있습니다.")])
    [kept] = left(out)
    assert kept.confidence_features["reconciled"] == "PARTIAL" and kept.confidence_features["confirmed_by"] == ["AMOUNT.WORDS_MISMATCH"]
    assert "성명" in kept.confidence_features["unconfirmed_sentences"][0] and "재계산으로 확인하지 못했" in kept.detail
    assert words.confidence_features["model_remarks"] and stats == {"confirmed": 0, "partial": 1, "unconfirmed": 0}


def test_value_not_found_in_any_verdict_is_not_confirmed():
    fmt = decided("FMT.DATE_NOT_ON_CALENDAR", "날짜 불가능(INVALID_FORMAT): 대법원 2019. 2. 30. 선고 2018도1 판결")
    other = remark("[m] 계약서의 2022. 7. 1.과 영수증의 2022. 7. 3.이 서로 다름")
    out, stats = run([fmt, other])
    assert left(out) == [other] and other.confidence_features["reconciled"] == "UNCONFIRMED"
    assert not fmt.confidence_features.get("model_remarks") and stats["unconfirmed"] == 1


def test_only_contradicted_verdicts_of_the_same_document_confirm_a_remark():
    unverified = decided("FMT.DATE_NOT_ON_CALENDAR", "날짜: 2021. 4. 31.", status=VerificationStatus.UNVERIFIED)
    elsewhere = decided("FMT.DATE_NOT_ON_CALENDAR", "날짜 불가능: 2021. 4. 31.")
    elsewhere.document_id = "other"
    out, _ = run([unverified, elsewhere, remark("[m] 선고일 2021. 4. 31.은 달력에 없어 서로 모순")])
    assert len(left(out)) == 1


def test_stance_remark_without_values_stays_for_human_review():
    out, stats = run([remark("[m] 피고인을 위한 서면임에도 '원심의 형은 과중하지 않다'는 등 제출 주체의 입장과 상반되는 서술이 혼재")])
    assert len(left(out)) == 1 and stats["unconfirmed"] == 1
