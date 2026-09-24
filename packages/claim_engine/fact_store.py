"""사건 단위 사실 저장소와 문서 간 불일치(추가지시 G5).

같은 사건의 문서들(소장·준비서면·진단서·진술서 등)에서 사실 튜플을 뽑아 같은 속성끼리 비교한다.
- injury_side: 신체 부위와 좌·우(예: 슬관절–좌). 같은 부위를 문서마다 반대쪽으로 적으면 불일치(B).
- incident_date: 사고·사건이 일어난 날. 문서마다 하나씩만 적었는데 서로 다르면 불일치(B).
- claim_amount: 청구취지의 청구 금액. 다르면 청구취지 변경일 수 있어 사람 확인(C).
판정은 문서가 적은 글자에만 근거하고, 어느 쪽이 맞는지는 판단하지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text, sentence_bounds

from .calculation import parse_amounts

ENGINE_NAME = "claim_engine.fact_store"
PARTS = (r"슬관절|무릎|견관절|어깨|수관절|손목|족관절|발목|고관절|주관절|팔꿈치|대퇴부?|허벅지|하퇴부?|종아리|정강이|"
         r"상완부?|전완부?|손가락|수지|발가락|족지|늑골|갈비뼈|쇄골|안구|눈|귀|팔|다리")
SIDE_PART_RE = re.compile(rf"(?P<side>좌측|우측|왼쪽|오른쪽|좌|우)\s*(?P<part>{PARTS})")
SIDE = {"좌측": "좌", "왼쪽": "좌", "좌": "좌", "우측": "우", "오른쪽": "우", "우": "우"}
INCIDENT_RE = re.compile(r"사고|사건\s*당일|사고일|발생(?:하|한|일)|폭행|상해를\s*입|부상을\s*입|추돌|충돌|피습")
DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*\.\s*(?P<m>\d{1,2})\s*\.\s*(?P<d>\d{1,2})\s*\.?")
RELIEF_RE = re.compile(r"청\s*구\s*취\s*지")
GROUNDS_RE = re.compile(r"청\s*구\s*원\s*인")


def _facts(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    text = build_reading_text(doc).text
    out: List[Dict[str, Any]] = []
    for m in SIDE_PART_RE.finditer(text):
        out.append({"document_id": doc.document_id, "attribute": "injury_side", "key": m.group("part"),
                    "value": SIDE[m.group("side")], "excerpt": " ".join(m.group(0).split())})
    for start, end in sentence_bounds(text):
        sentence = text[start:end]
        if not INCIDENT_RE.search(sentence):
            continue
        for m in DATE_RE.finditer(sentence):
            value = f"{int(m.group('y')):04d}-{int(m.group('m')):02d}-{int(m.group('d')):02d}"
            out.append({"document_id": doc.document_id, "attribute": "incident_date", "key": "incident",
                        "value": value, "excerpt": " ".join(sentence.split())[:160]})
    relief = RELIEF_RE.search(text)
    if relief:
        grounds = GROUNDS_RE.search(text, relief.end())
        section = text[relief.end():grounds.start() if grounds else relief.end() + 600]
        amounts = parse_amounts(section)
        if amounts:
            out.append({"document_id": doc.document_id, "attribute": "claim_amount", "key": "claim",
                        "value": str(amounts[0].value), "excerpt": " ".join(amounts[0].raw.split())})
    return out


def build_fact_store(documents: Iterable[NormalizedDocument]) -> List[Dict[str, Any]]:
    return [fact for doc in documents for fact in _facts(doc)]


def _finding(kind: str, title: str, detail: str, members: List[Dict[str, Any]], grade: EvidenceGrade,
             status: VerificationStatus, names: Dict[str, str]) -> Finding:
    docs = list(dict.fromkeys(m["document_id"] for m in members))
    return Finding.create(
        type=FindingType.CROSS_DOCUMENT_CONTRADICTION, status=status,
        severity=Severity.HIGH if grade == EvidenceGrade.B else Severity.MEDIUM, evidence_grade=grade,
        title=title, detail=detail, confidence=0.75 if grade == EvidenceGrade.B else 0.5,
        confidence_features={"deterministic_rule": True, "rule_id": f"FACT.{kind}", "documents": docs,
                             "facts": members[:10], "differences": title,
                             "sources": [{"document_id": d} for d in docs]},
        document_id=docs[0], engine=ENGINE_NAME, tags=["CROSS_DOCUMENT", "FACT_STORE"],
        evidence=[Evidence.create(description=f"{names.get(m['document_id'], m['document_id'])}의 기재",
                                  grade=grade, document_id=m["document_id"], excerpt=m["excerpt"])
                  for m in members[:6]])


def cross_document_facts(documents: Iterable[NormalizedDocument]) -> List[Finding]:
    documents = list(documents)
    names = {d.document_id: d.filename for d in documents}
    store = build_fact_store(documents)
    out: List[Finding] = []

    by_part: Dict[str, Dict[str, set]] = {}
    for fact in (f for f in store if f["attribute"] == "injury_side"):
        by_part.setdefault(fact["key"], {}).setdefault(fact["document_id"], set()).add(fact["value"])
    for part, per_doc in by_part.items():
        single = {doc: sides for doc, sides in per_doc.items() if len(sides) == 1}
        if len(single) >= 2 and len({next(iter(s)) for s in single.values()}) > 1:
            members = [f for f in store if f["attribute"] == "injury_side" and f["key"] == part
                       and f["document_id"] in single]
            label = ", ".join(f"{names[d]} {next(iter(s))}측" for d, s in single.items())
            out.append(_finding("INJURY_SIDE", f"문서마다 {part}의 좌·우가 다르다: {label}",
                                f"같은 사건 문서에서 {part} 부위를 서로 반대쪽으로 적었다. 어느 기재가 맞는지 원본(진료기록 등)으로 "
                                "확인해야 한다.", members, EvidenceGrade.B, VerificationStatus.CONTRADICTED, names))

    incidents: Dict[str, set] = {}
    for fact in (f for f in store if f["attribute"] == "incident_date"):
        incidents.setdefault(fact["document_id"], set()).add(fact["value"])
    single = {doc: next(iter(v)) for doc, v in incidents.items() if len(v) == 1}
    if len(single) >= 2 and len(set(single.values())) > 1:
        members = [f for f in store if f["attribute"] == "incident_date" and f["document_id"] in single]
        label = ", ".join(f"{names[d]} {v}" for d, v in single.items())
        out.append(_finding("INCIDENT_DATE", f"문서마다 사고일(사건일)이 다르다: {label}",
                            "같은 사건 문서가 사고·사건이 일어난 날을 서로 다르게 적었다.", members, EvidenceGrade.B,
                            VerificationStatus.CONTRADICTED, names))

    amounts = {f["document_id"]: f for f in store if f["attribute"] == "claim_amount"}
    if len({f["value"] for f in amounts.values()}) > 1:
        label = ", ".join(f"{names[d]} {f['excerpt']}" for d, f in amounts.items())
        out.append(_finding("CLAIM_AMOUNT", f"문서마다 청구금액이 다르다: {label}",
                            "청구취지의 금액이 문서마다 다르다. 청구취지 변경(확장·감축)인지, 기재 오류인지 사람이 확인한다.",
                            list(amounts.values()), EvidenceGrade.C, VerificationStatus.SUSPICIOUS, names))
    return out
