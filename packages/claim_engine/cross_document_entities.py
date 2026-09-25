"""서면 간 엔티티 교차 일치성 검증기 (XDOC).

소장, 준비서면, 답변서 등 본안 서면의 주장과
첨부된 증거 서류(근로계약서, 판정서, 출퇴근기록부 등) 간의
날짜, 수치, 인적사항 엔티티를 교차 대조하여 불일치(XDOC)를 정밀 탐지한다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.common.confidence import score as confidence_score
from packages.document_engine.reading_text import build_reading_text

ENGINE_NAME = "claim_engine.cross_document_entities"

# 날짜 패턴 (YYYY. M. D. 또는 YYYY-MM-DD 또는 YYYY년 M월 D일)
_DATE_PATTERNS = [
    re.compile(r"(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})(?:일)?"),
]

# 엔티티 키워드 패턴 목록 (양방향 일반 규칙)
ENTITY_PATTERNS: Dict[str, List[re.Pattern]] = {
    "입사일": [
        re.compile(r"(?:입사(?:일|한)?|채용(?:일|된)?|근로계약\s*체결일|근무\s*시작일|근무기간)[^.\n\d]{0,20}(\d{4}[.\-/년\s]+\d{1,2}[.\-/월\s]+\d{1,2}(?:일|\.)?)"),
        re.compile(r"(\d{4}[.\-/년\s]+\d{1,2}[.\-/월\s]+\d{1,2}(?:일|\.)?)[^\n]{0,30}?(?:입사|채용|근무를?\s*시작|근로계약\s*체결)"),
    ],
    "퇴사일": [
        re.compile(r"(?:퇴사(?:일|한)?|해고(?:일|된)?|근로관계\s*종료일)[^.\n\d]{0,20}(\d{4}[.\-/년\s]+\d{1,2}[.\-/월\s]+\d{1,2}(?:일|\.)?)"),
        re.compile(r"(\d{4}[.\-/년\s]+\d{1,2}[.\-/월\s]+\d{1,2}(?:일|\.)?)[^\n]{0,30}?(?:퇴사|해고|근로관계\s*(?:가\s*)?종료)"),
    ],
    "판정일": [
        re.compile(r"(?:중앙|지방|서울|경기)?\s*(?:노동위원회|지노위|중노위|위원회)?\s*(?:재결|처분|판정|의결|결정)[^.\n\d]{0,20}(\d{4}[.\-/년\s]+\d{1,2}[.\-/월\s]+\d{1,2}(?:일|\.)?)"),
        re.compile(r"(\d{4}[.\-/년\s]+\d{1,2}[.\-/월\s]+\d{1,2}(?:일|\.)?)[^\n]{0,30}?(?:판정|재결|의결)"),
    ],
    "연장근로시간": [
        re.compile(r"(?:총\s*)?(?:연장|초과|휴일)\s*근로(?:시간)?\s*(?:합계|총|총합)?[^.\n\d]{0,10}(\d+)\s*(?:시간|H)"),
    ],
}


def _norm_date(date_str: str) -> Optional[str]:
    """날짜 문자열을 YYYY-MM-DD 형식으로 정규화한다."""
    if not date_str:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(date_str)
        if m:
            y, mth, d = m.groups()
            try:
                return date(int(y), int(mth), int(d)).isoformat()
            except ValueError:
                return None
    return None


def _get_doc_text(doc: NormalizedDocument) -> str:
    """NormalizedDocument에서 텍스트를 안전하게 추출한다."""
    return build_reading_text(doc).text


def extract_document_entities(doc: NormalizedDocument) -> Dict[str, List[Dict[str, Any]]]:
    """문서 텍스트에서 주요 사실관계 엔티티를 추출한다."""
    entities: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    text = _get_doc_text(doc)
    filename = doc.filename or doc.document_id

    # 출퇴근기록부/근무시간 합계 특별 추출 (예: 30 + 28 + 30 = 88)
    time_sum_match = re.search(r"(\d+)\s*\+\s*(\d+)(?:\s*\+\s*(\d+))?\s*=\s*(\d+)", text)
    if time_sum_match and re.search(r"(?:연장|초과|휴일)\s*근로", text[max(0, time_sum_match.start() - 40):time_sum_match.end() + 20]):
        calc_total = int(time_sum_match.group(4) or time_sum_match.group(3) or time_sum_match.group(2))
        entities["연장근로시간"].append({
            "raw": f"{calc_total}시간 (산출합계)",
            "norm": calc_total,
            "span": (time_sum_match.start(), time_sum_match.end()),
            "context": time_sum_match.group(0),
            "document_id": doc.document_id,
            "filename": filename,
        })

    for key, pat_list in ENTITY_PATTERNS.items():
        for pat in pat_list:
            for match in pat.finditer(text):
                val_raw = match.group(1).strip()
                if "일" in key:
                    val_norm = _norm_date(val_raw)
                else:
                    # 덧셈식의 피연산자인 경우 건너뜀
                    after_match = text[match.end():match.end() + 10]
                    if "+" in after_match:
                        continue
                    try:
                        val_norm = int(val_raw)
                    except ValueError:
                        val_norm = val_raw

                if val_norm is not None:
                    # 중복 엔티티 방지 (동일 norm)
                    if any(e["norm"] == val_norm for e in entities[key]):
                        continue
                    start = max(0, match.start() - 40)
                    end = min(len(text), match.end() + 40)
                    entities[key].append({
                        "raw": val_raw,
                        "norm": val_norm,
                        "span": (match.start(), match.end()),
                        "context": text[start:end].replace("\n", " ").strip(),
                        "document_id": doc.document_id,
                        "filename": filename,
                    })

    return entities


def verify_cross_document_entities(docs: List[NormalizedDocument]) -> List[Finding]:
    """사건 내 전체 문서들 간의 엔티티 불일치(XDOC)를 검증하여 Finding을 생성한다."""
    findings: List[Finding] = []
    if len(docs) < 2:
        return findings

    # 각 문서별 엔티티 수집
    doc_entity_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for doc in docs:
        doc_entity_map[doc.document_id] = extract_document_entities(doc)

    # 엔티티 종류별로 문서 간 값 대조
    entity_keys = list(ENTITY_PATTERNS.keys())

    for key in entity_keys:
        # 모든 문서에서 발견된 해당 엔티티 값들 취합
        all_values: List[Dict[str, Any]] = []
        for doc_id, e_dict in doc_entity_map.items():
            for item in e_dict.get(key, []):
                all_values.append(item)

        if not all_values:
            continue

        # 고유 정규화 값들 확인
        unique_norms = set(item["norm"] for item in all_values)
        if len(unique_norms) > 1:
            # 서로 다른 문서 사이에 불일치가 있는지 검사
            # (동일 문서 내 오타는 별도 처리되거나 여기서 포괄)
            by_doc = defaultdict(list)
            for item in all_values:
                by_doc[item["document_id"]].append(item)

            if len(by_doc) >= 2:
                value_sets = [{item["norm"] for item in items} for items in by_doc.values()]
                if all(values == value_sets[0] for values in value_sets[1:]):
                    continue
                # 불일치 발생!
                docs_involved = list(by_doc.keys())
                primary_doc_id = docs_involved[0]
                
                # 불일치 상세 내역 문자열 생성
                details_list = []
                for doc_id, items in by_doc.items():
                    fn = items[0]["filename"]
                    vals = ", ".join(f"'{it['raw']}'(맥락: {it['context'][:30]})" for it in items)
                    details_list.append(f"[{fn}] {vals}")

                detail_msg = (f"문서 간 '{key}' 기재가 상이합니다: " + " vs ".join(details_list)
                              + ". 같은 당사자·사건·기간의 사실인지는 확인되지 않았으므로 모순을 확정하지 않습니다.")
                
                features = {
                    "cross_document_inconsistency": True,
                    "entity_type": key,
                    "defect_code": "XDOC",
                    "same_subject_confirmed": False,
                    "documents": [items[0]["filename"] for items in by_doc.values()],
                }

                evidence_items = []
                for items in by_doc.values():
                    it = items[0]
                    evidence_items.append(
                        Evidence.create(
                            description=f"{it['filename']} 기재",
                            grade=EvidenceGrade.C,
                            document_id=it["document_id"],
                            excerpt=it["context"][:300],
                            supports=False,
                        )
                    )

                findings.append(
                    Finding.create(
                        type=FindingType.CROSS_DOCUMENT_CONTRADICTION,
                        status=VerificationStatus.SUSPICIOUS,
                        severity=Severity.MEDIUM,
                        evidence_grade=EvidenceGrade.C,
                        advisory_only=True,
                        title=f"문서 간 기재 차이 확인 필요(XDOC): '{key}' 상이",
                        detail=detail_msg,
                        confidence=confidence_score(features),
                        confidence_features=features,
                        document_id=primary_doc_id,
                        engine=ENGINE_NAME,
                        tags=["FACT", "CROSS_DOCUMENT", "XDOC", key],
                        evidence=evidence_items,
                    )
                )

    return findings
