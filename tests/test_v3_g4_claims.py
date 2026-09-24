"""추가지시 G4: 법리 주장 검토를 '주장 유형 분류 → 근거 조회 → 판단'으로 재설계.

합성 시험셋(tests/fixtures/g4_claims.json: 무리한 주장 30·타당한 주장 30)과 보류 시험셋
(g4_claims_holdout.json)에서 정밀도·재현율을 잰다. 헌재 결정 이력과 조문 원문은 가상 법률명에 붙인 합성 자료다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.common.enums import FindingType
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.claim_review import classify_claims, law_name, review_claims
from packages.legal_engine.legal_rules import review_legal_rules
from packages.source_adapters.law_go_kr import decision_result

FIXTURES = Path(__file__).parent / "fixtures"
MAIN = json.loads((FIXTURES / "g4_claims.json").read_text(encoding="utf-8"))
HOLDOUT = json.loads((FIXTURES / "g4_claims_holdout.json").read_text(encoding="utf-8"))


def _doc(text, doc_id="d"):
    blocks = [Block(block_id=f"b{i}", text=t, page=1) for i, t in enumerate(text.split("\n"))]
    return NormalizedDocument(document_id=doc_id, filename=f"{doc_id}.pdf", mime_type="application/pdf", sha256="0",
                              pages=[Page(page_number=1, blocks=blocks)])


def _lookup(law, article):
    return MAIN["history"].get(f"{law} 제{article}조", {"status": "READY", "decisions": []})


def _review(text, doc_id="d", lookup=_lookup):
    doc = _doc(text, doc_id)
    rules = review_legal_rules(doc)
    return rules + review_claims(doc, lookup=lookup, provisions=MAIN["provisions"],
                                 skip_sentences=[f.confidence_features.get("claim", "") for f in rules])


def _scores(claims):
    tp = fp = fn = 0
    for claim in claims:
        flagged = bool(_review(claim["text"], claim["id"]))
        gold = claim["label"] == "UNREASONABLE"
        tp += flagged and gold
        fp += flagged and not gold
        fn += gold and not flagged
    return tp / max(1, tp + fp), tp / max(1, tp + fn)


def test_main_synthetic_set_precision_and_recall_at_least_0_8():
    assert len(MAIN["claims"]) == 60
    assert sum(c["label"] == "UNREASONABLE" for c in MAIN["claims"]) == 30
    precision, recall = _scores(MAIN["claims"])
    assert precision >= 0.8 and recall >= 0.8, (precision, recall)


def test_holdout_set_precision_and_recall_at_least_0_8():
    precision, recall = _scores(HOLDOUT["claims"])
    assert precision >= 0.8 and recall >= 0.8, (precision, recall)


@pytest.mark.parametrize("claim", [c for c in MAIN["claims"] if c["label"] == "UNREASONABLE"
                                   and c["type"] != "REQUIREMENT_MISMATCH"], ids=lambda c: c["id"])
def test_unreasonable_claims_are_classified_by_type(claim):
    """무리한 주장은 기대한 유형으로 분류된다(분야: 행정·민사·국가배상·형사·노동)."""
    types = {m.claim_type for m in classify_claims(claim["text"], _lookup)}
    rules = review_legal_rules(_doc(claim["text"]))
    assert claim["type"] in types or rules, (claim["id"], types)


@pytest.mark.parametrize("claim", [c for c in MAIN["claims"] if c["type"] == "REQUIREMENT_MISMATCH"
                                   and c["label"] == "UNREASONABLE"], ids=lambda c: c["id"])
def test_requirement_mismatch_names_the_compared_article(claim):
    findings = review_claims(_doc(claim["text"]), provisions=MAIN["provisions"])
    [finding] = findings
    assert finding.confidence_features["claim_type"] == "REQUIREMENT_MISMATCH"
    assert "비교 대상 조문" in finding.detail and finding.confidence_features["compared"] in finding.detail


def test_generalization_is_a_dedicated_finding_type():
    [finding] = _review("계약서에 서명하지 않은 약정은 언제나 무효이다.")
    assert finding.type == FindingType.UNSUPPORTED_GENERALIZATION
    assert finding.confidence_features["rule_id"] == "CLAIM.UNSUPPORTED_GENERALIZATION"


# --- 위헌 주장: 형식상 불가·결정 이력 대조 ---------------------------------------------
def test_constitution_itself_is_not_reviewable_regardless_of_lookup():
    [finding] = _review("헌법 제29조 제2항은 명백히 위헌이다.", lookup=None)
    assert str(finding.status) == "CONTRADICTED" and "헌법재판소법 제41조" in finding.detail


def test_upheld_provision_claimed_obviously_unconstitutional_cites_the_decision():
    [finding] = _review("가상공공배상법 제2조는 명백히 위헌이므로 적용할 수 없다.")
    assert str(finding.status) == "CONTRADICTED" and "합성-1" in finding.detail and "합헌" in finding.detail


def test_dismissal_only_history_is_human_review():
    lookup = lambda law, art: {"status": "READY", "decisions": [
        {"case_number": "합성-9", "decision_date": "2020. 1. 1.", "result": "각하"}]}
    [finding] = _review("가상세무특례법 제3조는 분명히 위헌이다.", lookup=lookup)
    assert str(finding.status) == "SUSPICIOUS" and str(finding.evidence_grade) == "C" and "각하" in finding.detail


def test_unavailable_history_is_unverified_not_a_defect():
    lookup = lambda law, art: {"status": "MISSING_KEY", "message": "OC 없음"}
    [finding] = _review("가상세무특례법 제3조는 분명히 위헌이다.", lookup=lookup)
    assert str(finding.status) == "UNVERIFIED" and "확인하지 못했다" in finding.detail


def test_later_unconstitutional_decision_means_no_finding():
    assert _review("가상집회제한법 제10조는 명백히 위헌이다.") == []


# --- 부속 요소 ------------------------------------------------------------------------
@pytest.mark.parametrize("raw,name", [
    ("피고 회사는 가상공공배상법", "가상공공배상법"), ("근거인 가상병역보상법", "가상병역보상법"),
    ("공공기관의 정보공개에 관한 법률", "공공기관의 정보공개에 관한 법률"), ("제조물 책임법", "제조물 책임법"),
    ("국가유공자 등 예우 및 지원에 관한 법률", "국가유공자 등 예우 및 지원에 관한 법률")])
def test_law_name_trims_leading_words_only(raw, name):
    assert law_name(raw) == name


@pytest.mark.parametrize("order,result", [
    ("심판대상조항은 헌법에 위반되지 아니한다.", "합헌"),
    ("심판대상조항은 헌법에 합치되지 아니한다. 위 조항은 개정될 때까지 계속 적용된다.", "헌법불합치"),
    ("심판대상조항은 헌법에 위반된다.", "위헌"),
    ("이 사건 심판청구를 각하한다.", "각하"),
    ("…에 적용하는 한 헌법에 위반된다.", "한정위헌"),
    ("판단 결과 없음", None)])
def test_decision_result_is_read_from_the_order(order, result):
    assert decision_result({"raw": {"주문": order}}) == result


def test_statutory_exception_is_not_flagged_by_the_deadline_rule():
    """무효확인소송·정당한 사유를 들어 제소기간을 말하는 문장은 v2 규칙도 판정하지 않는다."""
    for sentence in ("무효확인소송에는 취소소송의 제소기간 제한이 적용되지 않는다.",
                     "원고에게 정당한 사유가 있으므로 1년의 제소기간 제한이 적용되지 않는다."):
        doc = _doc(f"청구취지\n1. 피고의 처분을 취소한다.\n청구원인\n1. {sentence}")
        assert not [f for f in review_legal_rules(doc) if "제소기간" in f.title]
    # 예외 근거 없이 배제하면 그대로 판정한다.
    doc = _doc("청구취지\n1. 피고의 처분을 취소한다.\n청구원인\n1. 기본권 침해가 중대하므로 제소기간은 적용되지 않는다.")
    assert [f for f in review_legal_rules(doc) if "제소기간" in f.title]


def test_pipeline_runs_the_claim_review(tmp_path, monkeypatch):
    from packages.pii_engine import PseudonymStore
    from packages.verification_engine import pipeline as module
    from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline

    doc = _doc("준비서면\n1. 업계 기준에 따르면 하자보수비는 1,200만 원이 적정하다.\n"
               "2. 해고 예고를 하지 않은 해고는 모든 경우에 무효이다.", "A")
    monkeypatch.setattr(module, "parse_document", lambda path, document_id=None, **kw: doc)
    monkeypatch.setattr(module, "PseudonymStore", lambda project_id: PseudonymStore(project_id, root=tmp_path))
    result = VerificationPipeline().run("run-g4", ProjectContext("project-g4"), [DocumentInput("A", "A.txt", "A.txt")])
    rules = {(f.confidence_features or {}).get("rule_id") for d in result.documents for f in d.findings}
    assert {"CLAIM.UNSOURCED_STANDARD", "CLAIM.UNSUPPORTED_GENERALIZATION"} <= rules


@pytest.mark.parametrize("previous,flagged", [
    ("행정절차법 제21조는 사전통지를 정한다.", True),          # 무관한 앞 문장의 인용은 근거가 아니다
    ("민법 제103조는 반사회적 법률행위를 무효로 한다.", True)])
def test_unrelated_previous_citation_does_not_support_a_universal_claim(previous, flagged):
    assert bool(_review(f"{previous} 계약서 없는 약정은 언제나 무효이다.")) is flagged


def test_demonstrative_links_to_the_previous_citation():
    assert _review("민법 제103조는 반사회적 법률행위를 무효로 한다. 이런 약정은 언제나 무효이다.") == []


def test_continuation_sentence_inherits_the_previous_citation():
    assert _review("민법 제103조는 반사회적 법률행위를 무효로 한다. 따라서 이런 약정은 언제나 무효이다.") == []


@pytest.mark.parametrize("text", [
    "원고는 소청을 거치지 않았으나 헌법 제27조가 재판청구권을 보장하므로 전심절차가 필요하지 않다.",   # 행정(군인)
    "피해가 막대하므로 헌법 제10조에 비추어 이 사건 채권의 소멸시효는 적용되지 않는다.",            # 민사
    "국가가 가해자이므로 헌법 제29조에 따라 국가배상청구권의 소멸시효는 따질 필요가 없다."])      # 국가배상
def test_general_constitutional_right_is_not_an_exception_basis(text):
    [finding] = _review(text)
    assert finding.confidence_features["claim_type"] == "LITIGATION_REQUIREMENT_EXCLUSION"
