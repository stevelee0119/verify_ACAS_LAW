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
import json
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
    claim_contradictions,
    extract_claims,
    extract_entities,
    extract_events,
    resolve_entities,
)
from packages.common.config import get_settings
from packages.common.enums import (
    AuditEventType,
    CitationType,
    EvidenceGrade,
    ExternalAIPolicy,
    FindingType,
    JobState,
    MetaMessageType,
    Severity,
    VerificationProfile,
    VerificationStatus,
)
from packages.common.schemas import Claim, Finding, NormalizedDocument, SourceRecord
from packages.document_engine import parse_document
from packages.forensic_engine import ForensicContext, ForensicEngine
from packages.forensic_engine.advisory import AdvisoryContext
from packages.legal_engine import LegalVerifier, extract_citations, verify_argument_validity
from packages.legal_engine.source_review import case_applicability_review
from packages.source_adapters.legal_history import today_korea
from packages.llm_router import LLMRouter
from packages.pii_engine import PIIEngine, PseudonymStore
from packages.source_adapters import SourceRegistry

from .ai_document_detector import create_ai_detector_findings, detect_ai_document
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
    issue_dates: Dict[str, str] = field(default_factory=dict)


@dataclass
class DocumentInput:
    document_id: str
    path: str
    filename: str
    mime_type: str = ""
    sha256: str = ""
    is_own_document: Optional[bool] = None


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
    ai_detector_result: Dict[str, Any] = field(default_factory=dict)
    ai_hallucination_table: List[Dict[str, Any]] = field(default_factory=list)
    argument_validity_summary: str = ""
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
    context_snapshot: Optional[Dict[str, Any]] = None,
) -> str:
    """제18.3장 Idempotency."""
    payload = "|".join(sorted(document_hashes)) + f"|{profile}|{rule_version}|{prompt_version}|{model_config_version}"
    if context_snapshot is not None:
        payload += "|" + json.dumps(context_snapshot, sort_keys=True, ensure_ascii=False, default=str)
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
            context_snapshot={
                "case_date": context.case_date, "issue_dates": dict(context.issue_dates),
                "current_date": today_korea(), "external_ai_policy": str(context.external_ai_policy),
                "requested_issues": list(context.requested_issues),
                "document_ownership": {d.document_id: d.is_own_document for d in documents},
            },
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
                document_result = self._run_document(document, context, pii, emit, base, 1 / total,
                                                     source_run_id=run_id)
                result.documents.append(document_result)
            except Exception as exc:  # 문서 하나의 실패가 Job 전체를 실패시키지 않는다
                result.errors.append(f"{document.filename}: {exc}")
                result.documents.append(
                    DocumentResult(document_id=document.document_id, filename=document.filename,
                                   warnings=[f"처리 실패: {exc}"], unverified_items=[{
                                       "kind": "document", "document_id": document.document_id, "reason": "처리 실패"}])
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
        result.model_executions = [execution for d in result.documents
                                   for execution in d.engine_data.get("model_executions", [])]
        result.scores = aggregate_scores(result)
        result.timeline = build_timeline(
            [e for d in result.documents for e in _events_from(d)]
        )
        result.finished_at = datetime.utcnow()

        degraded = bool(result.errors or result.unverified_items)
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
        *,
        source_run_id: Optional[str] = None,
    ) -> DocumentResult:
        if document.is_own_document is not None:
            from dataclasses import replace
            context = replace(context, counterparty_document=not document.is_own_document)
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
        result.engine_data["page_coverage"] = doc.structure.get("page_coverage", [])
        result.unverified_items.extend({"kind": "page", "document_id": doc.document_id, **item}
            for item in doc.structure.get("page_coverage", []) if item["status"] == "UNVERIFIED")
        self.audit.record(
            AuditEventType.OCR if doc.structure.get("scanned_pdf") else AuditEventType.UPLOAD,
            {"document_id": doc.document_id, "parser": doc.parser_name, "sha256": doc.sha256,
             "warnings": doc.parse_warnings},
            project_id=context.project_id,
            document_id=doc.document_id,
        )
        # 본문을 한 글자도 읽지 못한 경우. 파싱 자체는 성공했으므로 parse_error가 아니지만,
        # 검증 관점에서는 아무것도 확인하지 못한 것이다. 조용히 넘어가면 모든 위험 축이
        # "문제 없음"으로 보고되어, 검증한 결과 깨끗한 문서와 구별되지 않는다.
        if doc.structure.get("body_extraction_failed") and not doc.body_blocks():
            result.findings.append(
                Finding.create(
                    type=FindingType.PARSE_ERROR,
                    status=VerificationStatus.UNVERIFIED,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.U,
                    title=f"본문을 읽지 못해 내용 검증을 수행하지 못했다: {document.filename}",
                    detail=(
                        "; ".join(doc.parse_warnings)
                        + " 본 문서에 대한 인용·주장·적대적 콘텐츠 검사 결과는 '이상 없음'이 아니라 "
                        "'확인하지 못함'이다."
                    ),
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    tags=["UNVERIFIED"],
                )
            )
            result.unverified_items.append(
                {"kind": "document_body", "document_id": doc.document_id,
                 "reason": "본문 추출 실패(OCR 미설치 등)로 내용 검증 미수행"}
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
        self._legal_reviews(result, citations, context)
        self._semantic_review(result, citations, context, pii)
        for record in result.source_records:
            self.audit.record(
                AuditEventType.API_QUERY,
                {"adapter": record.adapter, "query": record.query, "status": str(record.status),
                 "response_hash": record.response_hash},
                project_id=context.project_id,
                document_id=doc.document_id,
            )

        # 7) Claim / Entity / Event / 계산 검증
        claims = extract_claims(doc, citations, project_id=context.project_id, source_run_id=source_run_id)
        entities = resolve_entities(extract_entities(doc, project_id=context.project_id),
                                    project_id=context.project_id)
        events = extract_events(doc, project_id=context.project_id, source_run_id=source_run_id)
        result.claims = [c.to_dict() for c in claims]
        result.entities = [e.to_dict() for e in entities]
        result.events = [e.to_dict() for e in events]
        result.findings.extend(self.calculation.verify_document(doc))
        result.findings.extend(analyze_timeline(events))

        # 8) 허위 판례 인용 기반 법률적 주장 타당성 검토 및 AI 임의 생성 대조표 생성
        arg_validity = asyncio.run(
            verify_argument_validity(
                doc,
                citations,
                result.engine_data.get("legal_verdicts", []),
                claims,
                router=self.router,
                external_ai_policy=context.external_ai_policy,
            )
        )
        result.findings.extend(arg_validity.findings)
        result.ai_hallucination_table = [r.to_dict() for r in arg_validity.rows]
        result.argument_validity_summary = arg_validity.overall_validity_summary
        result.engine_data["ai_hallucination_table"] = result.ai_hallucination_table
        result.engine_data["argument_validity_summary"] = result.argument_validity_summary

        # 9) 작성자 분석 및 AI 문서 전체 생성 여부 심층 판별
        assessment = analyze_authorship(doc)
        result.authorship = assessment.to_dict()
        result.findings.extend(authorship_findings(doc, assessment))

        # 메타데이터 AI 힌트 여부
        metadata_hint = bool(assessment.signals.get("provenance_metadata")) or any(
            f.type == FindingType.METADATA_ANOMALY for f in result.findings
        )
        ai_detector_res = asyncio.run(
            detect_ai_document(
                doc,
                result.findings,
                router=self.router,
                external_ai_policy=context.external_ai_policy,
                metadata_indications=metadata_hint,
            )
        )
        result.ai_detector_result = ai_detector_res.to_dict()
        result.engine_data["ai_detector_result"] = result.ai_detector_result
        result.findings.extend(create_ai_detector_findings(doc, ai_detector_res))

        for finding in result.findings:
            finding.document_id = finding.document_id or doc.document_id
        return result

    def _legal_reviews(self, result, citations, context):
        """Keep the incident-date review and every issue-date review distinct."""
        current = today_korea()
        scopes = [("incident", None, context.case_date, citations)]
        statutes = [c for c in citations if c.type == CitationType.STATUTE]
        scopes.extend(("issue", issue_id, when, statutes)
                      for issue_id, when in sorted(context.issue_dates.items()))
        grouped, verdicts, applicability = [], [], []
        by_id = {c.citation_id: c for c in citations}
        for scope, issue_id, when, review_citations in scopes:
            review_id = f"issue:{issue_id}" if issue_id is not None else "incident"
            legal = self.legal.verify_citations(
                review_citations, case_date=when, incident_date=context.case_date, current_date=current)
            label = {"review_id": review_id, "scope": scope, "issue_id": issue_id,
                     "reference_date": when, "incident_date": context.case_date, "current_date": current}
            for verdict in legal.data.get("verdicts", []):
                verdict.update(label)
                citation = by_id.get(verdict["citation_id"])
                if citation and citation.type in (CitationType.CASE, CitationType.CONSTITUTIONAL):
                    review = case_applicability_review(
                        citation, verdict.get("official_record"),
                        source_record_ids=verdict.get("source_record_ids", []))
                    review.update(label)
                    applicability.append(review)
                verdicts.append(verdict)
            for finding in legal.findings:
                finding.confidence_features["legal_review"] = dict(label)
                if issue_id is not None:
                    finding.tags.extend(["ISSUE_DATE_REVIEW", f"ISSUE:{issue_id}"])
                    finding.detail = f"쟁점 {issue_id}, 검토 기준일 {when or '미입력'}. " + finding.detail
            result.findings.extend(legal.findings)
            result.source_records.extend(legal.source_records)
            result.unverified_items.extend({**item, **label} for item in legal.unverified_items)
            grouped.append({
                **label, "advisory_only": True,
                "citation_ids": [c.citation_id for c in review_citations],
                "finding_ids": [f.finding_id for f in legal.findings],
                "source_record_ids": [r.source_record_id for r in legal.source_records],
                "verdicts": legal.data.get("verdicts", []),
            })
            if scope == "incident":
                result.engine_data["legal"] = {k: v for k, v in legal.data.items() if k != "verdicts"}
        result.engine_data["legal"]["dated_review_count"] = len(grouped)
        result.engine_data["legal_reviews"] = grouped
        result.engine_data["legal_verdicts"] = verdicts
        result.engine_data["case_applicability_reviews"] = applicability

    def _semantic_review(self, result, citations, context, pii):
        """Source-grounded model advice never replaces deterministic findings."""
        by_id = {c.citation_id: c for c in citations}
        reviews = []
        for verdict in result.engine_data.get("legal_verdicts", []):
            citation = by_id.get(verdict.get("citation_id"))
            official = verdict.get("official_record") or {}
            if not citation or not any(k in verdict.get("levels", {}) for k in ("level4", "level5")):
                continue
            reason = ""
            if result.quarantined:
                reason = "격리 문서이므로 AI 검토를 수행하지 않음"
            elif context.profile == VerificationProfile.QUICK:
                reason = "빠른 검토에서는 의미·적용 검토를 수행하지 않음"
            elif not official.get("full_text"):
                reason = "공식 판결 전문이 없어 의미·적용 검토를 수행하지 않음"
            if reason:
                reviews.append({"citation_id": citation.citation_id, "status": "UNVERIFIED", "reason": reason,
                                "review_id": verdict.get("review_id"), "advisory_only": True})
                continue
            source_text = str(official["full_text"])[:24000]
            document_text = citation.context[:8000]
            if context.external_ai_policy != ExternalAIPolicy.ORIGINAL:
                source_text = pii.mask_text(source_text).masked_text
                document_text = pii.mask_text(document_text).masked_text
            outcome = asyncio.run(self.router.cascade(
                question="인용된 판결의 취지와 문서의 주장이 부합하는지, 사실관계 차이와 적용상 한계를 검토하라. 반드시 제공된 공식 전문의 실제 문구를 evidence_quotes에 인용하라.",
                evidence={"official": {"case_number": official.get("case_number"), "full_text": source_text},
                          "document": document_text},
                profile=context.profile, policy=context.external_ai_policy))
            result.engine_data.setdefault("model_executions", []).extend(e.to_dict() for e in outcome.executions)
            model_verdicts = [s["verdict"] for s in outcome.stages if s.get("used") and s.get("verdict")]
            quotes = [q for v in model_verdicts for q in v.get("evidence_quotes", [])]
            grounded = bool(quotes) and all(q.strip() and q in source_text for q in quotes)
            review = {"citation_id": citation.citation_id, "status": "UNVERIFIED",
                      "review_id": verdict.get("review_id"),
                      "source_record_ids": verdict.get("source_record_ids", []),
                      "advisory_only": True, "source_quotes_validated": grounded,
                      "source_truncated": len(str(official["full_text"])) > len(source_text),
                      "reason": outcome.rationale if grounded else "공식 전문에 있는 근거 인용이 확인되지 않아 AI 의견을 채택하지 않음",
                      "stages": outcome.stages if grounded else [], "evidence_quotes": quotes if grounded else []}
            reviews.append(review)
            for level in ("level4", "level5"):
                verdict["levels"][level] = "ADVISORY_REVIEWED" if grounded else "UNVERIFIED"
        result.engine_data["semantic_reviews"] = reviews

    # -- 프로젝트 단위 ----------------------------------------------------
    def _cross_check(self, result: VerificationRunResult) -> List[Finding]:
        from dataclasses import fields
        import json

        events_by_document: Dict[str, List[Any]] = {}
        claims = []
        claim_fields = {item.name for item in fields(Claim)}
        for document in result.documents:
            if document.quarantined:
                continue
            events = _events_from(document)
            if events:
                events_by_document[document.document_id] = events
            claims.extend(Claim(**{key: value for key, value in raw.items() if key in claim_fields})
                          for raw in document.claims)
        candidates = claim_contradictions(claims, project_id=result.project_id)
        candidates.extend(cross_document_contradictions(events_by_document))
        findings, seen = [], set()
        for finding in candidates:
            features = finding.confidence_features
            locations = sorted((source.get("document_id") or "", source.get("block_id") or "",
                                tuple(source.get("span") or ()))
                               for source in features.get("sources", []))
            key = json.dumps([locations, features.get("differences")], sort_keys=True)
            if key not in seen:
                seen.add(key)
                findings.append(finding)
        return findings


def _events_from(document: DocumentResult) -> List[Any]:
    from dataclasses import fields
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
        preserved = {item.name for item in fields(Event)} - {"date"}
        out.append(Event(date=value, **{key: val for key, val in raw.items() if key in preserved}))
    return out
