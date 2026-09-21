"""제9.2장 판례 검증 5단계 + 제9.4장 법령 기준시점 검증.

Level 1 판례 존재 여부      - 공식 DB 검색
Level 2 사건번호·법원·선고일 - 정확 일치 비교
Level 3 직접 인용문          - Exact/Fuzzy 문자열 비교
Level 4 판례 취지            - 공식 판시사항·판결요지 기반 의미 비교
Level 5 문맥 왜곡            - 조건·예외·사실관계 누락 Critic 검증

Level 1~3은 결정론적으로 수행한다. Level 4~5는 LLM이 담당하되
공식 Source가 없으면 UNVERIFIED로 남기고 LLM 답변만으로 VERIFIED 처리하지 않는다
(부록 C 제3항).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    AdapterStatus,
    CitationType,
    EvidenceGrade,
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Citation, EngineResult, Evidence, Finding, SourceRecord
from packages.common.textutil import contains_fuzzy, normalize_quote, similarity
from packages.source_adapters import SourceRegistry

from .normalize import canonical_article, same_case_number
from .source_review import date_context, verify_decision_source, verify_statute_source
from .spec_mapping import spec_source_verdict
from packages.source_adapters.legal_history import legal_date
from packages.source_adapters.transport import source_lookup_trace, source_recovery

ENGINE_NAME = "legal_engine"

QUOTE_EXACT_THRESHOLD = 0.98
QUOTE_FUZZY_THRESHOLD = 0.88


@dataclass
class CitationVerdict:
    citation: Citation
    status: VerificationStatus
    findings: List[Finding] = field(default_factory=list)
    source_records: List[SourceRecord] = field(default_factory=list)
    official_record: Optional[Dict[str, Any]] = None
    levels: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    review: Dict[str, Any] = field(default_factory=dict)
    lookup: Dict[str, Any] = field(default_factory=dict)


class LegalVerifier:
    def __init__(self, registry: Optional[SourceRegistry] = None) -> None:
        self.registry = registry or SourceRegistry()

    # -- 진입점 -----------------------------------------------------------
    def verify_citations(
        self, citations: List[Citation], *, case_date: Optional[str] = None,
        incident_date: Optional[str] = None, current_date: Optional[str] = None,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> EngineResult:
        result = EngineResult(engine=ENGINE_NAME)
        verdicts: List[CitationVerdict] = []

        def verify(citation):
            if citation.type in (CitationType.CASE, CitationType.CONSTITUTIONAL):
                verdict = self.verify_case(citation)
            elif citation.type == CitationType.STATUTE:
                verdict = self.verify_statute(citation, as_of=case_date,
                                              incident_date=incident_date, current_date=current_date)
            elif citation.type in (CitationType.INTERPRETATION, CitationType.ADMIN_APPEAL):
                verdict = verify_decision_source(self, citation)
            elif citation.type == CitationType.ACADEMIC:
                verdict = self.verify_academic(citation)
            else:
                verdict = CitationVerdict(citation, VerificationStatus.SKIPPED)
                verdict.notes.append("이 인용 유형의 공식 원문 검증 어댑터는 아직 지원하지 않습니다")
            return verdict

        pending = []
        for index, citation in enumerate(citations):
            if progress:
                progress(index, len(citations))
            with source_lookup_trace() as trace:
                verdict = verify(citation)
            verdict.lookup = {**trace.summary(), "deferred_retry": False}
            verdicts.append(verdict)
            if trace.retryable:
                pending.append(index)
            if progress:
                progress(index + 1, len(citations))

        if pending:
            with source_recovery() as recovery:
                if recovery:
                    for number, index in enumerate(pending, 1):
                        recovery.message(f"지연된 인용 다시 확인 {number}/{len(pending)}건")
                        prior = verdicts[index]
                        with source_lookup_trace() as trace:
                            verdict = verify(citations[index])
                        summary = trace.summary()
                        history = [*prior.lookup.get("requests", []), *summary["requests"]]
                        recovered = bool(summary["requests"]) and all(
                            r["status"] == str(AdapterStatus.READY) for r in summary["requests"])
                        verdict.lookup = {**summary, "deferred_retry": True,
                            "http_attempts": prior.lookup["http_attempts"] + summary["http_attempts"],
                            "cache_hits": prior.lookup["cache_hits"] + summary["cache_hits"],
                            "requests": history,
                            "recovery_status": ("RETRY_EXHAUSTED" if trace.retryable else
                                                "RECOVERED" if recovered else "UNAVAILABLE")}
                        # Keep failed lookup evidence for audit, not obsolete findings.
                        ids = {r.source_record_id for r in verdict.source_records}
                        verdict.source_records.extend(r for r in prior.source_records if r.source_record_id not in ids)
                        verdicts[index] = verdict

        for verdict in verdicts:
            if verdict.lookup.get("retryable"):
                verdict.notes.append(
                    f"외부 출처 자동 재조회 후에도 확인하지 못한 요청이 남아 있다 "
                    f"(HTTP 시도 {verdict.lookup['http_attempts']}회). 출처 연결 회복 후 재검증이 필요하다.")
                if verdict.status == VerificationStatus.NOT_FOUND:
                    # A timed-out fallback search is not evidence of absence.
                    verdict.status = VerificationStatus.UNVERIFIED
                    verdict.levels["level1"] = "UNVERIFIED"
                    verdict.findings = [f for f in verdict.findings if f.type != FindingType.CASE_NOT_FOUND]
                    verdict.findings.append(self._unverified_finding(
                        verdict.citation, verdict.notes[-1], None))
            result.findings.extend(verdict.findings)
            result.source_records.extend(verdict.source_records)
            if verdict.status in (VerificationStatus.UNVERIFIED, VerificationStatus.PARTIALLY_VERIFIED, VerificationStatus.SKIPPED):
                result.unverified_items.append(
                    {
                        "kind": "citation",
                        "citation_id": verdict.citation.citation_id,
                        "type": str(verdict.citation.type),
                        "raw_text": verdict.citation.raw_text,
                        "reason": "; ".join(verdict.notes) or "공식 Source 확인 불가",
                        "source_lookup": verdict.lookup,
                    }
                )
        result.data["verdicts"] = [
            {
                "citation_id": v.citation.citation_id,
                "status": str(v.status),
                # 명세 제4.1장 어휘로 읽을 수 있는 단일 값. 다단계 판정을
                # 대체하지 않고 함께 싣는다. 조회 실패(UNVERIFIABLE)와
                # 원문 미발견(NOT_FOUND)은 끝까지 구분한다.
                "spec_verdict": str(spec_source_verdict(
                    v.levels, v.notes, has_official_record=bool(v.official_record))),
                "levels": v.levels,
                "notes": v.notes,
                "official_record": v.official_record,
                "review": v.review,
                "source_record_ids": [r.source_record_id for r in v.source_records],
                "source_lookup": v.lookup,
            }
            for v in verdicts
        ]
        result.data["citation_count"] = len(citations)
        result.data["verified_count"] = sum(1 for v in verdicts if v.status == VerificationStatus.VERIFIED)
        result.data["unverified_count"] = sum(1 for v in verdicts if v.status == VerificationStatus.UNVERIFIED)
        return result

    # -- 판례 -------------------------------------------------------------
    def verify_case(self, citation: Citation) -> CitationVerdict:
        verdict = CitationVerdict(citation, VerificationStatus.UNVERIFIED)
        case_number = citation.canonical_case_number or citation.case_number
        if not case_number:
            verdict.status = VerificationStatus.SKIPPED
            verdict.notes.append("사건번호를 식별하지 못했다")
            return verdict

        response = self.registry.law.search_case(case_number, court=citation.court)
        if response.source_record:
            verdict.source_records.append(response.source_record)

        # --- Level 1: 존재 여부 ------------------------------------------
        if response.status != AdapterStatus.READY:
            verdict.levels["level1"] = "UNVERIFIED"
            verdict.notes.append(f"공식 Source 조회 불가({response.status}): {response.message}")
            verdict.findings.append(self._unverified_finding(citation, response.message, response.source_record))
            return verdict

        official = self._match_official(citation, response.records)
        if official is None:
            # 재검색: 선고일+사건번호, 법원+사건번호 (제9.3장)
            retry = self._retry_search(citation)
            if retry is not None:
                response, retried_query = retry
                verdict.notes.append(f"재검색으로 확인: {retried_query}")
                if response.source_record:
                    verdict.source_records.append(response.source_record)
                official = self._match_official(citation, response.records)
            if official is None and response.records:
                # 조회는 되었으나 같은 사건번호가 없다. 다른 사건에 붙이지 않는다.
                verdict.notes.append(
                    f"조회 결과 {len(response.records)}건 중 사건번호가 일치하는 기록이 없다"
                )

        if official is None:
            verdict.levels["level1"] = "NOT_FOUND"
            verdict.status = VerificationStatus.NOT_FOUND
            features = {"official_source_absent": True, "deterministic_rule": True, "source_count": 1}
            verdict.findings.append(
                Finding.create(
                    type=FindingType.CASE_NOT_FOUND,
                    status=VerificationStatus.NOT_FOUND,
                    severity=Severity.HIGH,
                    evidence_grade=EvidenceGrade.B,
                    title=f"공식 Source에서 확인되지 않는 판례 인용: {citation.raw_text}",
                    detail=(
                        f"사건번호 {case_number}와 일치하는 기록을 공식 Source에서 확인하지 못했다"
                        "(NOT_FOUND_IN_PRIMARY_SOURCE). 검색 결과에 다른 사건이 포함되어 있더라도 "
                        "사건번호가 다르면 그 사건에 결부시키지 않는다. 미공개 판결이거나 DB 수록 범위 "
                        "밖일 수 있으므로 '존재하지 않는 판례'라고 단정하지 않는다. 원문 확인이 필요하다."
                    ),
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=citation.document_id,
                    block_id=citation.block_id,
                    page=citation.page,
                    span=citation.span,
                    engine=ENGINE_NAME,
                    source_record_ids=[r.source_record_id for r in verdict.source_records],
                    tags=["LEGAL", "CASE"],
                    evidence=[
                        Evidence.create(
                            description="공식 Source 조회 결과 없음",
                            grade=EvidenceGrade.B,
                            document_id=citation.document_id,
                            block_id=citation.block_id,
                            excerpt=citation.raw_text,
                            supports=False,
                        )
                    ],
                )
            )
            return verdict

        verdict.official_record = official
        fetch_detail = getattr(self.registry.law, "fetch_case", None)
        if fetch_detail is not None and not official.get("full_text"):
            detail = fetch_detail(official, constitutional=citation.type == CitationType.CONSTITUTIONAL)
            if detail.source_record:
                verdict.source_records.append(detail.source_record)
            if detail.records:
                official = {**official, **detail.records[0]}
                verdict.official_record = official
        verdict.levels["level1"] = "VERIFIED"

        # --- Level 2: 메타데이터 대조 ------------------------------------
        mismatches = self._compare_metadata(citation, official)
        if mismatches:
            verdict.levels["level2"] = "CONTRADICTED"
            verdict.status = VerificationStatus.CONTRADICTED
            features = {
                "official_source_match": True,
                "metadata_mismatch": True,
                "deterministic_rule": True,
                "source_count": 1,
                "mismatched_fields": [m[0] for m in mismatches],
            }
            verdict.findings.append(
                Finding.create(
                    type=FindingType.CASE_METADATA_MISMATCH,
                    status=VerificationStatus.CONTRADICTED,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.A,
                    title=f"판례 메타데이터 불일치: {citation.raw_text}",
                    detail="; ".join(f"{field}: 문서 '{doc}' / 공식 '{off}'" for field, doc, off in mismatches),
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=citation.document_id,
                    block_id=citation.block_id,
                    page=citation.page,
                    span=citation.span,
                    engine=ENGINE_NAME,
                    source_record_ids=[r.source_record_id for r in verdict.source_records],
                    tags=["LEGAL", "CASE"],
                    evidence=[
                        Evidence.create(
                            description="공식 Source 메타데이터",
                            grade=EvidenceGrade.A,
                            document_id=citation.document_id,
                            block_id=citation.block_id,
                            excerpt=f"{official.get('court')} {official.get('decision_date')} {official.get('case_number')}",
                        )
                    ],
                )
            )
        else:
            verdict.levels["level2"] = "VERIFIED"
            verdict.status = VerificationStatus.VERIFIED

        # --- Level 3: 직접 인용문 대조 -----------------------------------
        if citation.quoted_text:
            official_text = " ".join(str(official.get(key) or "") for key in ("full_text", "holding", "summary"))
            level3, ratio = self._compare_quote(citation.quoted_text, official_text)
            if level3 == "CONTRADICTED" and not official.get("full_text"):
                level3 = "UNVERIFIED"
                verdict.notes.append("판례 전문을 확보하지 못해 직접 인용 불일치를 확정하지 않았다")
            verdict.levels["level3"] = level3
            if level3 == "CONTRADICTED":
                verdict.status = VerificationStatus.CONTRADICTED
                features = {
                    "official_source_match": True,
                    "quote_mismatch": True,
                    "deterministic_rule": True,
                    "quote_similarity": round(ratio, 3),
                }
                verdict.findings.append(
                    Finding.create(
                        type=FindingType.CASE_QUOTE_MISMATCH,
                        status=VerificationStatus.CONTRADICTED,
                        severity=Severity.HIGH,
                        evidence_grade=EvidenceGrade.A,
                        title=f"직접 인용문이 공식 원문과 일치하지 않는다: {citation.raw_text}",
                        detail=(
                            f"문서의 인용문과 공식 판시사항·판결요지의 최대 유사도는 {ratio:.2f}이다. "
                            "따옴표로 표시된 직접 인용은 원문과 일치해야 한다."
                        ),
                        confidence=confidence_score(features),
                        confidence_features=features,
                        document_id=citation.document_id,
                        block_id=citation.block_id,
                        page=citation.page,
                        span=citation.span,
                        engine=ENGINE_NAME,
                        source_record_ids=[r.source_record_id for r in verdict.source_records],
                        tags=["LEGAL", "CASE", "QUOTE"],
                        evidence=[
                            Evidence.create(
                                description="문서의 인용문",
                                grade=EvidenceGrade.A,
                                document_id=citation.document_id,
                                block_id=citation.block_id,
                                excerpt=citation.quoted_text[:300],
                                supports=False,
                            ),
                            Evidence.create(
                                description="공식 판시사항·판결요지",
                                grade=EvidenceGrade.A,
                                excerpt=official_text[:300],
                            ),
                        ],
                    )
                )
            elif level3 == "TRUNCATED":
                verdict.notes.append("인용문이 원문의 일부만 포함한다. 인용 절단 여부는 MM-4 참고신호로 전달된다.")

        # Level 4·5는 LLM 담당. 공식 Source가 있어야만 의미 비교를 수행한다.
        verdict.levels.setdefault("level4", "PENDING_LLM")
        verdict.levels.setdefault("level5", "PENDING_LLM")
        if verdict.status == VerificationStatus.VERIFIED:
            verdict.status = VerificationStatus.PARTIALLY_VERIFIED
        verdict.notes.append("판례 존재·메타데이터 확인과 취지·사건 적용 가능성 검토는 별도이다")
        return verdict

    def _retry_search(self, citation: Citation) -> Optional[Tuple[Any, str]]:
        """Exact 검색 실패 시 선고일·법원을 덧붙여 재검색한다.

        사건번호를 잘라 검색하지 않는다. 공식 Source의 사건 검색은 키워드 검색이므로
        "2023다284910"을 "2023다284"로 자르면 전혀 다른 사건(2024도12341)이 1순위로
        돌아온다. 그 결과를 그대로 받아들이면 존재하지 않는 판례가 "확인됨"이 되고,
        차이는 '선고일 불일치'로 보고되어 이용자를 오도한다.

        재검색 결과도 아래 _match_official()의 사건번호 완전일치 검사를 통과해야 한다.
        """
        queries: List[str] = []
        if citation.decision_date and citation.case_number:
            queries.append(f"{citation.decision_date} {citation.case_number}")
        if citation.court and citation.case_number:
            queries.append(f"{citation.court} {citation.case_number}")
        for query in queries:
            response = self.registry.law.search_case(query, court=citation.court)
            if response.found and self._match_official(citation, response.records) is not None:
                return response, query
        return None

    @staticmethod
    def _match_official(citation: Citation, records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """조회 결과 중 인용 사건번호와 같은 사건만 고른다.

        키워드 검색은 질의와 무관한 사건도 돌려준다. 1순위 결과를 무조건 '공식 기록'으로
        바인딩하면, 가공된 사건번호가 실재하는 다른 판례에 붙어 존재가 확인된 것처럼 된다.
        """
        target = citation.canonical_case_number or citation.case_number
        if not target:
            return None
        for record in records:
            if same_case_number(target, str(record.get("case_number") or "")):
                return record
        return None

    @staticmethod
    def _compare_metadata(citation: Citation, official: Dict[str, Any]) -> List[Tuple[str, str, str]]:
        mismatches: List[Tuple[str, str, str]] = []
        if citation.court and official.get("court"):
            doc_court = citation.court.replace(" ", "")
            off_court = str(official["court"]).replace(" ", "")
            if doc_court not in off_court and off_court not in doc_court:
                mismatches.append(("법원", citation.court, str(official["court"])))
        if citation.decision_date and official.get("decision_date"):
            if citation.decision_date != official["decision_date"]:
                mismatches.append(("선고일", citation.decision_date, str(official["decision_date"])))
        if citation.case_kind and official.get("case_kind"):
            doc_kind = citation.case_kind.replace("선고", "").strip()
            off_kind = str(official["case_kind"]).strip()
            if doc_kind and off_kind and doc_kind not in off_kind and off_kind not in doc_kind:
                mismatches.append(("재판유형", citation.case_kind, off_kind))
        return mismatches

    @staticmethod
    def _compare_quote(quoted: str, official_text: str) -> Tuple[str, float]:
        if not official_text.strip():
            return "UNVERIFIED", 0.0
        exact, ratio = contains_fuzzy(official_text, quoted, threshold=QUOTE_EXACT_THRESHOLD)
        if exact:
            return "VERIFIED", ratio
        fuzzy, ratio2 = contains_fuzzy(official_text, quoted, threshold=QUOTE_FUZZY_THRESHOLD)
        ratio = max(ratio, ratio2)
        if fuzzy:
            return "PARTIALLY_VERIFIED", ratio
        # 인용문이 원문보다 짧고 원문 일부와 높은 유사도를 보이면 절단 인용
        if len(normalize_quote(quoted)) < len(normalize_quote(official_text)) and ratio >= 0.6:
            return "TRUNCATED", ratio
        return "CONTRADICTED", ratio

    # -- 법령 -------------------------------------------------------------
    def verify_statute(self, citation: Citation, *, as_of: Optional[str] = None,
                       incident_date: Optional[str] = None,
                       current_date: Optional[str] = None) -> CitationVerdict:
        verdict = CitationVerdict(citation, VerificationStatus.UNVERIFIED)
        verdict.review = {"dates": date_context(as_of, incident_date, current_date),
                          "advisory_only": True, "applicability": "REVIEW_NEEDED"}
        if not citation.law_name:
            verdict.status = VerificationStatus.SKIPPED
            return verdict
        if any(value is not None and not legal_date(value) for value in (as_of, incident_date, current_date)):
            verdict.levels["temporal"] = "UNVERIFIED"
            verdict.notes.append("유효한 법령 기준일이 필요하다")
            return verdict
        resolver = getattr(self.registry.law, "resolve_statute", None)
        mirror = getattr(self.registry.law, "mirror", None)
        mirrored = mirror.all_versions(citation.law_name, citation.article) if mirror else []
        if resolver is not None and not mirrored:
            return verify_statute_source(self, citation, as_of=as_of,
                                         incident_date=incident_date, current_date=current_date)

        response = self.registry.law.search_law(citation.law_name, article=citation.article, as_of=as_of)
        if response.source_record:
            verdict.source_records.append(response.source_record)

        if response.status != AdapterStatus.READY:
            verdict.notes.append(f"공식 Source 조회 불가({response.status})")
            verdict.findings.append(self._unverified_finding(citation, response.message, response.source_record))
            return verdict

        if not response.records:
            verdict.status = VerificationStatus.NOT_FOUND
            features = {"official_source_absent": True, "deterministic_rule": True}
            verdict.findings.append(
                Finding.create(
                    type=FindingType.LAW_CITATION_ERROR,
                    status=VerificationStatus.NOT_FOUND,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.B,
                    title=f"공식 Source에서 확인되지 않는 법령 인용: {citation.raw_text}",
                    detail=f"법령명 '{citation.law_name}' 조회 결과가 없다. 법령명 표기나 조문 번호 확인이 필요하다.",
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=citation.document_id,
                    block_id=citation.block_id,
                    page=citation.page,
                    span=citation.span,
                    engine=ENGINE_NAME,
                    source_record_ids=[r.source_record_id for r in verdict.source_records],
                    tags=["LEGAL", "STATUTE"],
                )
            )
            return verdict

        official = response.records[0]
        verdict.official_record = official
        verdict.status = VerificationStatus.VERIFIED
        verdict.levels["existence"] = "VERIFIED"

        # 제9.4장 조문 단위 실존 확인.
        # 법령명이 맞아도 그 조문이 실재하는지는 별개다. 확인하지 않으면
        # 가공 조문이 법령만 맞다는 이유로 VERIFIED가 된다.
        if citation.article:
            verdict.levels["article"] = self._verify_article(citation, official, verdict)

        # 제9.4장 기준시점 검증
        if as_of:
            effective_from = official.get("effective_from")
            effective_to = official.get("effective_to")
            mismatch = official.get("as_of_match") is False
            if not mismatch and effective_from and as_of < str(effective_from):
                mismatch = True
            if not mismatch and effective_to and as_of > str(effective_to):
                mismatch = True
            if official.get("temporal_scope") in ("CURRENT_LIST_ONLY", "UNRESOLVED_MIRROR"):
                mismatch = False
                effective_from, effective_to = None, None
            if mismatch:
                verdict.status = VerificationStatus.CONTRADICTED
                verdict.levels["temporal"] = "CONTRADICTED"
                features = {
                    "official_source_match": True,
                    "metadata_mismatch": True,
                    "deterministic_rule": True,
                    "as_of": as_of,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                }
                verdict.findings.append(
                    Finding.create(
                        type=FindingType.TEMPORAL_LAW_MISMATCH,
                        status=VerificationStatus.CONTRADICTED,
                        severity=Severity.HIGH,
                        evidence_grade=EvidenceGrade.A,
                    title=f"조회된 조문의 시행기간과 기준일 불일치: {citation.raw_text}",
                        detail=(
                        f"검토 기준일 {as_of}은 조회된 조문의 시행기간과 일치하지 않는다. "
                            f"조회된 조문 시행기간: {effective_from or '미상'} ~ {effective_to or '현행'}."
                        ),
                        confidence=confidence_score(features),
                        confidence_features=features,
                        document_id=citation.document_id,
                        block_id=citation.block_id,
                        page=citation.page,
                        span=citation.span,
                        engine=ENGINE_NAME,
                        source_record_ids=[r.source_record_id for r in verdict.source_records],
                    tags=["LEGAL", "STATUTE", "TEMPORAL"],
                    advisory_only=True,
                        evidence=[
                            Evidence.create(
                                description="조회된 조문 시행정보",
                                grade=EvidenceGrade.A,
                                excerpt=f"{official.get('law_name')} 제{official.get('article')}조 "
                                f"({effective_from} ~ {effective_to or '현행'})",
                            )
                        ],
                    )
                )
            elif effective_from and (effective_to or official.get("as_of_match") is True):
                verdict.levels["temporal"] = "VERIFIED"
            else:
                verdict.levels["temporal"] = "UNVERIFIED"
                verdict.notes.append("시행기간 또는 기준시점의 적용 버전을 확인하지 못했다")
                if verdict.status == VerificationStatus.VERIFIED:
                    verdict.status = VerificationStatus.PARTIALLY_VERIFIED
        else:
            verdict.levels["temporal"] = "UNVERIFIED"
            verdict.notes.append("법령 적용 기준일이 입력되지 않았다")
            if verdict.status == VerificationStatus.VERIFIED:
                verdict.status = VerificationStatus.PARTIALLY_VERIFIED
        verdict.levels["content"] = "UNVERIFIED"
        verdict.levels["applicability"] = "REVIEW_NEEDED"
        verdict.review["version"] = {key: official.get(key) for key in (
            "law_id", "version_id", "effective_from", "effective_to", "temporal_scope")}
        verdict.review["supplementary_review_needed"] = True
        verdict.review["transitional_review_needed"] = True
        if verdict.levels.get("temporal") == "VERIFIED":
            verdict.levels["temporal"] = "UNVERIFIED"
            verdict.notes.append("기존 Mirror의 기간 정보만으로 조문별 시행일·부칙 적용을 확정하지 않는다")
        if citation.paragraph or citation.item:
            verdict.notes.append("항·호 및 조문 내용의 적용 여부는 별도 검토가 필요하다")
        if verdict.status == VerificationStatus.VERIFIED:
            verdict.status = VerificationStatus.PARTIALLY_VERIFIED
        return verdict

    def _verify_article(self, citation: Citation, official: Dict[str, Any], verdict: "CitationVerdict") -> str:
        """인용된 조문 번호가 해당 법령에 실재하는지 확인한다."""
        articles = official.get("articles")
        if articles is None:
            fetch = getattr(self.registry.law, "fetch_articles", None)
            articles = fetch(official) if fetch is not None else None
            source = official.get("article_source_record")
            if source:
                from datetime import datetime
                source = dict(source)
                source["retrieved_at"] = datetime.fromisoformat(source["retrieved_at"])
                source["status"] = AdapterStatus(source["status"])
                verdict.source_records.append(SourceRecord(**source))

        wanted = canonical_article(citation.article)
        if articles is None:
            # 확인 불가는 '없음'이 아니다. 확인되지 않은 채로 VERIFIED를 주지 않는다.
            verdict.status = VerificationStatus.UNVERIFIED
            verdict.notes.append(f"조문 목록을 조회하지 못해 제{citation.article}조 실존을 확인하지 못했다")
            verdict.findings.append(
                self._unverified_finding(
                    citation,
                    f"법령 '{citation.law_name}'은 확인했으나 제{citation.article}조의 실존은 확인하지 못했다.",
                    verdict.source_records[-1] if verdict.source_records else None,
                )
            )
            return "UNVERIFIED"

        if wanted in {canonical_article(a) for a in articles}:
            return "VERIFIED"

        if official.get("requested_as_of") and official.get("temporal_scope") == "CURRENT_LIST_ONLY":
            verdict.status = VerificationStatus.UNVERIFIED
            verdict.notes.append("현행 조문 목록에 없으나 과거 시행법을 확보하지 못했으므로 조문 부존재를 단정하지 않음")
            return "UNVERIFIED"

        verdict.status = VerificationStatus.NOT_FOUND
        features = {"official_source_match": True, "official_source_absent": True, "deterministic_rule": True}
        verdict.findings.append(
            Finding.create(
                type=FindingType.LAW_CITATION_ERROR,
                status=VerificationStatus.NOT_FOUND,
                severity=Severity.HIGH,
                evidence_grade=EvidenceGrade.A,
                title=f"조회한 법령 버전에서 조문 미확인: {citation.raw_text}",
                detail=(
                    f"'{official.get('law_name')}'은 공식 Source에서 확인되었으나, "
                    f"제{citation.article}조는 수록 조문 {len(articles)}건에 존재하지 않는다. "
                    "조문 번호, 법령 버전 및 적용시점을 확인해야 한다."
                ),
                confidence=confidence_score(features),
                confidence_features=features,
                document_id=citation.document_id,
                block_id=citation.block_id,
                page=citation.page,
                span=citation.span,
                engine=ENGINE_NAME,
                source_record_ids=[r.source_record_id for r in verdict.source_records],
                tags=["LEGAL", "STATUTE", "ARTICLE"],
                evidence=[
                    Evidence.create(
                        description="공식 Source 조문 목록에서 미확인",
                        grade=EvidenceGrade.A,
                        document_id=citation.document_id,
                        block_id=citation.block_id,
                        excerpt=citation.raw_text,
                        supports=False,
                    )
                ],
            )
        )
        return "NOT_FOUND"

    # -- 학술 -------------------------------------------------------------
    def verify_academic(self, citation: Citation) -> CitationVerdict:
        verdict = CitationVerdict(citation, VerificationStatus.UNVERIFIED)
        query = citation.title or citation.doi or citation.raw_text
        responses = self.registry.search_academic(query, doi=citation.doi)
        for response in responses:
            if response.source_record:
                verdict.source_records.append(response.source_record)

        usable = [r for r in responses if r.status == AdapterStatus.READY]
        if not usable:
            verdict.notes.append("학술 Source를 모두 사용할 수 없다")
            verdict.findings.append(
                self._unverified_finding(citation, "학술 Source 사용 불가", responses[0].source_record if responses else None)
            )
            return verdict

        matches: List[Dict[str, Any]] = []
        for response in usable:
            for record in response.records:
                if citation.doi and record.get("doi") and citation.doi.lower() == str(record["doi"]).lower():
                    matches.append(record)
                elif citation.title and record.get("title") and similarity(citation.title, str(record["title"])) >= 0.85:
                    matches.append(record)

        if not matches:
            verdict.status = VerificationStatus.NOT_FOUND
            features = {"official_source_absent": True, "source_count": len(usable)}
            verdict.findings.append(
                Finding.create(
                    type=FindingType.ACADEMIC_CITATION_ERROR,
                    status=VerificationStatus.NOT_FOUND,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.B,
                    title=f"학술자료를 확인하지 못했다: {citation.title or citation.doi or citation.raw_text}",
                    detail=(
                        f"{len(usable)}개 Source에서 일치하는 문헌을 찾지 못했다. "
                        "미색인 문헌일 수 있으므로 존재하지 않는다고 단정하지 않는다."
                    ),
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=citation.document_id,
                    block_id=citation.block_id,
                    page=citation.page,
                    span=citation.span,
                    engine=ENGINE_NAME,
                    source_record_ids=[r.source_record_id for r in verdict.source_records],
                    tags=["ACADEMIC"],
                )
            )
            return verdict

        best = matches[0]
        verdict.official_record = best
        mismatches: List[str] = []
        if citation.year and best.get("year") and int(citation.year) != int(best["year"]):
            mismatches.append(f"발행연도: 문서 {citation.year} / Source {best['year']}")
        if citation.authors and best.get("authors"):
            doc_authors = {a.replace(" ", "") for a in citation.authors}
            src_authors = {str(a).replace(" ", "") for a in best["authors"] if a}
            if doc_authors and src_authors and not (doc_authors & src_authors):
                mismatches.append(f"저자: 문서 {', '.join(citation.authors)} / Source {', '.join(map(str, best['authors'][:3]))}")

        if mismatches:
            verdict.status = VerificationStatus.CONTRADICTED
            features = {"metadata_mismatch": True, "source_count": len(usable), "deterministic_rule": True}
            verdict.findings.append(
                Finding.create(
                    type=FindingType.ACADEMIC_CITATION_ERROR,
                    status=VerificationStatus.CONTRADICTED,
                    severity=Severity.MEDIUM,
                    evidence_grade=EvidenceGrade.B,
                    title=f"학술자료 서지사항이 일치하지 않는다: {citation.title or citation.doi}",
                    detail="; ".join(mismatches),
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=citation.document_id,
                    block_id=citation.block_id,
                    page=citation.page,
                    span=citation.span,
                    engine=ENGINE_NAME,
                    source_record_ids=[r.source_record_id for r in verdict.source_records],
                    tags=["ACADEMIC"],
                )
            )
        else:
            verdict.status = VerificationStatus.VERIFIED
        return verdict

    # -- 공통 -------------------------------------------------------------
    @staticmethod
    def _unverified_finding(citation: Citation, message: str, record: Optional[SourceRecord]) -> Finding:
        features = {"heuristic_only": False, "source_count": 0}
        return Finding.create(
            type=FindingType.CASE_NOT_FOUND if citation.type == CitationType.CASE else FindingType.LAW_CITATION_ERROR,
            status=VerificationStatus.UNVERIFIED,
            severity=Severity.INFO,
            evidence_grade=EvidenceGrade.U,
            title=f"검증하지 못한 인용: {citation.raw_text}",
            detail=(
                f"{message} 공식 Source를 사용할 수 없어 이 항목은 미검증으로 남는다. "
                "미검증은 오류가 없다는 의미가 아니다."
            ),
            confidence=confidence_score(features),
            confidence_features=features,
            document_id=citation.document_id,
            block_id=citation.block_id,
            page=citation.page,
            span=citation.span,
            engine=ENGINE_NAME,
            source_record_ids=[record.source_record_id] if record else [],
            tags=["UNVERIFIED"],
        )
