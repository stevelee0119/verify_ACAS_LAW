"""Public synthetic speaker/predicate contrasts and the actual TXT consumer."""
from __future__ import annotations

import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.legal_rules import review_legal_rules

RULE = "GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS"
LIMIT = " 이 사건 채무에 관한 책임을 질 수 없다."
LIMIT_CONNECTIVE = LIMIT[:-2] + "고 "


def _warnings(text):
    doc = NormalizedDocument("synthetic-scope", "scope.txt", "text/plain", "synthetic",
                             pages=[Page(1, blocks=[Block("heading", "청구원인", 1), Block("body", text, 1)])])
    return [finding for finding in review_legal_rules(doc) if RULE in finding.tags]


CONCESSIONS = ["가사 약정이 성립하였더라도, ", "설령 계약이 체결되었더라도, ", "만약 대여가 유효하더라도, "]
DENIALS = ["변제공탁을 하지 않았으나", "전액을 지급하지 않았으나", "상계의 의사표시를 하지 않았으나"]
FULFILLED = ["변제공탁을 하였으므로", "전액을 지급하였으므로", "상계의 의사표시가 도달하였으므로"]


@pytest.mark.parametrize("lead,requirement", list(zip(CONCESSIONS, DENIALS)))
def test_grammatical_concession_with_denied_requirement_keeps_warning(lead, requirement):
    assert _warnings(lead + requirement + LIMIT)


@pytest.mark.parametrize("lead,requirement", list(zip(CONCESSIONS, FULFILLED)))
def test_opposite_fulfilled_requirement_keeps_limited_defense(lead, requirement):
    assert not _warnings(lead + requirement + LIMIT)


@pytest.mark.parametrize("tail", ["다른 당사자의 책임이 없다.", "관련 처분은 당연히 무효이다.", "징계책임도 전면 면책된다."])
def test_a_second_authored_categorical_effect_has_its_own_scope(tail):
    text = CONCESSIONS[0] + FULFILLED[0] + LIMIT_CONNECTIVE + tail
    assert _warnings(text)


@pytest.mark.parametrize("tail", ["형사책임은 별도 절차에서 심리된다.", "징계사유는 별도 절차에서 판단된다."])
def test_another_liability_mention_without_exemption_is_not_extension(tail):
    text = "설령 계약이 인정되더라도, " + FULFILLED[0] + LIMIT_CONNECTIVE + tail
    assert not _warnings(text)


@pytest.mark.parametrize("quoted,positive", [
    ("“변제공탁을 하지 않았다”", "변제공탁을 하였으므로"),
    ("‘상계의 의사표시를 하지 않았다’", "상계의 의사표시가 도달하였으므로"),
    ('"전액을 지급하지 않았다"', "전액을 지급하였으므로"),
    ("'변제공탁을 하지 않았다'", "변제공탁을 하였으므로"),
])
def test_a_quoted_requirement_is_not_the_writers_denial(quoted, positive):
    text = "설령 계약이 인정되더라도, 원고는 " + quoted + "고 주장하였으나 피고는 " + positive + LIMIT
    assert not _warnings(text)


@pytest.mark.parametrize("quoted,denial", [
    ("“변제공탁을 하였다”", DENIALS[0]),
    ("‘상계의 의사표시가 도달하였다’", DENIALS[2]),
])
def test_quoted_fulfilment_cannot_exempt_an_authored_denial(quoted, denial):
    text = "설령 계약이 인정되더라도, 원고는 " + quoted + "고 주장하였으나 피고는 " + denial + LIMIT
    assert _warnings(text)


@pytest.mark.parametrize("denial", DENIALS[:2])
def test_opponent_overclaim_being_rejected_is_not_authored(denial):
    text = "상대방은 설령 계약이 인정되더라도, " + denial + LIMIT[:-1] + "고 주장하나, 그 주장은 이유 없다."
    assert not _warnings(text)


@pytest.mark.parametrize("denial", DENIALS[:2])
def test_rebuttal_does_not_hide_a_separate_authored_overclaim(denial):
    text = ("상대방은 설령 계약이 인정되더라도, 변제공탁을 하지 않았으나" + LIMIT[:-1]
            + "고 주장하나; " + CONCESSIONS[1] + denial + LIMIT)
    assert _warnings(text)


@pytest.mark.parametrize("fulfilled", FULFILLED[:2])
def test_rebuttal_with_own_fulfilled_requirement_is_not_overclaim(fulfilled):
    text = ("상대방은 설령 계약이 인정되더라도, 변제공탁을 하지 않았으나" + LIMIT[:-1]
            + "고 주장하나; " + CONCESSIONS[1] + fulfilled + LIMIT)
    assert not _warnings(text)


