"""제18.2장 Job Workflow 및 제7-A.5장 파이프라인 순서.

QUEUED → PARSING → ADVERSARIAL_SCANNING → OCR/EXTRACTING → PII_PROCESSING
→ VERIFYING → CROSS_CHECKING → AGGREGATING → COMPLETED

핵심 순서 규칙(제24.3장 Release Gate):
- LLM 실행 전 Adversarial Scan, 실행 후 Output Scan을 수행한다.
- 문서 원문을 system prompt와 직접 결합하지 않는다.
- 의심 문서는 자동 Indexing하지 않는다.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from packages.adversarial_engine import AdversarialScanner
from packages.audit_engine import AuditChain
from packages.claim_engine import (
    CalculationEngine,
    analyze_timeline,
    build_timeline,
    cross_document_contradictions,
    extract_claims,
    extract_entities,
    extract_events,
    resolve_entities,
)
from packages.common.config import get_settings
from packages.common.enums import (
    AuditEventType,
    EvidenceGrade,
    ExternalAIPolicy,
    FindingType,
    JobState,
    MetaMessageType,
    Severity,
    VerificationProfile,
    VerificationStatus,
)
from packages.common.schemas import Finding, NormalizedDocument, SourceRecord
from packages.document_engine import parse_document
from packages.forensic_engine import ForensicContext, ForensicEngine
from packages.forensic_engine.advisory import AdvisoryContext
from packages.legal_engine import LegalVerifier, extract_citations
from packages.llm_router import LLMRouter
from packages.pii_engine import PIIEngine, PseudonymStore
from packages.source_adapters import SourceRegistry

from .authorship import analyze_authorship, authorship_findings
from .scoring import aggregate_scores

ENGINE_NAME = "verification_engine"

# RAG 자동 색인을 차단할 위험 수준 (제7.7장)
QUARANTINE_SEVERITIES = {Severity.CRITICAL, Severity.HIGH}


@dataclass
class ProjectContext:
    project_id: str
    case_number: Optional[str] = None
    court: Optional[str] = None
    parties: List[str] = field(default_factory=list)
    case_date: Optional[str] = None
    external_ai_policy: ExternalAIPolicy = ExternalAIPolicy.MASKED
    profile: VerificationProfile = VerificationProfile.STANDARD
    counterparty_document: bool = True
    org_block_reveal: bool = False
    enabled_advisory_signals: Optional[set] = None
    requested_issues: List[str] = field(default_factory=list)


@dataclass
class DocumentInput:
    document_id: str
    path: str
    filename: str
    mime_type: str = ""
    sha256: str = ""


@dataclass
class DocumentResult:
    document_id: str
    filename: str
    normalized: Optional[NormalizedDocument] = None
    findings: List[Finding] = field(default_factory=list)
    source_records: List[SourceRecord] = field(default_factory=list)
    unverified_items: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    claims: List[Dict[str, Any]] = field(default_factory=list)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    authorship: Dict[str, Any] = field(default_factory=dict)
    masked_preview: Dict[str, Any] = field(default_factory=dict)
    quarantined: bool = False
    rag_indexable: bool = False
    warnings: List[str] = field(default_factory=list)
    engine_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationRunResult:
    run_id: str
    project_id: str
    state: JobState
    verification_key: str
    documents: List[DocumentResult] = field(default_factory=list)
    project_findings: List[Finding] = field(default_factory=list)
    scores: Dict[str, Any] = field(default_factory=dict)
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    unavailable_sources: List[Dict[str, Any]] = field(default_factory=list)
    unverified_items: List[Dict[str, Any]] = field(default_factory=list)
    model_executions: List[Dict[str, Any]] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)

    @property
    def all_findings(self) -> List[Finding]:
        return [f for d in self.documents for f in d.findings] + self.project_findings


def verification_key(
    document_hashes: List[str],
    profile: VerificationProfile,
    *,
    rule_version: str,
    prompt_version: str,
    model_config_version: str,
) -> str:
    """제18.3장 Idempotency."""
    payload = "|".join(sorted(document_hashes)) + f"|{profile}|{rule_version}|{prompt_version}|{model_config_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


ProgressCallback = Callable[[JobState, str, float], None]


class VerificationPipeline:
    def __init__(
        self,
        *,
        registry: Optional[SourceRegistry] = None,
        router: Optional[LLMRouter] = None,
        audit: Optional[AuditChain] = None,
    ) -> None:
        self.settings = get_settings()
        self.registry = registry or SourceRegistry()
        self.router = router or LLMRouter()
        self.audit = audit or AuditChain()
        self.legal = LegalVerifier(self.registry)
        self.adversarial = AdversarialScanner()
        self.forensic = ForensicEngine()
        self.calculation = CalculationEngine()

    # -- 진입점 -----------------------------------------------------------
    def run(
        self,
        run_id: str,
        context: ProjectContext,
        documents: List[DocumentInput],
        *,
        progress: Optional[ProgressCallback] = None,
    ) -> VerificationRunResult:
        def emit(state: JobState, message: str, ratio: float) -> None:
            if progress:
                progress(state, message, ratio)

        key = verification_key(
            [d.sha256 for d in documents],
            context.profile,
            rule_version=self.settings.rule_version,
            prompt_version=self.settings.prompt_version,
            model_config_version=self.settings.model_config_version(),
        )
        result = VerificationRunResult(
            run_id=run_id, project_id=context.project_id, state=JobState.QUEUED, verification_key=key
        )
        store = PseudonymStore(project_id=context.project_id)
        pii = PIIEngine(store)

        total = max(1, len(documents))
        for index, document in enumerate(documents):
            base = index / total
            try:
                document_result = self._run_document(document, context, pii, emit, base, 1 / total)
                result.documents.append(document_result)
            except Exception as exc:  # 문서 하나의 실패가 Job 전체를 실패시키지 않는다
                result.errors.append(f"{document.filename}: {exc}")
                result.documents.append(
                    DocumentResult(document_id=document.document_id, filename=document.filename,
                                   warnings=[f"처리 실패: {exc}"])
                )

        # --- CROSS_CHECKING: 프로젝트 단위 교차검증 --------------------------
        emit(JobState.CROSS_CHECKING, "문서간 교차검증", 0.85)
        result.project_findings.extend(self._cross_check(result))
        self.audit.record(
            AuditEventType.VERIFICATION,
            {"run_id": run_id, "stage": "CROSS_CHECKING", "document_count": len(documents)},
            project_id=context.project_id,
        )

        # --- AGGREGATING ----------------------------------------------------
        emit(JobState.AGGREGATING, "결과 집계", 0.95)
        result.unavailable_sources = self.registry.unavailable()
        result.unverified_items = [item for d in result.documents for item in d.unverified_items]
        result.scores = aggregate_scores(result)
        result.timeline = build_timeline(
            [e for d in result.documents for e in _events_from(d)]
        )
        result.finished_at = datetime.utcnow()

        degraded = bool(result.errors or result.unavailable_sources)
        result.state = JobState.PARTIAL_COMPLETED if degraded else JobState.COMPLETED
        if all(d.normalized is None for d in result.documents) and result.documents:
            result.state = JobState.FAILED

        self.audit.record(
            AuditEventType.VERIFICATION,
            {
                "run_id": run_id,
                "state": str(result.state),
                "verification_key": key,
                "finding_count": len(result.all_findings),
                "unavailable_sources": [s["name"] for s in result.unavailable_sources],
            },
            project_id=context.project_id,
        )
        emit(result.state, "완료", 1.0)
        return result

    # -- 문서 단위 --------------------------------------------------------
    def _run_document(
        self,
        document: DocumentInput,
        context: ProjectContext,
        pii: PIIEngine,
        emit: Callable[[JobState, str, float], None],
        base: float,
        span: float,
    ) -> DocumentResult:
        result = DocumentResult(document_id=document.document_id, filename=document.filename)

        # 1) PARSING
        emit(JobState.PARSING, f"{document.filename} 파싱", base + span * 0.05)
        doc = parse_document(
            document.path,
            document_id=document.document_id,
            filename=document.filename,
            mime_type=document.mime_type,
            sha256=document.sha256,
        )
        result.normalized = doc
        result.warnings.extend(doc.parse_warnings)
        self.audit.record(
            AuditEventType.OCR if doc.structure.get("scanned_pdf") else AuditEventType.UPLOAD,
            {"document_id": doc.document_id, "parser": doc.parser_name, "sha256": doc.sha256,
             "warnings": doc.parse_warnings},
            project_id=context.project_id,
            document_id=doc.document_id,
        )
        if doc.structure.get("unsupported_format") or doc.structure.get("parse_error"):
            result.findings.append(
                Finding.create(
                    type=FindingType.UNSUPPORTED_FORMAT if doc.structure.get("unsupported_format") else FindingType.PARSE_ERROR,
                    status=VerificationStatus.SKIPPED,
                    severity=Severity.INFO,
                    evidence_grade=EvidenceGrade.U,
                    title=f"본문을 추출하지 못했다: {document.filename}",
                    detail="; ".join(doc.parse_warnings) or "파서를 적용할 수 없다.",
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    tags=["UNVERIFIED"],
                )
            )
            result.unverified_items.append(
                {"kind": "document", "document_id": doc.document_id, "reason": "본문 추출 실패"}
            )

        # 2) ADVERSARIAL_SCANNING — 반드시 모든 LLM 호출보다 먼저
        emit(JobState.ADVERSARIAL_SCANNING, f"{document.filename} 적대적 콘텐츠 검사", base + span * 0.2)
        adversarial = self.adversarial.scan(doc)
        result.findings.extend(adversarial.findings)
        result.engine_data["adversarial"] = adversarial.data
        self.audit.record(
            AuditEventType.ADVERSARIAL_SCAN,
            {"document_id": doc.document_id, "risk": adversarial.data.get("adversarial_risk"),
             "finding_count": len(adversarial.findings)},
            project_id=context.project_id,
            document_id=doc.document_id,
        )

        # 3) MM-2/MM-3 결정론적 포렌식 + MM-4 참고신호
        emit(JobState.EXTRACTING, f"{document.filename} 포렌식 검사", base + span * 0.35)
        forensic_context = ForensicContext(
            project_case_number=context.case_number,
            project_court=context.court,
            project_parties=context.parties,
            counterparty_document=context.counterparty_document,
            org_block_reveal=context.org_block_reveal,
            allow_reveal=self.settings.allow_sealed_reveal,
            enabled_advisory_signals=context.enabled_advisory_signals,
            advisory=AdvisoryContext(requested_issues=context.requested_issues or None),
            source_path=document.path,
        )
        forensic = self.forensic.scan(doc, forensic_context)
        result.findings.extend(forensic.findings)
        result.engine_data["forensic"] = {k: v for k, v in forensic.data.items() if k != "llm_safe_summary"}
        result.engine_data["forensic_llm_safe"] = forensic.data.get("llm_safe_summary", [])

        # 4) 격리 판정 — 의심 문서는 자동 Indexing하지 않는다 (제7.7장)
        result.quarantined = any(
            f.severity in QUARANTINE_SEVERITIES
            and f.meta_message_type == MetaMessageType.MM1_MACHINE_INSTRUCTION
            for f in result.findings
        )
        result.rag_indexable = not result.quarantined
        if result.quarantined:
            result.warnings.append(
                "적대적 콘텐츠가 탐지되어 QUARANTINED 상태이다. Vector Index 자동 등록을 하지 않는다."
            )

        # 5) PII_PROCESSING
        emit(JobState.PII_PROCESSING, f"{document.filename} 비식별화", base + span * 0.5)
        masked = pii.mask_document(doc, policy=context.external_ai_policy)
        result.masked_preview = {
            "policy": masked.policy,
            "match_count": masked.match_count,
            "kinds": masked.kinds,
            "block_count": len(masked.blocks),
        }
        self.audit.record(
            AuditEventType.PII_MASKING,
            {"document_id": doc.document_id, "match_count": masked.match_count, "policy": masked.policy},
            project_id=context.project_id,
            document_id=doc.document_id,
        )
        # 비식별화 산출물에도 마스킹 실패 검사를 반복 적용한다(제7-A.2장)
        from packages.forensic_engine.redaction import scan_redaction

        result.findings.extend(scan_redaction(doc))

        # 6) VERIFYING — 인용 검증(결정론 우선)
        emit(JobState.VERIFYING, f"{document.filename} 법률 인용 검증", base + span * 0.7)
        citations = extract_citations(doc)
        result.citations = [c.to_dict() for c in citations]
        legal = self.legal.verify_citations(citations, case_date=context.case_date)
        result.findings.extend(legal.findings)
        result.source_records.extend(legal.source_records)
        result.unverified_items.extend(legal.unverified_items)
        result.engine_data["legal"] = {k: v for k, v in legal.data.items() if k != "verdicts"}
        result.engine_data["legal_verdicts"] = legal.data.get("verdicts", [])
        for record in legal.source_records:
            self.audit.record(
                AuditEventType.API_QUERY,
                {"adapter": record.adapter, "query": record.query, "status": str(record.status),
                 "response_hash": record.response_hash},
                project_id=context.project_id,
                document_id=doc.document_id,
            )

        # 7) Claim / Entity / Event / 계산 검증
        claims = extract_claims(doc, citations)
        entities = resolve_entities(extract_entities(doc))
        events = extract_events(doc)
        result.claims = [c.to_dict() for c in claims]
        result.entities = [e.to_dict() for e in entities]
        result.events = [e.to_dict() for e in events]
        result.findings.extend(self.calculation.verify_document(doc))
        result.findings.extend(analyze_timeline(events))

        # 8) 작성자 분석
        assessment = analyze_authorship(doc)
        result.authorship = assessment.to_dict()
        result.findings.extend(authorship_findings(doc, assessment))

        for finding in result.findings:
            finding.document_id = finding.document_id or doc.document_id
        return result

    # -- 프로젝트 단위 ----------------------------------------------------
    def _cross_check(self, result: VerificationRunResult) -> List[Finding]:
        events_by_document: Dict[str, List[Any]] = {}
        for document in result.documents:
            events = _events_from(document)
            if events:
                events_by_document[document.document_id] = events
        return cross_document_contradictions(events_by_document)


def _events_from(document: DocumentResult) -> List[Any]:
    from datetime import date as date_cls

    from packages.common.schemas import Event

    out: List[Event] = []
    for raw in document.events:
        value = None
        if raw.get("date"):
            try:
                y, m, d = (int(x) for x in raw["date"].split("-"))
                value = date_cls(y, m, d)
            except Exception:
                value = None
        out.append(
            Event(
                event_id=raw["event_id"],
                date=value,
                description=raw["description"],
                document_id=raw.get("document_id"),
                block_id=raw.get("block_id"),
                page=raw.get("page"),
                entity_ids=raw.get("entity_ids", []),
                event_kind=raw.get("event_kind", "GENERIC"),
                raw_date_text=raw.get("raw_date_text", ""),
            )
        )
    return out
