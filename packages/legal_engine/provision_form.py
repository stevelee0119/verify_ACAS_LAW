"""법령 조문 표기 형식 검사(가지번호·0번 조문).

공식 원문을 조회하지 않고도 알 수 있는 표기 형식 오류만 본다(statute_ranges.provision_form_violations).
- 성립 불가(IMPOSSIBLE): 제0조·제0항·제0호, 가지번호 '의0' → CONTRADICTED(A)
- 형식 이상 후보(SUSPECT): 항·목의 가지번호, 가지번호 '의1' → SUSPICIOUS(B), 원문 확인 필요
같은 표기·같은 형식 문제는 한 번만 싣는다.
"""
from __future__ import annotations

from typing import List

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text

from .statute_ranges import provision_form_violations

ENGINE_NAME = "legal_engine.provision_form"
BASIS = "법제처 「법령 입안·심사 기준」(가지번호는 조·호에만 사용)"


def provision_form_findings(doc: NormalizedDocument) -> List[Finding]:
    text = build_reading_text(doc).text
    out: List[Finding] = []
    seen = set()
    for violation in provision_form_violations(text):
        key = (violation["raw"], violation["code"])
        if key in seen:
            continue
        seen.add(key)
        impossible = violation["certainty"] == "IMPOSSIBLE"
        grade = EvidenceGrade.A if impossible else EvidenceGrade.B
        features = {"deterministic_rule": True, "rule_id": violation["rule_id"], "defect_code": "LAW_PROVISION_FORM",
                    "form_code": violation["code"], "certainty": violation["certainty"], "basis": BASIS,
                    "human_review": not impossible}
        out.append(Finding.create(
            type=FindingType.LAW_CITATION_ERROR,
            status=VerificationStatus.CONTRADICTED if impossible else VerificationStatus.SUSPICIOUS,
            severity=Severity.HIGH if impossible else Severity.MEDIUM, evidence_grade=grade,
            title=(f"조문 표기 형식 오류: {violation['raw']}" if impossible
                   else f"조문 표기 형식 이상 후보: {violation['raw']}"),
            detail=(f"{violation['reason']}. " + ("이런 번호의 조문은 성립할 수 없다." if impossible else
                    f"근거: {BASIS}. 오기이거나 존재하지 않는 조문일 수 있으므로 공식 원문으로 확인해야 한다.")),
            confidence=0.95 if impossible else 0.6, confidence_features=features, document_id=doc.document_id,
            engine=ENGINE_NAME, tags=["LAW", "PROVISION_FORM"],
            evidence=[Evidence.create(description="조문 표기", grade=grade, document_id=doc.document_id,
                                      excerpt=violation["raw"][:200])]))
    return out
