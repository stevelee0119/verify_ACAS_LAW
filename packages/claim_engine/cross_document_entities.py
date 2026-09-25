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


# --- 당사자·사건 바인딩 -----------------------------------------------------------------------------
# 사실의 주체가 될 수 있는 당사자 지위. 복수형('원고들')·번호('원고 1')는 누구인지 특정되지 않으므로 바인딩하지 않는다.
PARTY_ROLE_RE = re.compile(
    r"(?P<role>피고인|피해자|피청구인|피신청인|청구인|신청인|채권자|채무자|근로자|사용자|고소인|참가인|원고|피고)"
    r"(?P<plural>들|\s*\d+\s*[.)]?|\s*등)?(?P<particle>께서|의|은|는|이|가|측|에게)?")
SUBJECT_PARTICLES = {"께서", "은", "는", "이", "가"}
# 당사자에 묶이는 사실(누구의 입사일인가). 판정일처럼 사건·기관에 묶이는 사실은 판정 기관까지 같아야 같은 사실이므로
# 승격하지 않고, 연장근로시간은 기간(어느 달·어느 기간)이 묶여야 하므로 승격하지 않는다.
PARTY_BOUND_KEYS = {"입사일", "퇴사일"}
_SENTENCE_END_RE = re.compile(r"(?:[다요음함임]\.|[!?。])(?=\s|$)|\n")


def _sentence_bounds(text: str, start: int, end: int) -> Tuple[int, int]:
    """start~end를 포함하는 문장의 범위. 날짜의 마침표('2021. 3. 4.')로 문장을 끊지 않도록 종결 어미 뒤 마침표만 본다."""
    left = 0
    for m in _SENTENCE_END_RE.finditer(text, 0, start):
        left = m.end()
    m = _SENTENCE_END_RE.search(text, end)
    return left, (m.end() if m else len(text))


def bind_subject(sentence: str, position: int) -> Optional[str]:
    """문장 안에서 position(사실 표기 위치)의 주체 당사자. 특정할 수 없으면 None.

    1) 사실 바로 앞(15자 안)의 소유격 '원고의 입사일' → 원고
    2) 주격·보조사로 표시된 당사자가 문장에 하나뿐이면 그 당사자('원고는 … 피고 회사에 입사')
    3) 문장에 나온 당사자가 하나뿐이고 '에게'로 표시되지 않았으면 그 당사자('원고 입사일: …')
    """
    mentions = [m for m in PARTY_ROLE_RE.finditer(sentence) if not m.group("plural")]
    before = [m for m in mentions if m.start() < position]
    possessive = [m for m in before if m.group("particle") == "의" and position - m.end() <= 15]
    if possessive:
        return possessive[-1].group("role")
    subjects = {m.group("role") for m in mentions if m.group("particle") in SUBJECT_PARTICLES}
    if len(subjects) == 1:
        return subjects.pop()
    roles = {m.group("role") for m in mentions if m.group("particle") != "에게"}
    if len(roles) == 1 and not subjects:
        return roles.pop()
    return None


def _annotate(doc: NormalizedDocument, entities: Dict[str, List[Dict[str, Any]]]) -> None:
    """엔티티마다 주체 당사자(subject)와 양태(modality: 확정/예정/가정/상대방 주장)를 붙인다."""
    from .fact_store import modality

    text = _get_doc_text(doc)
    for items in entities.values():
        for item in items:
            start, end = item["span"]
            left, right = _sentence_bounds(text, start, end)
            sentence = text[left:right]
            item["subject"] = bind_subject(sentence, start - left)
            item["modality"] = modality(sentence, end - left)


