"""v3 D1: 변형 인용문을 어절 단위로 원문과 나란히 제시한다(MODIFIED_QUOTE).

재현: 테스트셋 v1 TC-06(판례 인용문에서 '현저하게' 한 어절 삭제). 합성: 다른 판시 문장·다른 변형 유형.
"""
from __future__ import annotations

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Finding
from packages.legal_engine.quote_diff import quote_changes, render_quote_diff
from packages.verification_engine.finalize import consolidate_citation_findings

OFFICIAL = ("징계권자가 재량권의 행사로서 한 징계처분이 사회통념상 현저하게 타당성을 잃어 징계권자에게 맡겨진 "
            "재량권을 남용한 것이라고 인정되는 경우에 한하여 그 처분을 위법하다고 할 수 있다")


def _op(result, op):
    return [o for o in result["ops"] if o["op"] == op]


def test_reproduction_deleted_degree_adverb_is_shown_side_by_side():
    quote = ("징계권자가 재량권의 행사로서 한 징계처분이 사회통념상 타당성을 잃어 징계권자에게 맡겨진 "
             "재량권을 남용한 것이라고 인정되는 경우")
    result = quote_changes(quote, OFFICIAL)
    assert result and result["meaningful"]
    [deleted] = _op(result, "delete")
    assert deleted["original"] == "현저하게" and deleted["quoted"] == ""
    assert {c["kind"] for c in result["changes"]} == {"DEGREE"}
    shown = render_quote_diff(result)
    assert "현저하게" in shown and "삭제" in shown and "사회통념상" in shown


def test_synthetic_inserted_negation_in_other_holding():
    official = ("행정청이 처분을 하면서 상대방에게 의견제출의 기회를 주었다면 그 처분은 절차상 하자가 있다고 볼 "
                "수 없으므로 이를 이유로 처분을 취소할 것은 아니다")
    quote = ("행정청이 처분을 하면서 상대방에게 의견제출의 기회를 주지 않았다면 그 처분은 절차상 하자가 있다고 볼 "
             "수 없으므로")
    result = quote_changes(quote, official)
    assert result and result["meaningful"] and "NEGATION" in {c["kind"] for c in result["changes"]}
    [replaced] = _op(result, "replace")
    assert replaced["original"] == "주었다면" and "않았다면" in replaced["quoted"]


def test_synthetic_modality_replaced_may_to_must():
    official = ("법원은 당사자의 주장과 증거조사의 결과를 참작하여 자유로운 심증으로 손해배상의 액수를 정할 수 있다고 "
                "보아야 한다는 것이 확립된 법리이다")
    quote = ("법원은 당사자의 주장과 증거조사의 결과를 참작하여 자유로운 심증으로 손해배상의 액수를 정하여야 한다고 "
             "보아야 한다는 것이 확립된 법리이다")
    result = quote_changes(quote, official)
    assert result and result["meaningful"] and "MODALITY" in {c["kind"] for c in result["changes"]}


def test_synthetic_provision_qualifier_deleted():
    official = ("같은 법 제20조 제2항 단서의 정당한 사유가 있는 때에는 처분등이 있은 날부터 1년이 지난 뒤에도 "
                "취소소송을 제기할 수 있다고 해석함이 타당하다")
    quote = ("같은 법 제20조 제2항의 정당한 사유가 있는 때에는 처분등이 있은 날부터 1년이 지난 뒤에도 "
             "취소소송을 제기할 수 있다고 해석함이 타당하다")
    result = quote_changes(quote, official)
    assert result and result["meaningful"] and "PROVISION_QUALIFIER" in {c["kind"] for c in result["changes"]}


def test_synthetic_non_meaningful_word_change_is_reported_but_not_meaningful():
    official = ("피고가 원고에 대한 조사 과정에서 확보한 자료만으로는 원고가 이 사건 징계사유에 해당하는 비위를 "
                "저질렀다고 단정하기 어렵다")
    quote = ("피고가 원고에 대한 감사 과정에서 확보한 자료만으로는 원고가 이 사건 징계사유에 해당하는 비위를 "
             "저질렀다고 단정하기 어렵다")
    result = quote_changes(quote, official)
    assert result and not result["meaningful"]
    [replaced] = _op(result, "replace")
    assert (replaced["original"], replaced["quoted"]) == ("조사", "감사")


def test_spacing_and_punctuation_only_differences_are_not_changes():
    spaced = ("징계권자가 재량권의 행사로서 한 징계 처분이 사회통념상 현저하게 타당성을 잃어, 징계권자에게 맡겨진 "
              "재량권을 남용한 것이라고 인정되는 경우")
    assert quote_changes(spaced, OFFICIAL) is None
    assert quote_changes("사회통념상 현저하게 타당성을 잃어 징계권자에게 맡겨진 재량권을 남용한 것", OFFICIAL) is None


def test_marked_omission_reports_only_meaningful_changes():
    elided = ("징계권자가 재량권의 행사로서 한 징계처분이 사회통념상 현저하게 타당성을 잃어 … 재량권을 남용한 것이라고 "
              "인정되는 경우에 한하여 그 처분을 위법하다고 할 수 있다")
    assert quote_changes(elided, OFFICIAL) is None


def _finding(title, label, **extra):
    return Finding.create(type=FindingType.CASE_QUOTE_MISMATCH, status=VerificationStatus.CONTRADICTED,
                          severity=Severity.HIGH, evidence_grade=EvidenceGrade.A, title=title, detail="d",
                          confidence_features={"citation_id": "c1", "verdict_label": label, **extra})


def test_consolidated_verdict_keeps_every_defect_of_the_citation_visible():
    meta = _finding("판례 메타데이터 불일치: 대법원 2007. 12. 21. 선고 2006두16274 판결", "METADATA_MISMATCH",
                    defect_summary="선고일 불일치(문서 2007. 12. 21. / 공식 2006. 12. 21.)")
    quote = _finding("직접 인용문 변형", "MODIFIED_QUOTE", defect_summary="인용문 변형: 원문 '현저하게' 삭제")
    [final] = consolidate_citation_findings([meta, quote])
    assert "선고일 불일치" in final.title and "현저하게" in final.title
    assert final.confidence_features["defects"] == ["선고일 불일치(문서 2007. 12. 21. / 공식 2006. 12. 21.)",
                                                    "인용문 변형: 원문 '현저하게' 삭제"]


def test_ai_cross_review_request_carries_the_quote_diff(monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace

    from packages.legal_engine import argument_validity_verifier as avv

    seen = {}

    class Router:
        async def consult_all(self, role, request, **kwargs):
            seen["user"], seen["system"] = request.user, request.system
            return []

    citation = SimpleNamespace(page=1, raw_text="대법원 2006. 12. 21. 선고 2006두16274 판결", context="주장 문맥")
    item = {"citation": citation, "context": "주장 문맥", "basis": "CONTENT_MISMATCH",
            "quote_diff": "삭제(정도 부사) — 원문 「사회통념상 [현저하게] 타당성을」 → 인용 「사회통념상 타당성을」"}
    result = avv.ArgumentValidityResult()
    asyncio.run(avv._attach_ai_opinions(result, [item], Router(), None, None))
    payload = json.loads(seen["user"])["items"][0]
    assert "현저하게" in json.dumps(payload, ensure_ascii=False)
    assert "원문의 표현을 기준으로" in seen["system"]
