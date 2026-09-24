"""증거 정합성 점검(v2 R9·Phase 7).

증거설명서·입증방법의 호증 목록과 본문, 같은 사건의 다른 서면을 서로 대조한다. 모두 문서 자체만으로
확인되는 형식·논리 사항이며, 법률 판단(증명력·채부)은 하지 않는다.

- 작성일이 달력에 없는 날짜 → EVIDENCE_DATE_INVALID (A)
- 작성일이 제출 서면 작성일보다 뒤 → EVIDENCE_TIMELINE_INVERSION (A: 제출 시점에 있을 수 없는 문서)
- 분석·보고·진술 자료의 작성일이 그 대상 사건일보다 앞 → EVIDENCE_TIMELINE_INVERSION (B)
- 호증 번호 결번, 본문이 언급한 호증이 목록에 없음 → EVIDENCE_NUMBERING_GAP / EVIDENCE_LIST_MISMATCH (B)
- 같은 사람의 계급·소속 기재가 증거 목록과 진술서에서 다름 → EVIDENCE_PERSON_INCONSISTENT (B)
- 진술서 서명 생략 → EVIDENCE_FORM_DEFECT (B)
- 지각하지 못했다면서 단정하는 진술 → STATEMENT_BEYOND_PERCEPTION (C, 사람 확인)
- 진단서·소견서로 의료와 무관한 사실을 입증하려 함 → EVIDENCE_PURPOSE_MISMATCH (C, 사람 확인)
- 서로 다른 서면에 같은 문장(인용문 제외)이 그대로 있음 → CROSS_DOC_COPY (B)
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text, join_separator, sentence_bounds

ENGINE_NAME = "claim_engine.evidence_consistency"

EXHIBIT_RE = re.compile(r"(?P<party>갑|을|병)\s*(?:제\s*)?(?P<number>\d{1,3})\s*호\s*증(?:\s*의\s*(?P<branch>\d{1,3}))?")
DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[.\-년]\s*(?P<m>\d{1,2})\s*[.\-월]\s*(?P<d>\d{1,2})\s*[.일]?")
STANDALONE_DATE_RE = re.compile(r"^\s*(?:19|20)\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*$")
HEADER_KEYS = {
    "id": ("호증", "증거번호", "번호"),
    "name": ("서증명", "증거명", "자료명", "문서명", "표목"),
    "date": ("작성일", "일자", "작성일자"),
    "author": ("작성자", "작성명의인", "발행"),
    "purpose": ("입증취지", "입증 취지", "증명취지"),
}
# 사건 이후에 작성될 수밖에 없는 자료(그 사건을 분석·보고·진술한 문서)
AFTER_EVENT_KINDS = re.compile(r"분석|보고서|감정|진술|확인서|소견|조사")
MEDICAL_KINDS = re.compile(r"진단서|소견서|의무기록|진료기록")
MEDICAL_TERMS = re.compile(r"상해|부상|질병|질환|진단|치료|증상|건강|병명|장애|수술|통증|정신|심리|입원|외상")
# 계급(군). 법률 사실이 아니라 직급 명칭 목록이다.
RANKS = ("이병", "일병", "상병", "병장", "하사", "중사", "상사", "원사", "준위", "소위", "중위", "대위",
         "소령", "중령", "대령", "준장", "소장", "중장", "대장")
RANK_RE = re.compile("|".join(RANKS))
UNIT_RE = re.compile(r"제\s*(\d+)\s*(대대|중대|연대|여단|소대)")
NAME_FIELD_RE = re.compile(r"성\s*명\s*[:：]?\s*(?P<name>[가-힣][가-힣○△□＊*]{1,4})")
AFFILIATION_FIELD_RE = re.compile(r"소\s*속\s*[·ㆍ・]?\s*(?:계\s*급)?\s*[:：]?\s*(?P<value>[^\n]{2,60})")
SIGNATURE_OMITTED_RE = re.compile(r"(서명|날인|기명날인)\s*(생략|없음|미기재)")
LIMITATION_RE = re.compile(r"(들을\s*수\s*(는\s*)?없|듣지\s*못|보지\s*못|볼\s*수\s*(는\s*)?없|알\s*수\s*(는\s*)?없|"
                           r"기억(하지|나지)\s*(못|않)|확인하지\s*못)")
CERTAINTY_RE = re.compile(r"확실|분명|틀림없|단언|명백")
# 진술인의 위치: 가까이 있었다는 표현과 떨어져 있었다는 표현
PROXIMITY_RE = re.compile(r"같은\s*테이블|바로\s*옆|옆\s*자리|함께\s*앉|맞은\s*편|곁에")
DISTANCE_RE = re.compile(r"\d+\s*(?:미터|m|M)\s*(?:가량|정도|쯤)?\s*떨어진|다른\s*테이블|멀리\s*떨어")
# 진술인 명의 문서의 제목 줄(문단 전체가 제목). 증거 목록 속 "각 진술서"는 제목이 아니다.
STATEMENT_HEADING_RE = re.compile(r"(?:^|\n)\s*(?:진\s*술\s*서|사\s*실\s*확\s*인\s*서|확\s*인\s*서)\s*(?:\n|$)")
COPY_MIN_CHARS = 30
COPY_SIMILARITY = 0.9


# --- 날짜 --------------------------------------------------------------------------
def _k(value: date) -> str:
    return f"{value.year}. {value.month}. {value.day}."


def calendar_date(text: str) -> Tuple[Optional[date], Optional[str]]:
    """문자열의 첫 날짜를 읽는다. 반환 (날짜, 오류). 달력에 없는 날짜면 (None, "2026. 4. 31.")."""
    m = DATE_RE.search(text or "")
    if not m:
        return None, None
    y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
    try:
        return date(y, mo, d), None
    except ValueError:
        return None, m.group(0).strip()


def _all_dates(text: str) -> List[date]:
    out = []
    for m in DATE_RE.finditer(text or ""):
        try:
            out.append(date(int(m.group("y")), int(m.group("m")), int(m.group("d"))))
        except ValueError:
            continue
    return out


SIGNATURE_LINE_RE = re.compile(r"\(\s*인\s*\)|귀\s*중|대\s*리\s*인|서\s*명|날\s*인")


def document_date(doc: NormalizedDocument) -> Optional[date]:
    """서면의 작성일: 날짜만 있는 줄 가운데 바로 뒤(3줄 안)에 서명·귀중 줄이 오는 첫 날짜.

    증거설명서 뒤에 진술서 등이 붙어 있으면 뒤쪽 날짜는 첨부 문서의 작성일이므로 첫 서명 날짜를 쓴다.
    """
    blocks = doc.prose_blocks()
    for index, block in enumerate(blocks):
        if not STANDALONE_DATE_RE.match(block.text or ""):
            continue
        if any(SIGNATURE_LINE_RE.search(b.text or "") for b in blocks[index + 1:index + 4]):
            parsed, _ = calendar_date(block.text)
            if parsed:
                return parsed
    return None


# --- 호증 목록 ---------------------------------------------------------------------
def _cell(value: Any) -> str:
    text = ""
    for line in str(value or "").splitlines():
        line = line.strip()
        if line:
            text = (text + join_separator(text, line) + line) if text else line
    return " ".join(text.split())


def exhibit_rows(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """문서의 표 가운데 호증 목록을 찾아 행마다 {id, party, number, branch, name, date, author, purpose}."""
    rows: List[Dict[str, Any]] = []
    for table in doc.structure.get("tables") or []:
        cells = table.get("cells") or []
        if len(cells) < 2:
            continue
        header = [_cell(h) for h in cells[0]]
        columns = {}
        for key, names in HEADER_KEYS.items():
            for index, title in enumerate(header):
                if any(name in title.replace(" ", "") for name in names) and index not in columns.values():
                    columns[key] = index
                    break
        if "id" not in columns or len(columns) < 3:
            continue
        for row in cells[1:]:
            values = {key: _cell(row[index]) if index < len(row) else "" for key, index in columns.items()}
            match = EXHIBIT_RE.search(values.get("id", ""))
            if not match:
                continue
            rows.append({**values, "party": match.group("party"), "number": int(match.group("number")),
                         "branch": match.group("branch"), "label": " ".join(match.group(0).split()),
                         "table_ref": table.get("table_ref"), "page": table.get("page")})
    return rows or _exhibit_lines(doc)


LINE_ITEM_RE = re.compile(r"^\s*" + EXHIBIT_RE.pattern)


def _exhibit_lines(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """표가 없을 때: 문단 첫머리가 호증 번호인 목록(입증방법·증거설명 목록)을 행으로 읽는다.

    칸 구분이 없으므로 호증 번호 뒤부터 첫 날짜 앞까지를 서증명, 첫 날짜를 작성일, 나머지를
    작성자·입증취지(합쳐서)로 본다.
    """
    rows: List[Dict[str, Any]] = []
    reading = build_reading_text(doc)
    for paragraph in reading.text.split("\n"):
        match = LINE_ITEM_RE.match(paragraph)
        if not match:
            continue
        rest = paragraph[match.end():].strip()
        found = DATE_RE.search(rest)
        name = rest[:found.start()].strip() if found else rest
        tail = rest[found.end():].strip() if found else ""
        rows.append({"id": match.group(0).strip(), "name": name, "date": found.group(0) if found else "",
                     "author": tail, "purpose": tail, "party": match.group("party"),
                     "number": int(match.group("number")), "branch": match.group("branch"),
                     "label": " ".join(match.group(0).split()), "table_ref": None, "page": None,
                     "from_lines": True})
    return rows


def _finding(doc: NormalizedDocument, kind: FindingType, grade: EvidenceGrade, severity: Severity, title: str,
             detail: str, excerpt: str = "", *, page: Optional[int] = None, features: Optional[Dict] = None,
             status: VerificationStatus = VerificationStatus.CONTRADICTED) -> Finding:
    features = {"deterministic_rule": True, "rule_id": f"EVI.{kind}", **(features or {})}
    return Finding.create(
        type=kind, status=status, severity=severity, evidence_grade=grade, title=title, detail=detail,
        confidence=0.9 if grade == EvidenceGrade.A else 0.7 if grade == EvidenceGrade.B else 0.5,
        confidence_features=features, document_id=doc.document_id, page=page, engine=ENGINE_NAME,
        tags=["EVIDENCE"],
        evidence=[Evidence.create(description="문서 기재", grade=grade, document_id=doc.document_id, page=page,
                                  excerpt=excerpt[:300])] if excerpt else [])


def check_exhibits(doc: NormalizedDocument) -> List[Finding]:
    rows = exhibit_rows(doc)
    if not rows:
        return []
    out: List[Finding] = []
    filed = document_date(doc)
    for row in rows:
        parsed, invalid = calendar_date(row.get("date", ""))
        where = f"{row['label']} {row.get('name', '')}".strip()
        if invalid:
            out.append(_finding(doc, FindingType.EVIDENCE_DATE_INVALID, EvidenceGrade.A, Severity.HIGH,
                                f"증거 작성일이 달력에 없는 날짜다: {where} 작성일 {invalid}",
                                "달력에 없는 날짜이므로 그 날짜로는 문서가 작성될 수 없다. 오기인지 원본을 확인해야 한다.",
                                f"{where} | {row.get('date')}", page=row.get("page"),
                                features={"exhibit": row["label"], "written_date": invalid}))
            continue
        if parsed is None:
            continue
        if filed and parsed > filed:
            out.append(_finding(doc, FindingType.EVIDENCE_TIMELINE_INVERSION, EvidenceGrade.A, Severity.HIGH,
                                f"증거 작성일이 이 서면의 작성일보다 뒤다: {where} 작성일 {_k(parsed)} "
                                f"(서면 작성일 {_k(filed)})",
                                "서면을 작성·제출한 시점에는 존재할 수 없는 문서를 증거로 적었다.",
                                f"{where} | {row.get('date')}", page=row.get("page"),
                                features={"exhibit": row["label"], "written": parsed.isoformat(),
                                          "filed": filed.isoformat()}))
            continue
        described = f"{row.get('name', '')} {row.get('purpose', '')}"
        if AFTER_EVENT_KINDS.search(row.get("name", "")):
            later = [d for d in _all_dates(described) if d > parsed]
            if later:
                event = max(later)
                out.append(_finding(doc, FindingType.EVIDENCE_TIMELINE_INVERSION, EvidenceGrade.B, Severity.HIGH,
                                    f"분석·보고 자료의 작성일이 그 대상 사건보다 앞선다: {where} 작성일 "
                                    f"{_k(parsed)}, 대상 {_k(event)}",
                                    "대상 사건이 일어나기 전에 그 사건을 분석·보고한 문서가 작성되었다고 적혀 있다.",
                                    f"{where} | {row.get('date')} | {row.get('purpose')}", page=row.get("page"),
                                    features={"exhibit": row["label"], "written": parsed.isoformat(),
                                              "event": event.isoformat()}))
        if MEDICAL_KINDS.search(row.get("name", "")) and row.get("purpose") and not MEDICAL_TERMS.search(row["purpose"]):
            out.append(_finding(doc, FindingType.EVIDENCE_PURPOSE_MISMATCH, EvidenceGrade.C, Severity.MEDIUM,
                                f"입증취지가 서증 성격 범위를 벗어날 수 있다: {where} → '{row['purpose']}'",
                                "의료 문서로 의료와 무관한 사실을 입증하려 한다. 증명력은 법원이 판단하므로 사람이 확인한다.",
                                f"{where} | {row.get('purpose')}", page=row.get("page"),
                                status=VerificationStatus.UNVERIFIED,
                                features={"exhibit": row["label"], "human_review": True}))
    out.extend(_numbering(doc, rows))
    return out


def _numbering(doc: NormalizedDocument, rows: List[Dict[str, Any]]) -> List[Finding]:
    out: List[Finding] = []
    listed: Dict[str, set] = {}
    for row in rows:
        listed.setdefault(row["party"], set()).add(row["number"])
    for party, numbers in listed.items():
        gaps = [n for n in range(1, max(numbers) + 1) if n not in numbers]
        if gaps:
            out.append(_finding(doc, FindingType.EVIDENCE_NUMBERING_GAP, EvidenceGrade.B, Severity.MEDIUM,
                                f"호증 번호가 비어 있다: {party} 제{', '.join(map(str, gaps))}호증 결번",
                                "증거 목록의 번호가 연속하지 않는다. 누락된 증거가 있는지 확인해야 한다.",
                                ", ".join(f"{party} 제{n}호증" for n in sorted(numbers)),
                                features={"party": party, "missing": gaps}))
    text = build_reading_text(doc).text
    mentioned = {(m.group("party"), int(m.group("number"))) for m in EXHIBIT_RE.finditer(text)}
    missing = sorted((p, n) for p, n in mentioned if p in listed and n not in listed[p])
    if missing:
        labels = ", ".join(f"{p} 제{n}호증" for p, n in missing)
        out.append(_finding(doc, FindingType.EVIDENCE_LIST_MISMATCH, EvidenceGrade.B, Severity.MEDIUM,
                            f"본문이 언급한 증거가 증거 목록에 없다: {labels}",
                            "본문에서 입증 근거로 든 호증이 증거 목록에 없다.", labels,
                            features={"missing_from_list": [f"{p} 제{n}호증" for p, n in missing]}))
    return out


# --- 진술서 ------------------------------------------------------------------------
def _statement_fields(text: str) -> List[Dict[str, Any]]:
    out = []
    for m in NAME_FIELD_RE.finditer(text):
        window = text[m.end():m.end() + 160]
        affiliation = AFFILIATION_FIELD_RE.search(window)
        value = affiliation.group("value") if affiliation else ""
        out.append({"name": m.group("name"), "ranks": set(RANK_RE.findall(value)),
                    "units": {(n, u) for n, u in UNIT_RE.findall(value)}, "raw": value.strip()})
    return out


def check_statements(doc: NormalizedDocument, exhibits: Sequence[Dict[str, Any]] = ()) -> List[Finding]:
    """진술서의 형식·지각 범위와, 증거 목록 기재와의 인적사항 일치."""
    out: List[Finding] = []
    reading = build_reading_text(doc, [b for b in doc.body_blocks() if b.block_type != "running_head"])
    text = reading.text
    if SIGNATURE_OMITTED_RE.search(text) and re.search(r"진\s*술\s*서|확\s*인\s*서", text):
        m = SIGNATURE_OMITTED_RE.search(text)
        out.append(_finding(doc, FindingType.EVIDENCE_FORM_DEFECT, EvidenceGrade.B, Severity.MEDIUM,
                            f"진술서에 서명이 없다: '{m.group(0)}'",
                            "진술인의 서명·날인이 생략되어 작성 명의를 확인할 수 없다.",
                            text[max(0, m.start() - 40):m.end() + 20]))
    statement_start = _statement_start(text)
    proximity: List[str] = []
    distance: List[str] = []
    for start, end in sentence_bounds(text):
        sentence = text[start:end]
        # 발췌는 원래 줄 글자를 띄어 이어 붙인다(읽기 본문은 줄바꿈 자리를 붙여 쓴다).
        shown = " ".join(b.text.strip() for b in reading.blocks_between(start, end)) or sentence.strip()
        if LIMITATION_RE.search(sentence) and CERTAINTY_RE.search(sentence):
            out.append(_finding(doc, FindingType.STATEMENT_BEYOND_PERCEPTION, EvidenceGrade.C, Severity.MEDIUM,
                                "지각 범위를 넘는 단정: 지각하지 못했다고 하면서 사실을 확실하다고 한다",
                                "같은 문장에서 보거나 듣지 못했다고 하면서 그 사실을 확실하다고 한다. "
                                "진술의 신빙성은 사람이 판단한다.",
                                shown, status=VerificationStatus.UNVERIFIED,
                                features={"human_review": True, "rule_id": "EVI.BEYOND_PERCEPTION"}))
        if statement_start is not None and start >= statement_start:
            if PROXIMITY_RE.search(sentence):
                proximity.append(shown)
            if DISTANCE_RE.search(sentence):
                distance.append(shown)
    if proximity and distance and proximity[0] != distance[0]:
        out.append(_finding(doc, FindingType.FACT_CONTRADICTION, EvidenceGrade.B, Severity.MEDIUM,
                            "진술 내부 모순: 가까이 있었다는 진술과 떨어져 있었다는 진술이 함께 있다",
                            "같은 진술서 안에서 진술인의 위치를 서로 다르게 적었다. 어느 쪽이 맞는지 사람이 확인한다.",
                            f"{proximity[0]} ↔ {distance[0]}",
                            features={"rule_id": "EVI.STATEMENT_LOCATION_CONFLICT",
                                      "statements": [proximity[0][:200], distance[0][:200]]}))
    for fields in _statement_fields(text):
        for row in exhibits:
            if fields["name"] not in row.get("author", "") or not re.search(r"진술|확인서", row.get("name", "")):
                continue
            listed_ranks = set(RANK_RE.findall(row.get("author", "")))
            listed_units = {(n, u) for n, u in UNIT_RE.findall(row.get("author", ""))}
            differences = []
            if listed_ranks and fields["ranks"] and not (listed_ranks & fields["ranks"]):
                differences.append(f"계급 {'/'.join(sorted(listed_ranks))} ↔ {'/'.join(sorted(fields['ranks']))}")
            same_kind = {u for _, u in listed_units} & {u for _, u in fields["units"]}
            for kind in same_kind:
                left = {n for n, u in listed_units if u == kind}
                right = {n for n, u in fields["units"] if u == kind}
                if left and right and not (left & right):
                    differences.append(f"소속 제{'/'.join(sorted(left))}{kind} ↔ 제{'/'.join(sorted(right))}{kind}")
            if differences:
                out.append(_finding(doc, FindingType.EVIDENCE_PERSON_INCONSISTENT, EvidenceGrade.B, Severity.HIGH,
                                    f"같은 진술인의 인적사항이 다르다({row['label']} {fields['name']}): "
                                    + "; ".join(differences),
                                    "증거 목록의 작성자 기재와 진술서의 소속·계급 기재가 서로 다르다.",
                                    f"목록: {row.get('author')} / 진술서: {fields['raw']}",
                                    features={"exhibit": row["label"], "differences": differences}))
    return out


def check_document(doc: NormalizedDocument) -> List[Finding]:
    exhibits = exhibit_rows(doc)
    return check_exhibits(doc) + check_statements(doc, exhibits)


# --- 서면 간 문장 복사 -------------------------------------------------------------
_QUOTED_RE = re.compile(r"[“\"「『][^”\"」』]{6,}[”\"」』]")
_NORMALIZE_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def _shingles(text: str, n: int = 5) -> set:
    return {text[i:i + n] for i in range(max(0, len(text) - n + 1))}


def _sentences_for_copy(doc: NormalizedDocument) -> List[Tuple[str, str]]:
    text = build_reading_text(doc).text
    out = []
    for start, end in sentence_bounds(text):
        sentence = text[start:end].strip()
        body = _QUOTED_RE.sub("", sentence)  # 판례·법령 인용문은 서면끼리 겹치는 것이 정상이다
        key = _NORMALIZE_RE.sub("", body)
        if len(key) >= COPY_MIN_CHARS:
            out.append((sentence, key))
    return out


def _statement_start(text: str) -> Optional[int]:
    heading = STATEMENT_HEADING_RE.search(text)
    return heading.end() if heading else None


def cross_document_copies(documents: Iterable[NormalizedDocument]) -> List[Finding]:
    """진술서·확인서에 다른 서면의 문장이 그대로 있으면 알린다(대필·작출 의심 단서, 사람 확인).

    같은 대리인의 서면끼리 문장이 겹치는 것은 정상이므로 진술 부분(진술서 제목 줄 뒤)의 문장만 비교한다.
    비교 비용을 줄이려고 다른 서면 문장의 글자 조각 색인에서 후보를 먼저 고른다.
    """
    docs = list(documents)
    texts = {d.document_id: build_reading_text(d).text for d in docs}
    statements = {d.document_id: _statement_start(texts[d.document_id]) for d in docs}
    if not any(start is not None for start in statements.values()):
        return []
    prepared = {d.document_id: _sentences_for_copy(d) for d in docs}
    index: Dict[str, set] = {}
    for d in docs:
        for position, (_, key) in enumerate(prepared[d.document_id]):
            for gram in _shingles(key, 8):
                index.setdefault(gram, set()).add((d.document_id, position))
    by_id = {d.document_id: d for d in docs}
    out: List[Finding] = []
    for owner in docs:
        start = statements[owner.document_id]
        if start is None:
            continue
        pairs: Dict[str, List[Tuple[str, str, float]]] = {}
        for sentence, key in prepared[owner.document_id]:
            if texts[owner.document_id].find(sentence, start) == -1:
                continue
            hits: Dict[Tuple[str, int], int] = {}
            for gram in _shingles(key, 8):
                for hit in index.get(gram, ()):
                    if hit[0] != owner.document_id:
                        hits[hit] = hits.get(hit, 0) + 1
            grams = _shingles(key)
            for (other_id, position), count in hits.items():
                if count < 3:
                    continue
                other_sentence, other_key = prepared[other_id][position]
                other_grams = _shingles(other_key)
                overlap = len(grams & other_grams) / max(1, min(len(grams), len(other_grams)))
                if overlap >= COPY_SIMILARITY:
                    pairs.setdefault(other_id, []).append((sentence, other_sentence, round(overlap, 2)))
        for other_id, matched in pairs.items():
            other = by_id[other_id]
            out.append(_finding(owner, FindingType.CROSS_DOC_COPY, EvidenceGrade.B, Severity.MEDIUM,
                                f"진술 문서에 다른 서면({other.filename})과 같은 문장이 {len(matched)}건 있다",
                                "진술인 명의의 문서에 대리인 서면 등 다른 문서의 문장이 그대로 있으면 대필·작출을 "
                                "의심할 단서가 된다. 작성 경위는 사람이 확인한다.",
                                matched[0][0], status=VerificationStatus.SUSPICIOUS,
                                features={"other_document_id": other_id, "similarity": matched[0][2],
                                          "pairs": [{"statement": a[:200], "other": b[:200], "similarity": s}
                                                    for a, b, s in matched[:5]]}))
    return out