def _xdoc_finding(key: str, by_doc: Dict[str, List[Dict[str, Any]]], *, bound: Optional[Dict[str, Any]] = None
                  ) -> Finding:
    """문서 간 차이 finding. bound가 있으면 같은 사건·같은 당사자의 확정 서술 모순(CONTRADICTED, B)."""
    details_list = []
    for items in by_doc.values():
        fn = items[0]["filename"]
        vals = ", ".join(f"'{it['raw']}'(맥락: {it['context'][:30]})" for it in items)
        details_list.append(f"[{fn}] {vals}")
    features: Dict[str, Any] = {
        "cross_document_inconsistency": True,
        "entity_type": key,
        "defect_code": "XDOC",
        "same_subject_confirmed": bool(bound),
        "documents": [items[0]["filename"] for items in by_doc.values()],
    }
    if bound:
        features.update(bound)
        grade, status = EvidenceGrade.B, VerificationStatus.CONTRADICTED
        title = f"문서 간 사실 모순(XDOC): {bound['subject']}의 '{key}' 기재가 서로 다르다"
        detail = (f"같은 사건(사건번호 {', '.join(bound['shared_case_numbers'])})의 문서들이 같은 당사자({bound['subject']})의 "
                  f"'{key}'를 서로 다르게 확정적으로 적었다: " + " vs ".join(details_list)
                  + ". 상대방 주장·가정적 서술·예정 사항은 비교에서 뺐다. 어느 쪽이 맞는지는 원본 증거로 확인해야 한다.")
    else:
        grade, status = EvidenceGrade.C, VerificationStatus.SUSPICIOUS
        title = f"문서 간 기재 차이 확인 필요(XDOC): '{key}' 상이"
        detail = (f"문서 간 '{key}' 기재가 상이합니다: " + " vs ".join(details_list)
                  + ". 같은 당사자·사건·기간의 사실인지는 확인되지 않았으므로 모순을 확정하지 않습니다.")
    evidence_items = [Evidence.create(description=f"{items[0]['filename']} 기재", grade=grade,
                                      document_id=items[0]["document_id"], excerpt=items[0]["context"][:300],
                                      supports=False) for items in by_doc.values()]
    return Finding.create(
        type=FindingType.CROSS_DOCUMENT_CONTRADICTION, status=status,
        severity=Severity.HIGH if bound else Severity.MEDIUM, evidence_grade=grade, advisory_only=not bound,
        title=title, detail=detail, confidence=confidence_score(features), confidence_features=features,
        document_id=next(iter(by_doc)), engine=ENGINE_NAME, tags=["FACT", "CROSS_DOCUMENT", "XDOC", key],
        evidence=evidence_items)


def _group_by_doc(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_doc[item["document_id"]].append(item)
    return by_doc


def _differs(by_doc: Dict[str, List[Dict[str, Any]]]) -> bool:
    if len(by_doc) < 2:
        return False
    value_sets = [{item["norm"] for item in items} for items in by_doc.values()]
    return not all(values == value_sets[0] for values in value_sets[1:])


def verify_cross_document_entities(docs: List[NormalizedDocument]) -> List[Finding]:
    """사건 내 문서들 간의 엔티티 불일치(XDOC)를 검증한다.

    - 비교는 같은 사건 묶음(fact_store.case_groups: 자기 사건번호·당사자 이름) 안에서만 한다.
    - 상대방 주장·가정적 항변('설령 ~라 하더라도')·예정 사항에 든 값은 비교에서 뺀다(확정 서술만 비교).
    - 같은 사건번호를 공유하는 문서들이 같은 당사자의 당사자 귀속 사실(입사일·퇴사일)을 서로 다른 단일 값으로 확정
      서술하면 CONTRADICTED(B)로 올린다. 그 밖의 차이는 확인이 필요한 참고(C, advisory)로 둔다.
    """
    from .fact_store import CONFIRMED, build_fact_store, case_groups, own_case_numbers

    findings: List[Finding] = []
    if len(docs) < 2:
        return findings
    doc_entity_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for doc in docs:
        entities = extract_document_entities(doc)
        _annotate(doc, entities)
        doc_entity_map[doc.document_id] = entities
    numbers = {doc.document_id: own_case_numbers(doc) for doc in docs}
    groups = case_groups(docs, build_fact_store(docs))

    for group in groups:
        if len(group) < 2:
            continue
        for key in ENTITY_PATTERNS:
            items = [item for doc_id in group for item in doc_entity_map[doc_id].get(key, [])
                     if item.get("modality", CONFIRMED) == CONFIRMED]
            if not items:
                continue
            reported = False
            # 1) 같은 당사자에 묶인 확정 서술끼리
            if key in PARTY_BOUND_KEYS:
                for subject in sorted({i["subject"] for i in items if i.get("subject")}):
                    by_doc = _group_by_doc([i for i in items if i.get("subject") == subject])
                    if not _differs(by_doc):
                        continue
                    shared = set.intersection(*(numbers[d] for d in by_doc)) if by_doc else set()
                    single = all(len({i["norm"] for i in its}) == 1 for its in by_doc.values())
                    bound = ({"subject": subject, "shared_case_numbers": sorted(shared), "binding": "PARTY_AND_CASE",
                              "rule_id": "XDOC.PARTY_FACT_CONFLICT"} if shared and single else None)
                    findings.append(_xdoc_finding(key, by_doc, bound=bound))
                    reported = True
            if reported:
                continue
            # 2) 주체를 특정하지 못한 값이 있으면 참고(C)로만 알린다. 서로 다른 당사자의 값끼리는 비교하지 않는다.
            if not any(i.get("subject") is None for i in items):
                continue
            by_doc = _group_by_doc(items)
            if _differs(by_doc):
                findings.append(_xdoc_finding(key, by_doc))
    return findings
