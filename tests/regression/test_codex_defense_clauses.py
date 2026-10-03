"""TK-45: requirement negation stays in its own clause.

Synthetic examples exercise grammar changes, affirmative controls and the real
TXT consumer. They do not change the evaluator's fixtures or expected results.
"""
from __future__ import annotations

import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.legal_rules import review_legal_rules

RULE_ID = "GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS"
LEAD = "설령 차용 사실이 인정되더라도, 민법상 변제를 근거로 "
CONCLUSION = " 이 사건 채무에 관한 책임을 질 수 없다."

DENIED = [
    "변제공탁 절차를 밟지 아니하였고",
    "상계의 의사표시가 도달한 증거가 없었으나",
    "전액을 지급하였다는 사실이 입증되지 못하였지만",
    "변제기가 도래하였다고 인정되지 않음에도",
    "변제공탁이 이루어진 바 없는데도",
    "전액을 지급한 바는 없으며",
    "상계 의사표시를 아예 하지 않았으나",
    "전액을 지급할 수 없었으나",
]
AFFIRMED = [
    "변제공탁을 바로 하였으므로",
    "변제기가 도래하여 상대방에게 전액을 지급하였으므로",
    "수령거절 직후 머뭇거리지 않고 변제공탁을 하였으므로",
    "상계의 의사표시가 도달하였고 상대방이 이견을 제기하지 않았으므로",
    "시효 기간이 경과하였으므로",
    "전혀 망설이지 않고 변제공탁을 하였으므로",
]


def _warnings(text: str):
    document = NormalizedDocument(
        document_id="defense-clauses",
        filename="synthetic.txt",
        mime_type="text/plain",
        sha256="0" * 64,
        pages=[Page(page_number=1, blocks=[
            Block(block_id="heading", text="청구원인", page=1),
            Block(block_id="argument", text=text, page=1),
        ])],
    )
    return [finding for finding in review_legal_rules(document)
            if RULE_ID in finding.tags]


@pytest.mark.parametrize("requirement", DENIED)
def test_requirement_negation_is_not_limited_to_a_short_phrase(requirement):
    assert _warnings(LEAD + requirement + CONCLUSION)


@pytest.mark.parametrize("requirement", AFFIRMED)
def test_other_predicates_and_conclusion_negation_do_not_deny_requirements(requirement):
    assert not _warnings(LEAD + requirement + CONCLUSION)


@pytest.mark.parametrize("requirement", [DENIED[0], DENIED[1]])
def test_reported_court_statement_is_not_attributed_to_the_writer(requirement):
    text = ("앞서 선고된 판결에서 법원은 " + LEAD + requirement
            + CONCLUSION[:-1] + "고 판시하였다.")
    assert not _warnings(text)


@pytest.mark.parametrize("requirement", [DENIED[2], DENIED[4]])
def test_opponent_claim_being_rejected_is_not_the_writers_defense(requirement):
    text = ("피고는 " + LEAD + requirement + CONCLUSION[:-1]
            + "고 주장하나, 그 주장은 이유 없다.")
    assert not _warnings(text)


@pytest.mark.parametrize("requirement", [DENIED[3], DENIED[5]])
def test_counterargument_does_not_become_a_defense_overclaim(requirement):
    text = (LEAD + requirement + CONCLUSION[:-1]
            + "는 피고의 항변은 이유 없으며, 요건을 충족하였다는 자료도 없다.")
    assert not _warnings(text)


@pytest.mark.parametrize("tail", [
    "형사상 책임도 성립할 수 없다.",
    "징계책임도 전면 면책된다.",
])
def test_fulfilled_civil_requirement_does_not_exempt_an_extended_conclusion(tail):
    assert _warnings(LEAD + AFFIRMED[0] + CONCLUSION[:-1] + "고 " + tail)


