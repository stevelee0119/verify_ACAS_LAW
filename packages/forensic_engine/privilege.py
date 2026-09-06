"""제7-A.6장 특권·윤리 게이트.

상대방 문서의 잔류 메타메시지는 상대방 소송준비자료나 의뢰인 비밀일 수 있다.
시스템은 법적·윤리적 결론을 내리지 않고 절차적 보호장치만 제공한다.

참고자료(제7-A.10장):
- ABA Formal Opinion 06-442 (2006. 8. 5.) https://www.americanbar.org/products/ecd/chapter/220004/
- NYSBA Opinion 749 / NYCLA 정리 https://www.nycla.org/?p=422
국내에는 이에 직접 대응하는 명시적 유권해석이 확인되지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    AuditEventType,
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    MetaMessageType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding

PRIVILEGE_TAG = "PRIVILEGE_CANDIDATE"

WARNING_TEXT = (
    "본 항목은 상대방의 소송준비자료 또는 의뢰인 비밀에 해당할 수 있다. "
    "관할별로 상대방 문서 메타데이터의 검토·사용에 관한 입장이 갈리며"
    "(ABA Formal Opinion 06-442는 일반적 금지가 아니라고 보는 반면 NYSBA Opinion 749는 mining을 금지한다), "
    "국내에는 이에 직접 대응하는 명시적 유권해석이 확인되지 않는다. "
    "본 시스템은 법적·윤리적 결론을 내리지 않으며, 열람 여부는 사용자가 결정한다. "
    "열람 행위는 감사추적(Audit Hash Chain)에 기록된다."
)


@dataclass
class RevealDecision:
    allowed: bool
    reason: str
    audit_event: Optional[AuditEventType] = None


class PrivilegeGate:
    """봉인·경고·열람기록·기관정책 차단을 담당한다."""

    def __init__(self, *, org_block_reveal: bool = False, allow_reveal: bool = True) -> None:
        self.org_block_reveal = org_block_reveal
        self.allow_reveal = allow_reveal

    def apply(self, findings: List[Finding], *, counterparty_document: bool = True) -> List[Finding]:
        """특권 후보 Finding에 태그·경고를 부여하고 원문을 봉인 상태로 유지한다."""
        extra: List[Finding] = []
        flagged = 0
        for finding in findings:
            if PRIVILEGE_TAG not in finding.tags:
                continue
            if not counterparty_document:
                continue
            flagged += 1
            if "PRIVILEGE_EXPOSURE_RISK" not in finding.tags:
                finding.tags.append("PRIVILEGE_EXPOSURE_RISK")
            for evidence in finding.evidence:
                evidence.sealed = True
            finding.detail = f"{finding.detail} [열람 전 경고] {WARNING_TEXT}"
        if flagged:
            features = {"deterministic_rule": True, "forensic_signal": flagged}
            extra.append(
                Finding.create(
                    type=FindingType.PRIVILEGE_EXPOSURE_RISK,
                    status=VerificationStatus.UNVERIFIED,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.A,
                    title=f"특권·비밀 노출 위험 항목 {flagged}건이 봉인되었다",
                    detail=WARNING_TEXT,
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=findings[0].document_id if findings else None,
                    engine="forensic_engine.privilege",
                    meta_message_type=MetaMessageType.MM2_RESIDUAL,
                    forensic_level=ForensicLevel.NOTABLE,
                    tags=["MM-2", "PRIVILEGE_EXPOSURE_RISK"],
                    evidence=[
                        Evidence.create(
                            description="봉인 항목 수",
                            grade=EvidenceGrade.A,
                            excerpt=f"{flagged}건",
                        )
                    ],
                )
            )
        return extra

    def request_reveal(self, finding: Finding, *, user_confirmed: bool) -> RevealDecision:
        """사용자가 명시적으로 열람을 선택한 경우에만 원문을 공개한다."""
        if self.org_block_reveal:
            return RevealDecision(False, "기관 정책으로 봉인 원문 열람이 차단되어 있다.")
        if not self.allow_reveal:
            return RevealDecision(False, "시스템 설정으로 봉인 원문 열람이 비활성화되어 있다.")
        if not user_confirmed:
            return RevealDecision(False, "열람 전 경고에 대한 사용자 확인이 없다.")
        if finding.sealed_excerpt is None and not any(e.sealed for e in finding.evidence):
            return RevealDecision(False, "봉인된 원문이 없다.")
        return RevealDecision(True, "사용자 확인으로 열람을 허용한다.", AuditEventType.SEALED_CONTENT_REVEALED)
