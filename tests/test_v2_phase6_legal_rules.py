"""v2 Phase 6: 공식 원문 근거가 붙은 법리 규칙. 규칙마다 claim·rule_id·verdict·basis·confidence를 낸다."""
from __future__ import annotations

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.legal_rules import load_rules, review_legal_rules


def doc(*lines):
    page = Page(page_number=1)
    for index, text in enumerate(lines):
        page.blocks.append(Block(block_id=f"b{index}", text=text, page=1))
    return NormalizedDocument(document_id="D", filename="d.pdf", mime_type="application/pdf", sha256="0", pages=[page])


COMPLAINT = ["소 장", "원 고 김○○", "피 고 1. 제○○여단장", "2. 징계위원 한○○", "청 구 취 지",
             "1. 피고가 원고에게 한 감봉처분은 무효임을 확인한다.", "2. 피고 징계위원 한○○을 형사처벌한다.",
             "3. 피고는 원고를 원소속으로 복귀시켜라.", "청 구 원 인",
             "원고는 소청을 거치지 않았으나 군인에게는 전심절차가 적용되지 않습니다.",
             "재량권 일탈은 언제나 중대하고 명백한 하자입니다.",
             "징계위원은 경과실만 있어도 원고에게 손해를 배상할 책임이 있습니다."]


def rule_ids(findings):
    return {f.confidence_features["rule_id"] for f in findings}


def test_rules_carry_official_basis_with_url():
    table = load_rules()
    for rule in table["rules"]:
        for name in rule["basis"]:
            source = table["sources"][name]
            assert source["url"].startswith("https://www.law.go.kr/") and source["text"]


def test_complaint_defects_are_reported_with_claim_rule_verdict_basis_confidence():
    findings = review_legal_rules(doc(*COMPLAINT))
    assert {"ADMIN.RELIEF_CRIMINAL_PUNISHMENT", "ADMIN.RELIEF_PERFORMANCE_ORDER", "ADMIN.DEFENDANT_INDIVIDUAL",
            "MIL.PRE_TRIAL_REVIEW_REQUIRED", "ADMIN.NULLITY_ALWAYS", "TORT.OFFICIAL_LIGHT_NEGLIGENCE",
            "ADMIN.NULLITY_ONLY"} <= rule_ids(findings)
    for finding in findings:
        features = finding.confidence_features
        assert features["claim"] and features["verdict"] and 0 < features["confidence"] <= 1
        assert features["basis"] or features["rule_id"].startswith("GEN.")


def test_a_proper_complaint_triggers_no_rule():
    proper = ["소 장", "원 고 김○○", "피 고 제○○여단장", "청 구 취 지",
              "1. 피고가 원고에게 한 감봉처분을 취소한다.", "청 구 원 인",
              "원고는 군인사법 제51조의2에 따라 항고심사위원회의 결정을 거쳐 이 사건 소를 제기합니다.",
              "하자가 중대하고 명백한지는 사안마다 목적론적으로 판단하여야 합니다."]
    assert review_legal_rules(doc(*proper)) == []


def test_relief_rules_apply_only_to_administrative_suits():
    civil = ["소 장", "청 구 취 지", "1. 피고는 원고에게 1,000만 원을 지급하라.", "청 구 원 인", "대여금 청구입니다."]
    assert review_legal_rules(doc(*civil)) == []