@pytest.mark.parametrize("requirement", [DENIED[0], DENIED[4], AFFIRMED[2]])
def test_txt_pipeline_consumes_the_same_requirement_decision(tmp_path, requirement):
    from packages.audit_engine import AuditChain
    from packages.common.storage import sha256_file
    from packages.verification_engine import (
        DocumentInput, ProjectContext, VerificationPipeline,
    )

    path = tmp_path / "defense.txt"
    path.write_text("청구원인\n" + LEAD + requirement + CONCLUSION, encoding="utf-8")
    item = DocumentInput(
        document_id="txt-defense", path=str(path), filename=path.name,
        mime_type="text/plain", sha256=sha256_file(path),
    )
    result = VerificationPipeline(audit=AuditChain()).run(
        "defense-" + tmp_path.name, ProjectContext(project_id="clause-tests"), [item]
    ).documents[0]
    findings = [finding for finding in result.findings if RULE_ID in finding.tags]
    assert bool(findings) is (requirement in DENIED)


ABSENCE_REQUIREMENTS = [
    ("상계 금지사유", "상계의 의사표시가 도달하였으므로"),
    ("시효 중단 사유", "시효 기간이 경과하였으므로"),
    ("제3자의 권리", "채권과 채무가 동일인에게 귀속되었으므로"),
]


@pytest.mark.parametrize("requirement, positive", ABSENCE_REQUIREMENTS)
def test_absence_of_a_disqualifying_fact_is_not_a_denied_requirement(requirement, positive):
    assert not _warnings(LEAD + requirement + "가 없고 " + positive + CONCLUSION)


@pytest.mark.parametrize("requirement, positive", ABSENCE_REQUIREMENTS)
def test_presence_of_a_disqualifying_fact_keeps_the_warning(requirement, positive):
    assert _warnings(LEAD + requirement + "가 있으나 " + positive + CONCLUSION)


@pytest.mark.parametrize("requirement, positive", ABSENCE_REQUIREMENTS)
def test_a_bare_disqualifying_fact_keeps_uncertainty_despite_another_positive(requirement, positive):
    findings = _warnings(LEAD + requirement + ", " + positive + CONCLUSION)
    assert findings
    assert all("요건 확인 요청" in f.confidence_features["verdict"] for f in findings)


def test_nested_negation_does_not_silently_inherit_another_requirements_exemption():
    findings = _warnings(
        LEAD + "변제공탁을 하지 않은 적이 없으며 상계의 의사표시가 도달하였으므로" + CONCLUSION
    )
    assert findings
    assert all("요건 확인 요청" in f.confidence_features["verdict"] for f in findings)


@pytest.mark.parametrize("requirement", DENIED + AFFIRMED)
def test_synthetic_requirement_cases_reach_the_defense_rule(requirement):
    from packages.legal_engine.legal_rules import get_defense_overclaim_pattern

    assert get_defense_overclaim_pattern().search(LEAD + requirement + CONCLUSION)


@pytest.mark.parametrize("ending", ["마쳤고", "끝냈고", "해뒀고", "마치자", "끝내자", "해두자",
                                       "마쳤더니", "끝냈더니", "해뒀더니", "마친 뒤", "끝낸 후", "해둔 다음"])
def test_a_later_objects_negation_is_separate_from_a_completed_requirement(ending):
    text = LEAD + f"변제공탁을 {ending} 서류 사본은 받지 못하였으므로" + CONCLUSION
    assert not _warnings(text)


@pytest.mark.parametrize("modifier", ["전무한", "허용되지 않은", "불가능한"])
def test_a_direct_negative_modifier_requests_review_instead_of_exemption(modifier):
    findings = _warnings(LEAD + modifier + " 변제공탁을 근거로" + CONCLUSION)
    assert findings
    assert all("요건 확인 요청" in f.confidence_features["verdict"] for f in findings)


@pytest.mark.parametrize("requirement", [
    "변제공탁이 없지는 않으므로",
    "변제공탁이 없다고는 하지 않았으므로",
])
def test_overlapping_negating_phrases_are_kept_uncertain(requirement):
    findings = _warnings(LEAD + requirement + CONCLUSION)
    assert findings
    assert all("요건 확인 요청" in f.confidence_features["verdict"] for f in findings)


@pytest.mark.parametrize("requirement", [
    "수령거절에 따라 머뭇거리지 않고 변제공탁을 하였으므로",
    "상계의 의사표시가 도달한 뒤 망설이지 않고 전액을 지급하였으므로",
])
def test_adverbial_requirement_context_does_not_absorb_a_later_negation(requirement):
    assert not _warnings(LEAD + requirement + CONCLUSION)
