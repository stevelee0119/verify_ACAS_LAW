"""F2 통합 검토 항목(ReviewItem) 생성 및 단일 판정 모듈.

통합 '검토 항목' 탭(Review Items)을 위한 단일 판정 객체(ReviewItem)를 구축합니다.
- T1 단일 판정: 인용 하나에 검토 행 하나, 행 심각도는 연결된 Finding 중 최고 심각도(순수 파생).
- T2 손실 없음: AI·보안 탭 배정이 아닌 모든 Finding을 빠짐없이 검토 행에 연결.
- T4 AI 탭 배타성: 검토 행에는 AI·보안 유형 Finding을 절대 포함하지 않음.
- 근거 사다리 2축 분리: 공식 확인(official_status)과 참고자료 지지(reference_status) 독립 분리.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from packages.common.enums import (
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.finding_category_map import (
    FINDING_CATEGORY_MAP,
    ScreenCategory,
    ScreenTab,
    get_finding_category,
    get_finding_tab,
    is_review_item_finding,
)
from packages.common.schemas import (
    Finding,
    OfficialConfirmationStatus,
    ReferenceSupportStatus,
    ReviewItem,
    ReviewItemKind,
)


# 사람 말(Human-Readable) 변환표 (19b 설계 2.5절 반영)
HUMAN_READABLE_UNVERIFIED_REASONS: Dict[str, str] = {
    "Multiple versions share the requested effective boundary": "해당 조문의 시행일자 기준 복수 개정판이 존재하여 특정 판본 확인 필요",
    "NO_READABLE_DRIVE_REFERENCE": "판독 가능한 Drive 참고자료 문서 없음",
    "RELEVANT_REFERENCES_NOT_FULLY_READ": "참고자료 분량 초과로 일부 문서 미대조",
    "NO_TEXT_AFTER_REMOVING_INSTRUCTIONS": "지시문 제거 후 분석 대상 본문 텍스트 부족",
    "DOCUMENT_UNREADABLE": "서면 문서 텍스트 정규화 실패로 판독 불가",
    "REFERENCE_LIBRARY_UNAVAILABLE": "참고자료 라이브러리 색인 준비 미완료",
    "BUDGET_ADMISSION_FAILED": "요청 예산 한도 도달로 모델 대조 미실시",
    "MODEL_NOT_AVAILABLE_OR_QUICK_PROFILE": "빠른 검토 프로필 설정 또는 모델 가용성 부족",
    "document_truncated": "서면 길이 한도 초과로 일부 구간 수동 검토 권장",
}


def humanize_unverified_reason(reason: str) -> str:
    """내부 엔진의 미확인 사유 코드를 사람이 읽기 편한 안내 문구로 변환합니다."""
    if not reason:
        return "미확인 사유 미기재"
    if reason in HUMAN_READABLE_UNVERIFIED_REASONS:
        return HUMAN_READABLE_UNVERIFIED_REASONS[reason]
    for key, val in HUMAN_READABLE_UNVERIFIED_REASONS.items():
        if key in reason:
            return val
    return f"미확인 사유: {reason}"


def derive_item_severity(linked_findings: List[Finding]) -> Severity:
    """연결된 Finding들의 심각도 중 가장 높은 순위(rank)를 순수 파생하여 반환합니다.
    
    연결된 Finding이 없는 경우 기본값은 Severity.INFO입니다(T1).
    """
    if not linked_findings:
        return Severity.INFO
    return max(linked_findings, key=lambda f: f.severity.rank).severity


def _kind_for_finding_type(ft: FindingType) -> ReviewItemKind:
    """FindingType에 따른 ReviewItemKind를 결정합니다."""
    cat = get_finding_category(ft)
    if cat == ScreenCategory.LEGAL_CITATION:
        return ReviewItemKind.CITATION
    if cat == ScreenCategory.TEMPORAL_TIMELINE:
        return ReviewItemKind.TEMPORAL
    if cat == ScreenCategory.PROCESSING_QUALITY:
        if ft == FindingType.PARSE_ERROR:
            return ReviewItemKind.UNVERIFIED_SCOPE
        return ReviewItemKind.PROCESSING_QUALITY
    if cat in (ScreenCategory.FACT_DISCREPANCY, ScreenCategory.MM4_ADVISORY):
        return ReviewItemKind.FACT
    return ReviewItemKind.FACT


def build_document_review_items(
    doc_result: Any,
    norm_doc: Optional[Any] = None,
    context: Optional[Any] = None,
) -> List[ReviewItem]:
    """단일 문서 검증 결과로부터 통합 검토 항목(review_items) 목록을 생성합니다.

    1. 인용 행(CITATION):
       - 문서의 인용 목록을 기준으로 인용당 정확히 1개의 검토 행을 생성(T1).
       - 해당 인용에 연관된 검토 대상 Finding들을 연결하고 최고 심각도를 계산(T1).
       - AI·보안 탭 소속 Finding은 배타적으로 제외(T4).
    2. 미연결 검토 Finding 행(FACT, TEMPORAL, PROCESSING_QUALITY 등):
       - 인용 행에 연결되지 않은 모든 검토 대상 Finding을 누락 없이 개별 행으로 생성(T2).
    """
    doc_id = getattr(doc_result, "document_id", "doc_unknown")
    all_findings: List[Finding] = getattr(doc_result, "findings", []) or []

    # 1. 검토 대상 Finding 필터링 (AI·보안 유형 원천 배제, T4 만족)
    review_findings: List[Finding] = [
        f for f in all_findings if is_review_item_finding(f.type)
    ]
    finding_by_id: Dict[str, Finding] = {f.finding_id: f for f in review_findings}

    # 2. Finding과 Citation 간의 매핑 인덱스 구축
    findings_by_citation: Dict[str, List[Finding]] = {}
    for f in review_findings:
        features = f.confidence_features or {}
        matched_cids: Set[str] = set()

        cid = features.get("citation_id")
        if cid and isinstance(cid, str):
            matched_cids.add(cid)

        cids = features.get("citation_ids")
        if isinstance(cids, list):
            for c_item in cids:
                if isinstance(c_item, str):
                    matched_cids.add(c_item)

        if f.tags:
            for tag in f.tags:
                tag_str = str(tag)
                if tag_str.startswith("cit_") or tag_str.startswith("CIT_"):
                    matched_cids.add(tag_str)

        for c_id in matched_cids:
            findings_by_citation.setdefault(c_id, []).append(f)

    # 3. 보조 테이블 조회 (ai_hallucination_table, legal_verdicts)
    hallucination_by_cid: Dict[str, Dict[str, Any]] = {}
    for row in getattr(doc_result, "ai_hallucination_table", []) or []:
        cid = row.get("citation_id") if isinstance(row, dict) else getattr(row, "citation_id", None)
        if cid:
            row_dict = row if isinstance(row, dict) else row.to_dict()
            hallucination_by_cid[cid] = row_dict

    verdicts_by_cid: Dict[str, Dict[str, Any]] = {}
    engine_data = getattr(doc_result, "engine_data", {}) or {}
    for v in engine_data.get("legal_verdicts", []) or []:
        cid = v.get("citation_id")
        if cid:
            verdicts_by_cid[cid] = v

    # 4. 인용 행 생성 (T1 단일 판정: 1 인용 = 1 행)
    items: List[ReviewItem] = []
    assigned_finding_ids: Set[str] = set()
    seen_citation_ids: Set[str] = set()
    seen_item_ids: Set[str] = set()

    citations = getattr(doc_result, "citations", []) or []
    for cit in citations:
        cid = cit.citation_id if hasattr(cit, "citation_id") else cit.get("citation_id")
        if not cid or cid in seen_citation_ids:
            continue
        seen_citation_ids.add(cid)

        # 연관 Finding 목록 (중복 제거 및 AI·보안 배제 검증)
        candidate_findings = findings_by_citation.get(cid, [])
        unique_findings: List[Finding] = []
        for f in candidate_findings:
            if f.finding_id in finding_by_id and f not in unique_findings:
                unique_findings.append(f)

        linked_fids = [f.finding_id for f in unique_findings]
        assigned_finding_ids.update(linked_fids)

        # 순수 파생 심각도 (T1)
        severity = derive_item_severity(unique_findings)

        h_row = hallucination_by_cid.get(cid, {})
        v_row = verdicts_by_cid.get(cid, {})

        # 공식 DB 확인 상태(official_status) 결정
        v_status = str(v_row.get("status", "")).upper()
        if v_status in ("CONFIRMED", "MATCH", "VERIFIED"):
            off_status = OfficialConfirmationStatus.OFFICIAL_CONFIRMED
        elif v_status == "NOT_FOUND":
            off_status = OfficialConfirmationStatus.OFFICIAL_NOT_FOUND
        elif v_status == "UNVERIFIED":
            off_status = OfficialConfirmationStatus.UNVERIFIED_SCOPE
        else:
            auth_exists = h_row.get("authority_exists")
            if auth_exists is True:
                off_status = OfficialConfirmationStatus.OFFICIAL_CONFIRMED
            elif auth_exists is False:
                off_status = OfficialConfirmationStatus.OFFICIAL_NOT_FOUND
            else:
                off_status = OfficialConfirmationStatus.NOT_ASSESSED

        # 참고자료 지지 상태(reference_status) 및 출처 반영 (F3)
        rag_data = getattr(doc_result, "engine_data", {}).get("rag", {})
        drive_used = rag_data.get("drive_used", False)
        ref_matches = rag_data.get("reference_matches", {})
        issues = rag_data.get("issues", [])

        # 인용과 연결된 Claim 확인: Claim.citation_ids에 cid가 포함된 주장들
        claims_list = getattr(doc_result, "claims", []) or []
        cit_claim_ids = {
            getattr(c, "claim_id", None) or (c.get("claim_id") if isinstance(c, dict) else None)
            for c in claims_list
            if cid in (getattr(c, "citation_ids", None) or (c.get("citation_ids") if isinstance(c, dict) else []) or [])
        }
        # 또는 관찰의견 이슈 중 claim_ids 매칭
        linked_issues = [
            issue for issue in issues
            if any(claim_id in cit_claim_ids for claim_id in issue.get("claim_ids", []))
        ]

        has_contradicted = any(issue.get("relationship") == "CONTRADICTS" for issue in linked_issues)
        match_info = ref_matches.get(cid)

        # 상태 우선순위: CONTRADICTED > SUPPORTED > NOT_MENTIONED > NOT_CHECKED
        if has_contradicted:
            ref_status = ReferenceSupportStatus.CONTRADICTED
        elif match_info and match_info.get("status") == "SUPPORTED":
            ref_status = ReferenceSupportStatus.SUPPORTED
        elif drive_used or rag_data.get("sources"):
            ref_status = ReferenceSupportStatus.NOT_MENTIONED
        else:
            ref_status = ReferenceSupportStatus.NOT_CHECKED

        # 판정 라벨(verdict_label)
        verdict_label = h_row.get("validity_verdict")
        if not verdict_label:
            if off_status == OfficialConfirmationStatus.OFFICIAL_CONFIRMED:
                verdict_label = "공식 원문 일치"
            elif off_status == OfficialConfirmationStatus.OFFICIAL_NOT_FOUND:
                verdict_label = "공식 DB 미확인"
            elif off_status == OfficialConfirmationStatus.UNVERIFIED_SCOPE:
                verdict_label = "미확인 범위"
            else:
                verdict_label = "검토 필요" if linked_fids else "검토 완료"

        # 주장 텍스트(claim_text)
        claim_text = h_row.get("claim_text")
        if not claim_text:
            raw = getattr(cit, "raw_text", None) or (cit.get("raw_text") if isinstance(cit, dict) else "")
            claim_text = f"{raw}에 기반한 법률적 주장" if raw else "인용 근거 주장"

        # 인용 대상 권위(cited_authority)
        cited_authority = h_row.get("cited_authority")
        if not cited_authority:
            cited_authority = (
                getattr(cit, "canonical_case_number", None)
                or getattr(cit, "case_number", None)
                or getattr(cit, "raw_text", None)
                or (cit.get("raw_text") if isinstance(cit, dict) else None)
            )

        # 위치 정보(location)
        location: Optional[Dict[str, Any]] = None
        if h_row.get("location"):
            location = {"display": h_row["location"]}
        else:
            page = getattr(cit, "page", None) or (cit.get("page") if isinstance(cit, dict) else None)
            span = getattr(cit, "span", None) or (cit.get("span") if isinstance(cit, dict) else None)
            if page is not None or span is not None:
                location = {"page": page, "span": span}

        # 근거 출처 목록(evidence_sources)
        evidence_sources: List[str] = []
        if v_row.get("source"):
            evidence_sources.append(str(v_row["source"]))
        if ref_status == ReferenceSupportStatus.SUPPORTED and match_info:
            file_id = match_info.get("file_id") or ""
            source_title = match_info.get("source_title") or "참고자료"
            evidence_sources.append(f"참고자료(공식 법령·판례 아님): {source_title} ({file_id})")

        reasoning = h_row.get("reasoning_sections")
        counteraction = h_row.get("recommended_counteraction")

        item_id = f"{doc_id}_CITATION_{cid}"
        seen_item_ids.add(item_id)

        item = ReviewItem(
            item_id=item_id,
            kind=ReviewItemKind.CITATION,
            document_id=doc_id,
            claim_text=claim_text,
            official_status=off_status,
            reference_status=ref_status,
            verdict_label=verdict_label,
            severity=severity,
            location=location,
            cited_authority=cited_authority,
            evidence_sources=evidence_sources,
            finding_ids=linked_fids,
            citation_id=cid,
            advisory_only=False,
            reasoning_sections=reasoning,
            counteraction=counteraction,
        )
        items.append(item)

    # 5. 인용 행에 배정되지 않은 남은 검토 Finding 행 생성 (T2 손실 없음 보장)
    unassigned_findings = [
        f for f in review_findings if f.finding_id not in assigned_finding_ids
    ]

    for f in unassigned_findings:
        fid = f.finding_id
        item_id = f"{doc_id}_FINDING_{fid}"
        if item_id in seen_item_ids:
            idx = 1
            while f"{item_id}_{idx}" in seen_item_ids:
                idx += 1
            item_id = f"{item_id}_{idx}"
        seen_item_ids.add(item_id)

        kind = _kind_for_finding_type(f.type)
        verdict_label = f.title or str(f.type)
        claim_text = f.detail or f.title or "검토 필요 항목"

        # 공식 상태 결정
        if f.status == VerificationStatus.UNVERIFIED or kind == ReviewItemKind.UNVERIFIED_SCOPE:
            off_status = OfficialConfirmationStatus.UNVERIFIED_SCOPE
            # 사유 변환 적용
            reason_raw = (f.confidence_features or {}).get("reason") or f.title
            if reason_raw:
                verdict_label = humanize_unverified_reason(str(reason_raw))
        else:
            off_status = OfficialConfirmationStatus.NOT_ASSESSED

        ref_status = ReferenceSupportStatus.NOT_CHECKED

        # 위치 정보
        loc: Optional[Dict[str, Any]] = None
        if f.page is not None or f.span is not None:
            loc = {"page": f.page, "span": f.span}

        item = ReviewItem(
            item_id=item_id,
            kind=kind,
            document_id=doc_id,
            claim_text=claim_text,
            official_status=off_status,
            reference_status=ref_status,
            verdict_label=verdict_label,
            severity=f.severity,  # 순수 파생 (단일 finding이므로 동일, T1)
            location=loc,
            cited_authority=(f.confidence_features or {}).get("cited_authority"),
            evidence_sources=[],
            finding_ids=[fid],
            citation_id=None,  # 인용 행이 아니므로 None 유지 (T1 citation_id 중복 방지)
            advisory_only=f.advisory_only,
            reasoning_sections=None,
            counteraction=getattr(f, "recommendation", None),
        )
        items.append(item)
        assigned_finding_ids.add(fid)

    return items
