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
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    ADVERSARIAL_FINDING_TYPES,
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
from packages.claim_engine.attachments import analyze_attachments
from packages.claim_engine.classification import link_claim_evidence
from packages.legal_engine.components import affected_by_unavailable
from packages.legal_engine.reference_dates import reference_date_candidates
from packages.legal_engine.source_review import case_applicability_review
from packages.legal_engine.spec_mapping import relevance_finding
from packages.source_adapters.legal_history import today_korea
from packages.llm_router import LLMRouter
from packages.pii_engine import PIIEngine, PseudonymStore
from packages.source_adapters import SourceRegistry
from packages.source_adapters.transport import prepare_source_document, source_lookup_session

from packages.claim_engine.assertion import analyze_assertions
from packages.claim_engine.evidence_consistency import check_document as check_evidence_consistency
from packages.claim_engine.evidence_consistency import cross_document_copies
from packages.legal_engine.legal_rules import review_legal_rules
from packages.legal_engine.internal_citation import (build_clause_index, check_references,
                                                    internal_citation_findings)
from packages.legal_engine.omission import analyze_omissions, omission_findings

from .ai_document_detector import create_ai_detector_findings, detect_ai_document
from .finalize import finalize_document_findings
from packages.document_engine.reading_text import SPACE_MAP
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
    # 사용자가 지정한 문서 역할. "SOURCE_TEXT" = 조항 대조에 쓸 원문 첨부(계약서·규정·법령 사본)
    role: Optional[str] = None


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
    role: Optional[str] = None


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
        self, run_id: str, context: ProjectContext, documents: List[DocumentInput], *,
        progress: Optional[ProgressCallback] = None, check: Optional[Callable[[], None]] = None,
    ) -> VerificationRunResult:
        current_progress = [JobState.QUEUED, "검증 준비", 0.0]

        def emit(state, message, ratio):
            if check:
                check()
            if progress:
                progress(state, message, ratio)
            current_progress[:] = [state, message, ratio]

        def source_progress(message):
            if progress:
                state, stage, ratio = current_progress
                progress(state, f"{stage} · {message}", ratio)

        with source_lookup_session(self.settings.source_lookup_budget_seconds, check=check,
                                   notify=source_progress, max_attempts=self.settings.source_lookup_attempts,
                                   request_timeout=self.settings.http_timeout):
            return self._run(run_id, context, documents, progress=emit)

    def _run(
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
            base = 0.85 * index / total
            try:
                document_result = self._run_document(document, context, pii, emit, base, 0.85 / total,
                                                     source_run_id=run_id, run_inputs=documents)
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
        result.unavailable_sources = annotate_unavailable_sources(self.registry.unavailable(), result.documents)
        result.unverified_items = [item for d in result.documents for item in d.unverified_items]
        result.model_executions = [execution for d in result.documents
                                   for execution in d.engine_data.get("model_executions", [])]
        result.scores = aggregate_scores(result)
        result.timeline = build_timeline(
            [e for d in result.documents for e in _events_from(d)]
        )
        result.finished_at = datetime.utcnow()

        # '일부 미확인'은 실제로 확인하지 못한 항목이 있을 때만이다. 공식 원문으로 확인했고
        # 취지·적용 검토만 남은 인용(PARTIAL)까지 세면 인용이 있는 모든 문서가 미확인이 된다.
        degraded = bool(result.errors or any(item.get("scope") != "PARTIAL" for item in result.unverified_items))
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
        run_inputs: Optional[List[DocumentInput]] = None,
    ) -> DocumentResult:
        if document.is_own_document is not None:
            from dataclasses import replace
            context = replace(context, counterparty_document=not document.is_own_document)
        result = DocumentResult(document_id=document.document_id, filename=document.filename, role=document.role)

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
        if (doc.structure.get("body_extraction_failed") or doc.structure.get("unsupported_body")) and not doc.body_blocks():
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
                 "reason": "본문 추출 실패로 내용 검증 미수행"}
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
        emit(JobState.VERIFYING, f"{document.filename} 인용 항목 추출", base + span * 0.55)
        citations = extract_citations(doc)
        result.citations = [c.to_dict() for c in citations]
        self._legal_reviews(result, citations, context, progress=lambda done, total: emit(
            JobState.VERIFYING, f"{document.filename} 법률 인용 확인 {done}/{total}건",
            base + span * (0.55 + 0.20 * done / max(1, total))))
        self._attach_reference_dates(result, doc, context)
        emit(JobState.VERIFYING, f"{document.filename} 판례 의미·적용 검토", base + span * 0.75)
        self._semantic_review(result, citations, context, pii, progress=lambda done, total: emit(
            JobState.VERIFYING, f"{document.filename} 판례 의미·적용 검토 {done}/{total}건",
            base + span * (0.75 + 0.05 * done / max(1, total))))
        # 출처 조회 기록은 한 문서에 수천 건이 나온다. 건수는 줄이지 않되
        # 한 번에 잇는다. 건마다 트랜잭션을 열면 그 쓰기가 DB 쓰기 잠금을
        # 독차지해 임차 갱신이 밀리고, 작업이 정상 실행 중에 회수된다.
        self.audit.record_many([
            (AuditEventType.API_QUERY,
             {"adapter": record.adapter, "query": record.query, "status": str(record.status),
              "response_hash": record.response_hash},
             {"project_id": context.project_id, "document_id": doc.document_id})
            for record in result.source_records
        ])

        # 7) Claim / Entity / Event / 계산 검증
        emit(JobState.VERIFYING, f"{document.filename} 주장·사건·금액 분석", base + span * 0.81)
        claims = extract_claims(doc, citations, project_id=context.project_id, source_run_id=source_run_id)
        entities = resolve_entities(extract_entities(doc, project_id=context.project_id),
                                    project_id=context.project_id)
        events = extract_events(doc, project_id=context.project_id, source_run_id=source_run_id)
        # 문서가 근거로 든 첨부·증거를 입력 파일과 대조하고, 관련 주장에 그 상태를 붙인다.
        uploads = [{"document_id": d.document_id, "filename": d.filename, "sha256": d.sha256}
                   for d in (run_inputs or [document])]
        attachments = analyze_attachments(doc, uploads, claims)
        result.findings.extend(attachments.pop("findings"))
        result.engine_data["attachments"] = attachments
        result.engine_data["tables"] = [
            {k: v for k, v in table.items() if k != "cells"} | {"parsed": bool(table.get("cells"))}
            for table in doc.structure.get("tables", [])]
        link_claim_evidence(claims, attachments["items"])
        result.claims = [c.to_dict() for c in claims]
        result.entities = [e.to_dict() for e in entities]
        result.events = [e.to_dict() for e in events]
        result.findings.extend(self.calculation.verify_document(doc))
        result.findings.extend(analyze_timeline(events))
        # 법리 규칙 검토: 공식 원문 근거로 청구취지·주장의 형태를 점검한다(v2 Phase 6).
        try:
            result.findings.extend(review_legal_rules(doc))
        except Exception as exc:  # pragma: no cover - 방어
            result.warnings.append(f"법리 규칙 검토 경고: {exc}")
        # 증거 정합성: 호증 목록의 작성일·결번·인적사항, 진술서 형식(v2 R9)
        try:
            result.findings.extend(check_evidence_consistency(doc))
        except Exception as exc:  # pragma: no cover - 방어
            result.warnings.append(f"증거 정합성 점검 경고: {exc}")

        # 외부 모델에 보내는 본문은 의미·적용 검토와 같은 기준으로 가린다.
        mask_for_models = (None if context.external_ai_policy == ExternalAIPolicy.ORIGINAL
                           else (lambda text: pii.mask_text(text).masked_text))

        # 8) 허위 판례 인용 기반 법률적 주장 타당성 검토 및 AI 임의 생성 대조표 생성
        emit(JobState.VERIFYING, f"{document.filename} 법률 주장 타당성 검토", base + span * 0.85)
        try:
            arg_validity = asyncio.run(
                verify_argument_validity(
                    doc,
                    citations,
                    result.engine_data.get("legal_verdicts", []),
                    claims,
                    router=self.router,
                    external_ai_policy=context.external_ai_policy,
                    mask=mask_for_models,
                )
            )
            result.findings.extend(arg_validity.findings)
            result.ai_hallucination_table = [r.to_dict() for r in arg_validity.rows]
            result.argument_validity_summary = arg_validity.overall_validity_summary
            result.engine_data["ai_hallucination_table"] = result.ai_hallucination_table
            result.engine_data["argument_validity_summary"] = result.argument_validity_summary
        except Exception as e:
            result.warnings.append(f"법률 주장 타당성 검토 경고: {e}")

        # 9) 작성자 분석 및 AI 문서 전체 생성 여부 심층 판별
        emit(JobState.VERIFYING, f"{document.filename} 작성 이력 분석", base + span * 0.9)
        assessment = analyze_authorship(doc)
        result.authorship = assessment.to_dict()
        result.findings.extend(authorship_findings(doc, assessment))

        # 메타데이터 AI 힌트 여부
        metadata_hint = bool(assessment.signals.get("provenance_metadata")) or any(
            f.type == FindingType.METADATA_ANOMALY for f in result.findings
        )
        emit(JobState.VERIFYING, f"{document.filename} AI 작성 정황 분석", base + span * 0.92)
        try:
            ai_detector_res = asyncio.run(
                detect_ai_document(
                    doc,
                    result.findings,
                    router=self.router,
                    external_ai_policy=context.external_ai_policy,
                    metadata_indications=metadata_hint,
                    mask=mask_for_models,
                    # 문서 속 지시문은 공격 탐지의 근거일 뿐 작성 주체의 근거가 아니다.
                    exclude_texts=[str((f.confidence_features or {}).get("observed_text") or "")
                                   for f in result.findings
                                   if f.type in ADVERSARIAL_FINDING_TYPES and not f.advisory_only],
                    exclude_block_ids=[block_id for f in result.findings
                                       if f.type in ADVERSARIAL_FINDING_TYPES and not f.advisory_only
                                       for block_id in ((f.confidence_features or {}).get("block_ids")
                                                        or ([f.block_id] if f.block_id else []))],
                )
            )
            result.ai_detector_result = ai_detector_res.to_dict()
            result.engine_data["ai_detector_result"] = result.ai_detector_result
            result.findings.extend(create_ai_detector_findings(doc, ai_detector_res))
        except Exception as e:
            result.warnings.append(f"AI 문서 생성 판별 경고: {e}")

        # 10) 명세 v1.0 제1.2장: 초안 흔적, 불확실성 미고지, 과잉 일반화, 출처 위계
        #     확신 표현 자체는 결함이 아니다. 원문을 확보하지 못한 채 그렇게 쓴 것이
        #     결함이므로, 미검증 인용 목록을 함께 넘긴다.
        emit(JobState.VERIFYING, f"{document.filename} 표현·검토 누락 검사", base + span * 0.96)
        try:
            # 불확실성 미고지는 최종 판정이 NOT_FOUND·UNVERIFIED인 인용에만 낸다(v3 D5). 원문을 조회해 불일치까지
            # 판정한 인용에 "원문 미확보 상태에서 확정적으로 서술"을 함께 내면 서로 모순된다.
            unverified_ids = {v.get("citation_id") for v in result.engine_data.get("legal_verdicts", [])
                              if v.get("status") in ("NOT_FOUND", "UNVERIFIED")}
            unverified_ids |= {item.get("citation_id") for item in result.unverified_items
                               if item.get("kind") == "citation" and item.get("status") == "UNVERIFIED"}
            unverified_citations = [c for c in citations if c.citation_id in unverified_ids]
            # 인용 원문(raw_text)은 NBSP를 일반 공백으로 바꾼 읽기 본문에서 뽑았으므로 같은 기준으로 맞춘다.
            body = "\n".join(block.text for page in doc.pages for block in page.blocks
                              if block.source_layer == "visible_text" and block.text).translate(SPACE_MAP)
            result.findings.extend(analyze_assertions(
                body, citations=citations, unverified_citations=unverified_citations,
                document_id=doc.document_id,
            ))
            # 제7.2장 누락 탐지. 결론을 확정하지 않고 누락 후보만 제시한다.
            reports = analyze_omissions(body)
            result.engine_data["omission_reports"] = [r.to_dict() for r in reports]
            result.findings.extend(omission_findings(reports, document_id=doc.document_id))
        except Exception as e:
            result.warnings.append(f"표현·초안흔적 검사 경고: {e}")

        for finding in result.findings:
            finding.document_id = finding.document_id or doc.document_id
        # 인용마다 최종 판정 하나, 모든 finding에 필수 필드(v2 Phase 1)
        statuses = {v.get("citation_id"): v.get("status") for v in result.engine_data.get("legal_verdicts", [])}
        result.findings = finalize_document_findings(result.findings, doc, document.document_id, statuses)
        emit(JobState.VERIFYING, f"{document.filename} 문서 분석 완료", base + span)
        return result

    @staticmethod
    def _attach_reference_dates(result, doc, context):
        """문서의 날짜를 기준일 '후보'로만 붙인다. 사람이 확인하기 전에는 적용하지 않는다."""
        candidates = reference_date_candidates(doc.visible_text)
        result.engine_data["reference_date_candidates"] = candidates
        usable = [c for c in candidates if c["candidate_for_reference"]]
        if context.case_date or not usable:
            return
        note = (f"문서에서 기준일 후보 {len(usable)}건(" + ", ".join(
            f"{c['label']} {c['date']}" for c in usable[:3]) + ")을 찾았으나 자동 적용하지 않았다. "
            "사건 설정에서 기준일을 확인해 입력하면 시간적 적용을 검토한다")
        for verdict in result.engine_data.get("legal_verdicts", []):
            temporal = next((c for c in verdict.get("components") or [] if c["key"] == "temporal_applicability"), None)
            if temporal and temporal["status"] != "CONFIRMED":
                verdict["reference_date_candidates"] = usable[:5]
                temporal["meaning"] = "기준일 미입력 — " + note
        for item in result.unverified_items:
            if item.get("type") == "STATUTE":
                item["reference_date_candidates"] = usable[:5]

    def _legal_reviews(self, result, citations, context, *, progress=None):
        """Keep the incident-date review and every issue-date review distinct."""
        current = today_korea()
        scopes = [("incident", None, context.case_date, citations)]
        statutes = [c for c in citations if c.type == CitationType.STATUTE]
        scopes.extend(("issue", issue_id, when, statutes)
                      for issue_id, when in sorted(context.issue_dates.items()))
        grouped, verdicts, applicability = [], [], []
        by_id = {c.citation_id: c for c in citations}
        completed = 0
        total = sum(len(scope[3]) for scope in scopes)
        lookup = prepare_source_document(total,
            base_seconds=self.settings.source_lookup_budget_seconds,
            max_seconds=self.settings.source_lookup_max_document_seconds,
            recovery_seconds=self.settings.source_lookup_recovery_seconds)
        for scope, issue_id, when, review_citations in scopes:
            review_id = f"issue:{issue_id}" if issue_id is not None else "incident"
            legal = self.legal.verify_citations(
                review_citations, case_date=when, incident_date=context.case_date, current_date=current,
                progress=(lambda done, count: progress(completed + done, total)) if progress else None)
            completed += len(review_citations)
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
                    # 제4.2장. 존재 확인과 관련성은 별개다. 관련성 축이 채워진
                    # 경우에만 판정하고, 재지 않은 축을 약하다고 말하지 않는다.
                    weak = relevance_finding(
                        review.get("relevance") or {},
                        case_number=citation.case_number or "",
                        citation_id=citation.citation_id,
                        document_id=citation.document_id, page=citation.page)
                    if weak is not None:
                        result.findings.append(weak)
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
        # grouped의 판정은 legal_verdicts와 겹쳐 보이지만 중복이 아니다.
        # 같은 인용이라도 기준일이 다르면 적용 법령 버전이 달라진다(제4.2장).
        # 기준일별 스냅샷이므로 줄이지 않는다.
        result.engine_data["legal_reviews"] = grouped
        result.engine_data["legal_verdicts"] = verdicts
        result.engine_data["case_applicability_reviews"] = applicability
        if lookup:
            result.engine_data["source_lookup"] = {
                "spent_seconds": round(lookup.spent_seconds, 3),
                "budget_seconds": lookup.budget_seconds,
                "max_attempts": lookup.max_attempts,
                "recovery_used": lookup.recovery_used,
                "retry_exhausted_count": sum(bool(v.get("source_lookup", {}).get("retryable")) for v in verdicts),
            }

    @staticmethod
    def _provider_reason(text: str) -> str:
        """공급자 오류를 결과에 남기되 자격증명 조각이 섞이지 않게 한다.

        오류 본문에는 키 일부가 그대로 실려 오는 경우가 있다. 검증 결과는
        보고서로 내보내지므로 여기서 지운다.
        """
        import re as _re

        if not text:
            return "사유 미기재"
        cleaned = _re.sub(r"(sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}|[A-Za-z0-9_\-]{40,})",
                          "[REDACTED]", str(text))
        cleaned = _re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:160]

    def _semantic_review(self, result, citations, context, pii, *, progress=None):
        """Source-grounded model advice never replaces deterministic findings."""
        by_id = {c.citation_id: c for c in citations}
        reviews = []
        verdicts = result.engine_data.get("legal_verdicts", [])
        for index, verdict in enumerate(verdicts):
            if progress:
                progress(index, len(verdicts))
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
            # 모델이 한 번도 실행되지 않은 것과, 실행됐으나 근거 인용이 확인되지
            # 않은 것은 전혀 다르다. 둘을 같은 문구로 적으면 공급자 키·모델 ID가
            # 잘못되어 AI가 아무 일도 하지 않는 동안에도 "검토했으나 채택하지
            # 않았다"로 읽힌다. 실제로 세 공급자가 모두 실패하는 동안 그렇게
            # 기록되고 있었다.
            model_ran = any(s.get("used") for s in outcome.stages)
            if grounded:
                reason = outcome.rationale
            elif model_ran:
                reason = "공식 전문에 있는 근거 인용이 확인되지 않아 AI 의견을 채택하지 않음"
            else:
                reason = (f"AI 공급자를 사용하지 못해 의미·적용 검토를 수행하지 못함"
                          f"({self._provider_reason(outcome.rationale)})")
            review = {"citation_id": citation.citation_id, "status": "UNVERIFIED",
                      "review_id": verdict.get("review_id"),
                      "source_record_ids": verdict.get("source_record_ids", []),
                      "advisory_only": True, "source_quotes_validated": grounded,
                      "model_executed": model_ran,
                      "source_truncated": len(str(official["full_text"])) > len(source_text),
                      "reason": reason,
                      "stages": outcome.stages if grounded else [], "evidence_quotes": quotes if grounded else []}
            reviews.append(review)
            for level in ("level4", "level5"):
                verdict["levels"][level] = "ADVISORY_REVIEWED" if grounded else "UNVERIFIED"
        result.engine_data["semantic_reviews"] = reviews
        if progress:
            progress(len(verdicts), len(verdicts))

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
        candidates.extend(self._internal_citation_check(result))
        candidates.extend(cross_document_copies(
            [d.normalized for d in result.documents if not d.quarantined and d.normalized is not None]))
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


    def _internal_citation_check(self, result: VerificationRunResult) -> List[Finding]:
        """제4.4장. 첨부문서의 조항 색인으로 다른 문서의 조항 참조를 대조한다.

        어느 문서가 참조이고 어느 문서가 원본인지 미리 알 수 없으므로,
        조항 색인이 잡히는 문서를 모두 원본 후보로 두고 교차 대조한다.
        참조한 문서 자신의 조항은 대조 대상에서 뺀다.
        """
        from packages.common.enums import CitationType as _CitationType
        from packages.document_engine.reading_text import build_reading_text
        from packages.legal_engine.citation_extractor import extract_from_text
        from packages.legal_engine.internal_citation import clause_source_eligible, source_pointers

        indices: Dict[str, Dict[str, Any]] = {}
        pointers: Dict[str, List[str]] = {}
        bodies: Dict[str, Tuple[str, List[Tuple[int, int]]]] = {}
        for document in result.documents:
            if document.quarantined or document.normalized is None:
                continue
            text = build_reading_text(document.normalized).text
            # 법령·행정규칙 인용 안의 "제N조"는 첨부문서가 아니라 그 법령의 조문이다.
            statute_spans = [c.span for c in extract_from_text(text)
                             if c.span and c.type in (_CitationType.STATUTE, _CitationType.ADMIN_RULE)]
            bodies[document.document_id] = (text, statute_spans)
            if not clause_source_eligible(document.normalized, role=getattr(document, "role", None)):
                continue
            index = build_clause_index(document.normalized)
            if len(index) >= 2:  # 조항이 하나뿐이면 색인으로 보지 않는다
                indices[document.document_id] = index
                pointers[document.document_id] = source_pointers(document.normalized, document.filename)

        findings: List[Finding] = []
        for document_id, (text, statute_spans) in bodies.items():
            for source_id, index in indices.items():
                if source_id == document_id or not text:
                    continue
                label = next((d.filename for d in result.documents
                              if d.document_id == source_id), "첨부문서")
                checks = [c for c in check_references(text, index, exclude_spans=statute_spans,
                                                      pointers=pointers[source_id])
                          if c.matches_concept is False]
                findings.extend(internal_citation_findings(
                    checks, source_label=label, document_id=document_id))
        return findings


def annotate_unavailable_sources(sources: List[Dict[str, Any]], documents: List[Any]) -> List[Dict[str, Any]]:
    """사용하지 못한 출처마다 이번 실행에서 영향을 받은 인용을 연결한다.

    학술자료가 없는 법령·판례 문서에서 KCI 키가 없다는 사실은 검증 결과에 영향이 없다.
    영향이 없는 출처는 'NOT_NEEDED'로 표시해 결과를 불필요하게 낮춰 보이지 않게 한다.
    """
    citations = [c for d in documents for c in (d.citations or [])]
    types = sorted({str(c.get("type")) for c in citations})
    out = []
    for source in sources:
        affected_types = affected_by_unavailable(str(source.get("name", "")), types)
        ids = [c.get("citation_id") for c in citations if str(c.get("type")) in (affected_types or [])]
        out.append({**source, "impact": "AFFECTS_VERIFICATION" if ids else "NOT_NEEDED",
                    "affected_citation_types": affected_types or [], "affected_citation_ids": ids,
                    "impact_note": (f"이번 실행의 인용 {len(ids)}건 검증에 영향" if ids else
                                    "이번 문서에 이 출처로 확인할 인용이 없어 검증 결과에 영향 없음")})
    return out


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
