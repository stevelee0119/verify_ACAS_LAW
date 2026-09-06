"""제7-A장 은닉 메타메시지 탐지 엔진 오케스트레이터.

파이프라인 위치(제7-A.5장):
  Ingestion → 제7장 Adversarial Scan(MM-1) → MM-2/MM-3 결정론적 포렌식 스캔
  → 정규화·비식별화 → Claim·Evidence Graph → MM-4 추론 → Finding·Advisory 통합

MM-2·MM-3에서 추출된 원문 문자열은 LLM Context에 그대로 투입하지 않는다.
유형 태그와 위치정보, 길이·해시만 전달한다(제7-A.5장).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from packages.common.enums import ForensicLevel, MetaMessageType, Severity
from packages.common.schemas import EngineResult, Finding, NormalizedDocument

from .advisory import AdvisoryContext, scan_advisory
from .covert import scan_covert
from .document_forensics import analyze_image_lsb, scan_document_forensics
from .privilege import PrivilegeGate
from .redaction import scan_redaction
from .residual import scan_residual
from .template_residue import scan_template_residue

ENGINE_NAME = "forensic_engine"


@dataclass
class ForensicContext:
    project_case_number: Optional[str] = None
    project_court: Optional[str] = None
    project_parties: List[str] = field(default_factory=list)
    counterparty_document: bool = True
    org_block_reveal: bool = False
    allow_reveal: bool = True
    enabled_advisory_signals: Optional[Set[str]] = None
    advisory: Optional[AdvisoryContext] = None
    source_path: Optional[str] = None


class ForensicEngine:
    def scan(self, doc: NormalizedDocument, context: Optional[ForensicContext] = None) -> EngineResult:
        context = context or ForensicContext()
        result = EngineResult(engine=ENGINE_NAME)

        # 이미지인 경우 LSB 통계를 구조정보에 추가
        if context.source_path and doc.structure.get("image_size"):
            doc.structure["lsb_analysis"] = analyze_image_lsb(context.source_path)

        findings: List[Finding] = []
        findings.extend(scan_residual(doc))
        findings.extend(scan_redaction(doc))
        findings.extend(scan_covert(doc))
        findings.extend(
            scan_template_residue(
                doc,
                project_case_number=context.project_case_number,
                project_court=context.project_court,
                project_parties=context.project_parties,
            )
        )
        findings.extend(scan_document_forensics(doc))

        advisory_context = context.advisory or AdvisoryContext()
        if context.enabled_advisory_signals is not None:
            advisory_context.enabled_signals = context.enabled_advisory_signals
        advisory_findings = scan_advisory(doc, advisory_context)

        # 특권·윤리 게이트 적용 (봉인 유지 + 열람 경고)
        gate = PrivilegeGate(org_block_reveal=context.org_block_reveal, allow_reveal=context.allow_reveal)
        findings.extend(gate.apply(findings, counterparty_document=context.counterparty_document))

        result.findings = findings + advisory_findings
        result.data["mm2_count"] = sum(1 for f in findings if f.meta_message_type == MetaMessageType.MM2_RESIDUAL)
        result.data["mm3_count"] = sum(1 for f in findings if f.meta_message_type == MetaMessageType.MM3_COVERT_CHANNEL)
        result.data["mm4_count"] = len(advisory_findings)
        result.data["sealed_count"] = sum(1 for f in result.findings if f.sealed_excerpt)
        result.data["forensic_level"] = self.overall_level(result.findings)
        result.data["llm_safe_summary"] = self.llm_safe_summary(result.findings)
        return result

    @staticmethod
    def overall_level(findings: List[Finding]) -> str:
        levels = [f.forensic_level for f in findings if f.forensic_level]
        for level in (ForensicLevel.CRITICAL, ForensicLevel.SUSPICIOUS, ForensicLevel.NOTABLE):
            if level in levels:
                return str(level)
        return str(ForensicLevel.BENIGN)

    @staticmethod
    def llm_safe_summary(findings: List[Finding]) -> List[Dict[str, Any]]:
        """LLM Context 투입용 요약.

        제7-A.5장에 따라 원문 문자열은 넣지 않고 유형 태그·위치정보·길이·해시만 전달한다.
        """
        out: List[Dict[str, Any]] = []
        for finding in findings:
            if finding.meta_message_type not in (
                MetaMessageType.MM2_RESIDUAL,
                MetaMessageType.MM3_COVERT_CHANNEL,
            ):
                continue
            payload = finding.sealed_excerpt or ""
            out.append(
                {
                    "finding_id": finding.finding_id,
                    "type": str(finding.type),
                    "meta_message_type": str(finding.meta_message_type),
                    "severity": str(finding.severity),
                    "document_id": finding.document_id,
                    "page": finding.page,
                    "block_id": finding.block_id,
                    "content_length": len(payload),
                    "content_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else None,
                    "content_included": False,
                }
            )
        return out


def scan_forensics(doc: NormalizedDocument, context: Optional[ForensicContext] = None) -> EngineResult:
    return ForensicEngine().scan(doc, context)
