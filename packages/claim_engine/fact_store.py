"""사건 단위 사실 저장소와 문서 간·문서 안 불일치(추가지시 G5, v4 P1 CROSS_DOC_INCONSISTENCY).

1. 사건 묶기. 한 프로젝트에 여러 사건의 문서가 섞일 수 있으므로 같은 사건의 문서끼리만 비교한다.
   - 자기 사건번호(머리글 '사건 2024가합10001', '2024구합20002 영업정지처분취소')가 같으면 같은 사건,
     서로 다르면 다른 사건이다. 인용한 판례 번호(…선고 … 판결)는 자기 사건번호가 아니다.
   - 분야(사건부호·핵심어로 본 민사·형사·행정·가사)가 분명히 다르면 다른 사건이다.
   - 당사자 가명(원고 김○○, 환자 김○○ 등, 대리인·의사 같은 작성자는 빼고)이 겹치면 같은 사건으로 묶는다.
   - 식별 표지가 없는 문서는 어긋나지 않는 묶음이 하나뿐일 때만 그 묶음에 넣는다. 묶음이 없으면 표지 없는
     문서끼리 한 사건으로 본다(같은 프로젝트에 함께 올린 문서).
2. 문서 안 구획. '첨부 진단서(사본)' 같은 첨부 사본 제목 뒤는 첨부 구획으로 나눠, 본문과 첨부 원문도 대조한다.
3. 사실 튜플: 부위 좌·우, 사고(사건)일, 청구금액, 당사자 성명(가명 표기). 판정은 문서가 적은 글자에만 근거하고
   어느 쪽이 맞는지는 판단하지 않는다. 실명(가명이 아닌 이름)은 일반 낱말과 구분할 수 없어 성명 대조에 쓰지 않는다.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text, sentence_bounds

from .calculation import parse_amounts

ENGINE_NAME = "claim_engine.fact_store"
DEFECT_CODE = "CROSS_DOC_INCONSISTENCY"
PARTS = (r"슬관절|무릎|견관절|어깨|수관절|손목|족관절|발목|고관절|주관절|팔꿈치|대퇴부?|허벅지|하퇴부?|종아리|정강이|"
         r"상완부?|전완부?|손가락|수지|발가락|족지|늑골|갈비뼈|쇄골|안구|눈|귀|팔|다리")
SIDE_PART_RE = re.compile(rf"(?P<side>좌측|우측|왼쪽|오른쪽|좌|우)\s*(?P<part>{PARTS})")
SIDE = {"좌측": "좌", "왼쪽": "좌", "좌": "좌", "우측": "우", "오른쪽": "우", "우": "우"}
BILATERAL_RE = re.compile(r"양측|양쪽|좌\s*[·ㆍ,및]\s*우|좌우|우\s*[·ㆍ,및]\s*좌")
DATE = r"(?P<y>(?:19|20)\d{2})\s*\.\s*(?P<m>\d{1,2})\s*\.\s*(?P<d>\d{1,2})\s*\.?"
DATE_RE = re.compile(DATE)
# 사고일: 날짜 바로 뒤(짧은 거리)에 사고·범행 서술이 오거나, 날짜 바로 앞에 '사고일·범행일·발병일'이 온다.
INCIDENT_AFTER_RE = re.compile(r"^[^.。\n]{0,24}?(?:사고(?:로|가|를|를\s*당)|교통사고|추돌|충돌|폭행(?:을|하|당)|피습|"
                               r"상해를\s*입|부상을\s*입|범행(?:을|하))")
INCIDENT_BEFORE_RE = re.compile(r"(?:사고일|사고\s*당일|사건\s*당일|범행일|발병일|수상일|사고\s*일자)\s*(?:인|은|는|:|：)?\s*$")
RELIEF_RE = re.compile(r"청\s*구\s*취\s*지")
GROUNDS_RE = re.compile(r"청\s*구\s*원\s*인")
CLAIMED_RE = re.compile(r"청구\s*(?:금액|액)\s*(?:은|는|인)?\s*(?:금\s*)?")
ATTACHED_HEAD_RE = re.compile(r"^\s*[\[【(]?\s*첨부\s*[\]】)]?\s*\S{1,20}(?:\(\s*사본\s*\)|사본|원본)?\s*$")
# 자기 사건번호: 뒤에 판결·결정이 붙지 않고, 앞에 법원·선고가 없는 번호
CASE_NO_RE = re.compile(r"(?<![\d가-힣])(?P<no>(?:19|20)\d{2}\s*(?P<code>[가-힣]{1,3})\s*\d{1,7})(?![\d])")
CITED_BEFORE_RE = re.compile(r"(?:선고|법원|대법원|헌법재판소|지원|고등법원)\s*(?:\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*)?(?:선고\s*)?$")
CITED_AFTER_RE = re.compile(r"^\s*(?:판결|결정|전원합의체|호\s*판결|등\s*판결)")
FIELD_BY_CODE = {
    "민사": {"가합", "가단", "가소", "나", "다", "머", "카합", "카단"},
    "행정": {"구합", "구단", "누", "두", "아"},
    "형사": {"고합", "고단", "고정", "고약", "노", "도", "초"},
    "가사": {"드합", "드단", "르", "므", "느합", "느단", "즈합", "즈단"},
}
FIELD_WORDS = {
    "가사": r"이혼|재산분할|양육비|친권자|면접교섭|혼인관계|혼인신고",
    "형사": r"피고인|공소사실|공소장|변론요지서|기소|범행",
    "행정": r"처분의\s*취소|처분취소|행정청|재결|행정심판|취소소송",
}
MASK = r"[○◯〇Ｏ＊*]{1,3}"
PARTY_ROLES = r"원고|피고|피고인|피해자|청구인|피청구인|신청인|피신청인|채권자|채무자|환자|위\s*환자|사건본인|고소인"
PARTY_RE = re.compile(rf"(?P<role>{PARTY_ROLES})(?:\s*성명)?\s*[:：]?\s*(?P<name>[가-힣]{MASK})")
PLURAL_PARTY_RE = re.compile(r"(원고|피고|피고인|청구인|신청인)(?:들|\s*\d\s*[.)]|\s*등\s)")
SUBJECT_ROLES = {"환자", "위 환자", "위환자", "피해자", "사건본인"}


def _date_value(m: "re.Match[str]") -> Optional[str]:
    y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _role(role: str) -> str:
    role = re.sub(r"\s+", " ", role)
    return "환자" if role in ("위 환자", "위환자") else role


# --- 문서 구획과 표지 -------------------------------------------------------------------------
def segments(doc: NormalizedDocument) -> List[tuple]:
    """[(구획 이름, 블록들)]. 첨부 사본 제목 뒤는 첨부 구획이다."""
    blocks = [b for b in doc.body_blocks() if b.block_type not in ("table", "table_line")]
    out: List[tuple] = [("본문", [])]
    for block in blocks:
        text = (block.text or "").strip()
        if ATTACHED_HEAD_RE.match(text) and len(text) <= 30:
            out.append((re.sub(r"\s+", " ", text), []))
            continue
        out[-1][1].append(block)
    return [(name, bs) for name, bs in out if bs]


def own_case_numbers(doc: NormalizedDocument) -> Set[str]:
    text = "\n".join((b.text or "") for b in doc.body_blocks(include_running_heads=True))
    found = set()
    for m in CASE_NO_RE.finditer(text):
        if CITED_BEFORE_RE.search(text[max(0, m.start() - 30):m.start()]) or CITED_AFTER_RE.match(text[m.end():m.end() + 8]):
            continue
        if "헌" in m.group("code"):
            continue
        found.add(re.sub(r"\s+", "", m.group("no")))
    return found


def document_field(doc: NormalizedDocument, case_numbers: Set[str]) -> Optional[str]:
    for number in case_numbers:
        code = re.sub(r"[\d\s]", "", number)
        for field, codes in FIELD_BY_CODE.items():
            if code in codes:
                return field
    text = "\n".join((b.text or "") for b in doc.body_blocks(include_running_heads=True))
    hits = {field: len(re.findall(pattern, text)) for field, pattern in FIELD_WORDS.items()}
    best = max(hits, key=hits.get)
    ranked = sorted(hits.values(), reverse=True)
    return best if ranked[0] >= 2 and ranked[0] >= 2 * ranked[1] else None


# --- 사실 튜플 ---------------------------------------------------------------------------------
def _facts(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for segment, blocks in segments(doc):
        text = build_reading_text(doc, blocks).text
        base = {"document_id": doc.document_id, "segment": segment}
        for start, end in sentence_bounds(text):
            sentence = text[start:end]
            bilateral = bool(BILATERAL_RE.search(sentence))
            sides: Dict[str, Set[str]] = {}
            for m in SIDE_PART_RE.finditer(sentence):
                sides.setdefault(m.group("part"), set()).add(SIDE[m.group("side")])
            for m in SIDE_PART_RE.finditer(sentence):
                # 한 문장에서 같은 부위를 양쪽 모두 적었으면 양측 부상이다(모순이 아니다)
                if not bilateral and len(sides[m.group("part")]) == 1:
                    out.append({**base, "attribute": "injury_side", "key": m.group("part"), "value": SIDE[m.group("side")],
                                "excerpt": " ".join(sentence.split())[:160]})
            for m in DATE_RE.finditer(sentence):
                value = _date_value(m)
                if value and (INCIDENT_AFTER_RE.match(sentence[m.end():]) or INCIDENT_BEFORE_RE.search(sentence[:m.start()])):
                    out.append({**base, "attribute": "incident_date", "key": "incident", "value": value,
                                "excerpt": " ".join(sentence.split())[:160]})
        relief = RELIEF_RE.search(text)
        amount = None
        if relief:
            grounds = GROUNDS_RE.search(text, relief.end())
            amounts = parse_amounts(text[relief.end():grounds.start() if grounds else relief.end() + 600])
            amount = amounts[0] if amounts else None
        if amount is None:
            claimed = CLAIMED_RE.search(text)
            amounts = parse_amounts(text[claimed.end():claimed.end() + 40]) if claimed else []
            amount = amounts[0] if amounts and amounts[0].start <= 3 else None
        if amount is not None:
            out.append({**base, "attribute": "claim_amount", "key": "claim", "value": str(amount.value),
                        "excerpt": " ".join(amount.raw.split())})
        plural = {m.group(1) for m in PLURAL_PARTY_RE.finditer(text)}
        for m in PARTY_RE.finditer(text):
            role = _role(m.group("role"))
            out.append({**base, "attribute": "party_name", "key": role, "value": m.group("name"),
                        "plural_role": role in plural,
                        "excerpt": " ".join(text[max(0, m.start() - 20):m.end() + 20].split())})
    # 표의 '환자 성명 | 김○○' 같은 칸 쌍
    for table in _tables(doc):
        for row in table:
            cells = [" ".join(str(c or "").split()) for c in row]
            for label, value in zip(cells, cells[1:]):
                role = re.fullmatch(rf"(?P<role>{PARTY_ROLES})(?:\s*성명)?", label)
                name = re.fullmatch(rf"[가-힣]{MASK}", value)
                if role and name:
                    out.append({"document_id": doc.document_id, "segment": "본문", "attribute": "party_name",
                                "key": _role(role.group("role")), "value": value, "plural_role": False,
                                "excerpt": f"{label} {value}"})
    return out


def _tables(doc: NormalizedDocument) -> List[List[List[str]]]:
    tables = [t.get("cells") or [] for t in doc.structure.get("tables") or []]
    known = {t.get("table_ref") for t in doc.structure.get("tables") or []}
    tables += [b.attributes.get("cells") or [] for b in doc.blocks
               if b.block_type == "table" and b.attributes.get("table_ref") not in known]
    return tables


def build_fact_store(documents: Iterable[NormalizedDocument]) -> List[Dict[str, Any]]:
    return [fact for doc in documents for fact in _facts(doc)]


# --- 사건 묶기 ---------------------------------------------------------------------------------
def case_groups(documents: List[NormalizedDocument], store: List[Dict[str, Any]]) -> List[List[str]]:
    info: Dict[str, Dict[str, Any]] = {}
    for doc in documents:
        numbers = own_case_numbers(doc)
        names = {f["value"] for f in store if f["document_id"] == doc.document_id and f["attribute"] == "party_name"}
        info[doc.document_id] = {"numbers": numbers, "field": document_field(doc, numbers), "names": names}

    def compatible(a: str, b: str) -> bool:
        x, y = info[a], info[b]
        if x["numbers"] and y["numbers"] and not (x["numbers"] & y["numbers"]):
            return False
        return not (x["field"] and y["field"] and x["field"] != y["field"])

    ids = [d.document_id for d in documents]
    parent = {i: i for i in ids}

    def find(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if not compatible(a, b):
                continue
            if (info[a]["numbers"] & info[b]["numbers"]) or (info[a]["names"] & info[b]["names"]):
                parent[find(a)] = find(b)
    groups: Dict[str, List[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    loose = [g[0] for g in groups.values() if len(g) == 1 and not info[g[0]]["numbers"] and not info[g[0]]["names"]]
    candidates = [g for g in groups.values() if not (len(g) == 1 and g[0] in loose)]
    linked = [g for g in candidates if len(g) > 1]
    for doc_id in loose:
        # 표지 없는 문서는 어긋나지 않는 사건이 하나뿐일 때만 붙인다(두 사건 이상이면 어느 쪽인지 모른다)
        fits = [g for g in candidates if all(compatible(doc_id, other) for other in g)]
        if len(fits) == 1:
            fits[0].append(doc_id)
            if fits[0] not in linked:
                linked.append(fits[0])
    if not candidates:
        # 묶을 표지가 하나도 없으면 같은 프로젝트의 문서를 한 사건으로 본다(서로 어긋나는 것끼리는 제외)
        pool: List[str] = []
        for doc_id in loose:
            if all(compatible(doc_id, other) for other in pool):
                pool.append(doc_id)
        if len(pool) > 1:
            linked.append(pool)
    placed = {d for g in linked for d in g}
    return linked + [[d] for d in ids if d not in placed]


# --- 판정 --------------------------------------------------------------------------------------
def digit_transposition(a: str, b: str) -> bool:
    """자릿수가 같고 같은 숫자들의 순서만 바뀐 두 금액(205,000,000 ↔ 250,000,000)."""
    x, y = re.sub(r"\D", "", a.split(".")[0]), re.sub(r"\D", "", b.split(".")[0])
    return len(x) == len(y) and x != y and sorted(x) == sorted(y)


def _finding(kind: str, scope: str, title: str, detail: str, members: List[Dict[str, Any]], grade: EvidenceGrade,
             status: VerificationStatus, names: Dict[str, str], **extra: Any) -> Finding:
    docs = list(dict.fromkeys(m["document_id"] for m in members))
    return Finding.create(
        type=FindingType.CROSS_DOCUMENT_CONTRADICTION, status=status,
        severity=Severity.HIGH if grade == EvidenceGrade.B else Severity.MEDIUM, evidence_grade=grade,
        title=title, detail=detail, confidence=0.75 if grade == EvidenceGrade.B else 0.5,
        confidence_features={"deterministic_rule": True, "rule_id": f"FACT.{kind}", "defect_code": DEFECT_CODE,
                             "scope": scope, "documents": docs, "facts": members[:10], "differences": title,
                             "sources": [{"document_id": d} for d in docs], **extra},
        document_id=docs[0], engine=ENGINE_NAME, tags=["CROSS_DOCUMENT" if scope == "CROSS_DOCUMENT" else "IN_DOCUMENT",
                                                       "FACT_STORE"],
        evidence=[Evidence.create(description=f"{names.get(m['document_id'], m['document_id'])} {m['segment']}의 기재",
                                  grade=grade, document_id=m["document_id"], excerpt=m["excerpt"])
                  for m in members[:6]])


def _where(fact: Dict[str, Any], names: Dict[str, str]) -> str:
    return names.get(fact["document_id"], fact["document_id"]) + ("" if fact["segment"] == "본문" else f" {fact['segment']}")


def _in_document(store: List[Dict[str, Any]], names: Dict[str, str]) -> List[Finding]:
    out: List[Finding] = []
    for doc_id in dict.fromkeys(f["document_id"] for f in store):
        facts = [f for f in store if f["document_id"] == doc_id]
        # 같은 부위의 좌·우가 본문과 첨부 사본(또는 본문 안)에서 다르다
        for part in dict.fromkeys(f["key"] for f in facts if f["attribute"] == "injury_side"):
            members = [f for f in facts if f["attribute"] == "injury_side" and f["key"] == part]
            if len({m["value"] for m in members}) > 1:
                label = ", ".join(f"{_where(m, names)} {m['value']}측" for m in
                                  {(m["segment"], m["value"]): m for m in members}.values())
                out.append(_finding("INJURY_SIDE", "IN_DOCUMENT", f"같은 문서 안에서 {part}의 좌·우가 다르다: {label}",
                                    f"한 문서 안에서 {part} 부위를 서로 반대쪽으로 적었다(본문과 첨부 사본의 대조 포함). 어느 기재가 "
                                    "맞는지 원본으로 확인해야 한다.", members, EvidenceGrade.B,
                                    VerificationStatus.CONTRADICTED, names))
        # 같은 역할(원고 등)의 가명 표기가 다르다. 당사자가 여럿이라고 밝힌 역할은 보지 않는다.
        for role in dict.fromkeys(f["key"] for f in facts if f["attribute"] == "party_name"):
            members = [f for f in facts if f["attribute"] == "party_name" and f["key"] == role]
            if any(m["plural_role"] for m in members) or role in SUBJECT_ROLES:
                continue
            counts = Counter(m["value"] for m in members)
            if len(counts) > 1:
                label = ", ".join(f"{name} {n}회" for name, n in counts.most_common())
                out.append(_finding("PARTY_NAME", "IN_DOCUMENT", f"같은 문서 안에서 {role} 성명 표기가 다르다: {label}",
                                    f"한 문서 안에서 {role}을(를) 서로 다른 성명으로 적었다. 당사자가 여럿이라는 기재가 없으므로 "
                                    "표기 오류인지 확인해야 한다.", members, EvidenceGrade.B,
                                    VerificationStatus.CONTRADICTED, names, names_found=dict(counts)))
    return out


def _cross_document(group: List[str], store: List[Dict[str, Any]], names: Dict[str, str]) -> List[Finding]:
    out: List[Finding] = []
    facts = [f for f in store if f["document_id"] in group and f["segment"] == "본문"]

    for part in dict.fromkeys(f["key"] for f in facts if f["attribute"] == "injury_side"):
        per_doc: Dict[str, Set[str]] = {}
        for f in facts:
            if f["attribute"] == "injury_side" and f["key"] == part:
                per_doc.setdefault(f["document_id"], set()).add(f["value"])
        single = {d: next(iter(s)) for d, s in per_doc.items() if len(s) == 1}
        if len(single) >= 2 and len(set(single.values())) > 1:
            members = [f for f in facts if f["attribute"] == "injury_side" and f["key"] == part and f["document_id"] in single]
            label = ", ".join(f"{names[d]} {v}측" for d, v in single.items())
            out.append(_finding("INJURY_SIDE", "CROSS_DOCUMENT", f"문서마다 {part}의 좌·우가 다르다: {label}",
                                f"같은 사건 문서에서 {part} 부위를 서로 반대쪽으로 적었다. 어느 기재가 맞는지 원본(진료기록 등)으로 "
                                "확인해야 한다.", members, EvidenceGrade.B, VerificationStatus.CONTRADICTED, names))

    incidents: Dict[str, Set[str]] = {}
    for f in facts:
        if f["attribute"] == "incident_date":
            incidents.setdefault(f["document_id"], set()).add(f["value"])
    single = {d: next(iter(v)) for d, v in incidents.items() if len(v) == 1}
    if len(single) >= 2 and len(set(single.values())) > 1:
        members = [f for f in facts if f["attribute"] == "incident_date" and f["document_id"] in single]
        label = ", ".join(f"{names[d]} {v}" for d, v in single.items())
        out.append(_finding("INCIDENT_DATE", "CROSS_DOCUMENT", f"문서마다 사고일(사건일)이 다르다: {label}",
                            "같은 사건 문서가 사고·사건이 일어난 날을 서로 다르게 적었다.", members, EvidenceGrade.B,
                            VerificationStatus.CONTRADICTED, names))

    amounts: Dict[str, Dict[str, Any]] = {}
    for f in facts:
        if f["attribute"] == "claim_amount":
            amounts.setdefault(f["document_id"], f)
    if len({f["value"] for f in amounts.values()}) > 1:
        values = [f["value"] for f in amounts.values()]
        transposed = any(digit_transposition(a, b) for i, a in enumerate(values) for b in values[i + 1:])
        label = ", ".join(f"{names[d]} {f['excerpt']}" for d, f in amounts.items())
        out.append(_finding("CLAIM_AMOUNT", "CROSS_DOCUMENT",
                            f"문서마다 청구금액이 다르다{'(자릿수 뒤바뀜 의심)' if transposed else ''}: {label}",
                            ("같은 숫자의 자리만 바뀐 금액이다. 기재 오류일 가능성이 있어 확인해야 한다. " if transposed else "")
                            + "청구취지 변경(확장·감축)인지, 기재 오류인지 사람이 확인한다.",
                            list(amounts.values()), EvidenceGrade.C, VerificationStatus.SUSPICIOUS, names,
                            digit_transposition=transposed))

    roles: Dict[str, Dict[str, Counter]] = {}
    for f in facts:
        if f["attribute"] == "party_name" and f["key"] not in SUBJECT_ROLES and not f["plural_role"]:
            roles.setdefault(f["key"], {}).setdefault(f["document_id"], Counter())[f["value"]] += 1
    for role, per_doc in roles.items():
        main = {d: c.most_common(1)[0][0] for d, c in per_doc.items()}
        if len(main) >= 2 and len(set(main.values())) > 1:
            members = [f for f in facts if f["attribute"] == "party_name" and f["key"] == role and f["document_id"] in main]
            label = ", ".join(f"{names[d]} {v}" for d, v in main.items())
            out.append(_finding("PARTY_NAME", "CROSS_DOCUMENT", f"문서마다 {role} 성명 표기가 다르다: {label}",
                                f"같은 사건 문서가 {role}을(를) 서로 다른 성명으로 적었다.", members, EvidenceGrade.B,
                                VerificationStatus.CONTRADICTED, names))
    return out


def cross_document_facts(documents: Iterable[NormalizedDocument]) -> List[Finding]:
    documents = list(documents)
    names = {d.document_id: d.filename for d in documents}
    store = build_fact_store(documents)
    out = _in_document(store, names)
    for group in case_groups(documents, store):
        if len(group) > 1:
            out.extend(_cross_document(group, store, names))
    return out


def incident_dates(doc: NormalizedDocument) -> List[str]:
    """문서 본문이 적은 사고(사건)일. 증거 작성일의 선후 판단에 쓴다."""
    return sorted({f["value"] for f in _facts(doc) if f["attribute"] == "incident_date" and f["segment"] == "본문"})


__all__ = ["build_fact_store", "case_groups", "cross_document_facts", "digit_transposition", "incident_dates",
           "own_case_numbers", "segments"]