@pytest.mark.parametrize("reference", ["변제공탁 관련 서류는 확인되지 않았으나", "상계의 의사표시 관련 기록은 확보되지 않았으나"])
def test_a_different_predicates_argument_keeps_uncertainty(reference):
    findings = _warnings("설령 계약이 인정되더라도, " + reference + LIMIT)
    assert findings
    assert all("요건 확인 요청" in finding.confidence_features["verdict"] for finding in findings)
    observations = [row for finding in findings for row in finding.confidence_features["defense_scope"]["requirements"]]
    assert observations and all(row["state"] == "UNCERTAIN" for row in observations)


@pytest.mark.parametrize("reference", ["변제공탁을 근거로", "상계의 의사표시를 근거로", "전액을 지급한다는 계획을 근거로"])
def test_reference_without_an_asserted_requirement_predicate_is_uncertain(reference):
    findings = _warnings("설령 계약이 인정되더라도, " + reference + LIMIT)
    assert findings
    assert all("요건 확인 요청" in finding.confidence_features["verdict"] for finding in findings)


@pytest.mark.parametrize("requirement", ["변제공탁을 하지 않은 적이 없으며", "상계의 의사표시를 하지 않았다는 자료가 없으며"])
def test_nested_scope_is_an_explicit_verification_request(requirement):
    findings = _warnings("설령 계약이 인정되더라도, " + requirement + LIMIT)
    assert findings
    assert all("요건 확인 요청" in finding.confidence_features["verdict"] for finding in findings)


@pytest.mark.parametrize("opener", ["“", "‘", "「"])
def test_an_unclosed_quote_keeps_an_explicit_uncertain_warning(opener):
    findings = _warnings(opener + CONCESSIONS[0] + DENIALS[0] + LIMIT)
    assert findings
    assert all("요건 확인 요청" in finding.confidence_features["verdict"] for finding in findings)
    assert all(finding.confidence_features["defense_scope"]["uncertain_quotation"] for finding in findings)


@pytest.mark.parametrize("lead,requirement,expected", [
    (CONCESSIONS[0], DENIALS[0], True),
    (CONCESSIONS[1], DENIALS[1], True),
    (CONCESSIONS[2], DENIALS[2], True),
    (CONCESSIONS[0], FULFILLED[0], False),
    (CONCESSIONS[1], FULFILLED[1], False),
    (CONCESSIONS[2], FULFILLED[2], False),
])
def test_actual_txt_pipeline_preserves_authored_requirement_decision(tmp_path, lead, requirement, expected):
    findings = _pipeline_warnings(tmp_path, lead + requirement + LIMIT)
    assert bool(findings) is expected


def _pipeline_warnings(tmp_path, text):
    from packages.audit_engine import AuditChain
    from packages.common.storage import sha256_file
    from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline

    path = tmp_path / "scope.txt"
    path.write_text("청구원인\n" + text, encoding="utf-8")
    item = DocumentInput("synthetic-scope", str(path), path.name, "text/plain", sha256_file(path))
    result = VerificationPipeline(audit=AuditChain()).run("scope-" + tmp_path.name, ProjectContext("synthetic-scope"), [item])
    assert not result.errors
    return [finding for finding in result.documents[0].findings if RULE in finding.tags]


REPORTED = "상대방은 설령 계약이 인정되더라도, " + DENIALS[0] + LIMIT[:-1] + "고 주장하나"


@pytest.mark.parametrize("text,expected,uncertain", [
    ("설령 계약이 인정되더라도, 원고는 “변제공탁을 하지 않았다”고 주장하였으나 피고는 " + FULFILLED[0] + LIMIT, False, False),
    ("설령 계약이 인정되더라도, 원고는 ‘변제공탁을 하였다’고 주장하였으나 피고는 " + DENIALS[0] + LIMIT, True, False),
    (REPORTED + ", 그 주장은 이유 없다.", False, False),
    ("상대방은 설령 계약이 인정되더라도, " + DENIALS[1] + LIMIT[:-1] + "고 주장하나, 그 항변은 이유 없다.", False, False),
    (REPORTED + "; " + CONCESSIONS[1] + DENIALS[1] + LIMIT, True, False),
    (REPORTED + "; " + CONCESSIONS[1] + FULFILLED[1] + LIMIT, False, False),
    ("“" + CONCESSIONS[0] + DENIALS[0] + LIMIT, True, True),
    ("「" + CONCESSIONS[0] + DENIALS[0] + LIMIT, True, True),
])
def test_actual_txt_pipeline_preserves_speaker_and_uncertainty(tmp_path, text, expected, uncertain):
    findings = _pipeline_warnings(tmp_path, text)
    assert bool(findings) is expected
    if uncertain:
        assert all("요건 확인 요청" in finding.confidence_features["verdict"] for finding in findings)
        assert all(finding.confidence_features["defense_scope"]["uncertain"] for finding in findings)
