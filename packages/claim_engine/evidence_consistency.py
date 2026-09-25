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

from .exhibits import exhibit_keys, parse_exhibits, split_items

ENGINE_NAME = "claim_engine.evidence_consistency"


DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[.\-년]\s*(?P<m>\d{1,2})\s*[.\-월]\s*(?P<d>\d{1,2})\s*[.일]?")
STANDALONE_DATE_RE = re.compile(r"^\s*(?:19|20)\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*$")
HEADER_KEYS = {
    "id": ("호증", "증거번호", "증번", "번호", "순번"),
    "name": ("서증명", "증거명", "자료명", "문서명", "표목", "증거방법", "제출자료", "자료"),
    "date": ("작성일", "작성일자", "발급일", "발행일", "일자", "날짜"),
    "author": ("작성자", "작성명의인", "발행", "발급기관", "발급처", "제출자"),
    "purpose": ("입증취지", "입증 취지", "증명취지", "입증사항", "요지"),
    "amount": ("금액", "액수"),
}
MIN_ID_SHARE = 0.6  # 열 내용으로 증거표를 찾을 때: 호증 참조가 있는 행의 비율
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
    서명 줄이 바닥글(대리인 표시)에만 있는 서면은 같은 쪽 바닥글까지 본다.
    """
    blocks = [b for b in doc.body_blocks(include_running_heads=True) if b.block_type not in ("table", "table_line")]
    for index, block in enumerate(blocks):
        if block.block_type == "running_head" or not STANDALONE_DATE_RE.match(block.text or ""):
            continue
        following = [b for b in blocks[index + 1:index + 6] if b.page == block.page]
        prose = [b for b in following if b.block_type != "running_head"][:3]
        heads = [b for b in following if b.block_type == "running_head"]
        if any(SIGNATURE_LINE_RE.search(b.text or "") for b in prose) or (
                len(prose) == 0 and any(SIGNATURE_LINE_RE.search(b.text or "") for b in heads)):
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


def _row(values: Dict[str, Any], ref: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    branches = ref.get("branches") or []
    return {**values, "party": ref["party"], "number": ref["number"], "branches": branches,
            "branch": str(branches[0]) if len(branches) == 1 else None,
            "label": f"{ref['party']} 제{ref['number']}호증" + (f"의 {branches[0]}" if len(branches) == 1 else
                                                              f"의 {branches[0]} 내지 {branches[-1]}" if branches else ""),
            **extra}


def exhibit_rows(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """문서의 호증 목록을 증거마다 한 행으로 읽는다: {id, party, number, branches, name, date, author, purpose}.

    표는 머리글 칸(호증·서증명·작성일…)으로 찾는다. 한 칸에 여러 증거가 묶인 표기('갑 제2, 3호증',
    '갑 제5호증의 1 내지 3')는 호증 문법(exhibits.py)으로 풀어 증거마다 행을 만든다(v5 3-1).
    """
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
        body = cells[1:]
        if "id" not in columns or len(columns) < 3:
            # 표 제목·머리글이 표준과 달라도(양형자료 제출서 등) 열 내용으로 증거표를 알아본다(v5 3-3)
            columns, body = _columns_by_content(cells), cells
            if not columns:
                continue
        for row in body:
            values = {key: _cell(row[index]) if index < len(row) else "" for key, index in columns.items()}
            for ref in parse_exhibits(values.get("id", "")):
                rows.append(_row(values, ref, table_ref=table.get("table_ref"), page=table.get("page")))
    return rows or _exhibit_lines(doc)


def _columns_by_content(cells: List[List[Any]]) -> Dict[str, int]:
    """머리글 없이 열 내용으로 증거표 열을 정한다. 호증 참조가 칸 첫머리에 오는 행이 60% 이상인 열을 번호 열로,
    날짜가 가장 많은 열을 작성일 열로, 번호 열 뒤 첫 글 열을 서증명, 마지막 글 열을 입증취지로 본다."""
    rows = [[_cell(c) for c in row] for row in cells if any(str(c or "").strip() for c in row)]
    if len(rows) < 2:
        return {}
    width = max(len(r) for r in rows)

    def share(index, test):
        values = [r[index] for r in rows if index < len(r) and r[index]]
        return (sum(1 for v in values if test(v)) / len(rows)) if values else 0.0

    def is_ref(value):
        refs = parse_exhibits(value)
        return bool(refs) and refs[0]["span"][0] == 0

    id_col = max(range(width), key=lambda i: share(i, is_ref))
    if share(id_col, is_ref) < MIN_ID_SHARE:
        return {}
    columns = {"id": id_col}
    dates = [(share(i, lambda v: bool(DATE_RE.search(v))), i) for i in range(width) if i != id_col]
    if dates and max(dates)[0] >= 0.5:
        columns["date"] = max(dates)[1]
    text_cols = [i for i in range(width) if i not in columns.values()
                 and share(i, lambda v: bool(re.search(r"[가-힣]{2,}", v))) >= 0.5]
    if not text_cols:
        return {}
    columns["name"] = text_cols[0]
    if len(text_cols) >= 2:
        columns["purpose"] = text_cols[-1]
    if len(text_cols) >= 3:
        columns["author"] = text_cols[1]
    amount = [i for i in range(width) if i not in columns.values() and share(i, lambda v: bool(re.search(r"\d[\d,]{3,}\s*원", v))) >= 0.5]
    if amount:
        columns["amount"] = amount[0]
    return columns


# 목록 줄이 아닌 것: 날짜만 있는 줄, 서명·첨부·당사자 줄, 번호 머리말로 시작하는 새 항목
_NOT_CONTINUATION_RE = re.compile(r"^\s*(?:(?:19|20)\d{2}\s*\.|첨\s*부|위\s|원\s*고|피\s*고|대\s*리\s*인|귀\s*중|"
                                  r"\d{1,2}\s*[.)]|[가-하]\s*[.)]|[①-⑳]|[■□▶-]|입\s*증\s*방\s*법|증\s*거\s*목\s*록)")


def _exhibit_lines(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """표가 없을 때: 문단 첫머리가 호증 번호인 목록(입증방법·증거설명 목록)을 행으로 읽는다.

    - 두 단으로 짠 목록은 한 줄에 증거가 여럿 이어져 읽힌다('갑 제2호증항고장 접수증 갑 제3호증항고결정서'). 줄 안의
      참조마다 나눈다(v5 3-1).
    - 칸 구분이 없으므로 참조 뒤부터 첫 날짜 앞까지를 서증명, 첫 날짜를 작성일, 나머지를 작성자·입증취지로 본다.
    - 긴 서증명이 다음 줄로 넘어가면(참조·날짜 없는 짧은 줄) 앞 행의 서증명에 잇는다.
    """
    rows: List[Dict[str, Any]] = []
    reading = build_reading_text(doc)
    previous_was_item = False
    for paragraph_index, paragraph in enumerate(reading.text.split("\n")):
        stripped = paragraph.strip()
        items = split_items(stripped) if parse_exhibits(stripped[:24]) and parse_exhibits(stripped)[0]["span"][0] == 0 else []
        if not items:
            if (previous_was_item and rows and stripped and len(stripped) <= 40 and not DATE_RE.search(stripped)
                    and not _NOT_CONTINUATION_RE.match(stripped) and not parse_exhibits(stripped)):
                group = rows[-1].get("line_group")
                for row in rows:
                    if row.get("line_group") == group and not row.get("date"):
                        row["name"] = (row["name"] + join_separator(row["name"], stripped) + stripped).strip()
                continue
            previous_was_item = False
            continue
        previous_was_item = True
        for index, (ref, rest) in enumerate(items):
            found = DATE_RE.search(rest)
            name = rest[:found.start()].strip() if found else rest
            tail = rest[found.end():].strip() if found else ""
            rows.append(_row({"id": ref["label"], "name": name, "date": found.group(0) if found else "",
                              "author": tail, "purpose": tail}, ref, table_ref=None, page=None, from_lines=True,
                             line_group=(paragraph_index, ref["span"])))
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
        # 사건을 기록·증명하는 서증(분석·보고·진술·확인·의료·조서 등)은 그 사건보다 먼저 작성될 수 없다(G5).
        # 사건일은 입증취지·서증명의 날짜, 없으면 본문의 사고·사건 날짜를 쓴다.
        if EVENT_RECORD_KINDS.search(row.get("name", "")):
            later = [d for d in _all_dates(described) if d > parsed]
            if not later and EVENT_WORDS.search(described):
                later = [d for d in incident_dates(doc) if d > parsed]
            if later:
                event = max(later) if _all_dates(described) else min(later)
                out.append(_finding(doc, FindingType.EVIDENCE_TIMELINE_INVERSION, EvidenceGrade.B, Severity.HIGH,
                                    f"사건을 기록·증명하는 서증의 작성일이 그 사건보다 앞선다: {where} 작성일 "
                                    f"{_k(parsed)}, 대상 {_k(event)}",
                                    "입증하려는 사건이 일어나기 전에 그 사건을 기록·증명한 문서가 작성되었다고 적혀 있다.",
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
    out.extend(_attached_originals(doc, rows))
    out.extend(_attached_amounts(doc, rows))
    return out


def _attached_amounts(doc: NormalizedDocument, rows: List[Dict[str, Any]]) -> List[Finding]:
    """증거목록의 금액과 같은 파일에 붙은 원문 사본(첨부 … 사본)의 금액을 대조한다(v4 P4)."""
    from .calculation import parse_amounts
    from .fact_store import digit_transposition, segments

    copies = [(re.sub(r"\s|첨부|사본|원본|[()\[\]【】]", "", name), blocks) for name, blocks in segments(doc)[1:]]
    out: List[Finding] = []
    for row in rows:
        listed = parse_amounts(row.get("amount") or "")
        name = re.sub(r"\s", "", row.get("name") or "")
        if not listed or not name:
            continue
        for title, blocks in copies:
            if not title or (title not in name and name not in title):
                continue
            original = parse_amounts(build_reading_text(doc, blocks).text)
            if not original or any(a.value == listed[0].value for a in original):
                break
            where = f"{row['label']} {row.get('name', '')}".strip()
            transposed = any(digit_transposition(str(listed[0].value), str(a.value)) for a in original)
            out.append(_finding(doc, FindingType.EVIDENCE_LIST_MISMATCH, EvidenceGrade.A, Severity.HIGH,
                                f"증거목록 금액과 첨부 원문의 금액이 다르다: {where} — 목록 {listed[0].raw}, 원문 "
                                f"{original[0].raw}" + (" (자릿수 뒤바뀜 의심)" if transposed else ""),
                                "같은 파일 안의 증거목록과 첨부 원문 사본이 금액을 다르게 적었다. 원본을 확인해야 한다.",
                                f"{where} | 목록: {listed[0].raw} | 원문: {original[0].raw}", page=row.get("page"),
                                features={"rule_id": "EVI.LIST_AMOUNT_MISMATCH", "defect_code": "LIST_AMOUNT_MISMATCH",
                                          "exhibit": row["label"], "list_amount": str(listed[0].value),
                                          "original_amounts": [str(a.value) for a in original[:5]],
                                          "digit_transposition": transposed}))
            break
    return out


EVENT_RECORD_KINDS = re.compile(r"분석|보고서|감정|진술|확인서|경위서|소견|조사|진단서|의무기록|진료기록|진료비|영수증|"
                                r"조서|증명서|사실조회|사고\s*사실")
EVENT_WORDS = re.compile(r"사고|사건|폭행|상해|부상|피해|경위|치료|입원|발생")
ORG_RE = re.compile(r"[가-힣○△□A-Za-z]{1,20}(?:대학교병원|병원|의원|한의원|치과|보건소|경찰서|검찰청|법원|청|구청|시청|군청|"
                    r"센터|공단|공사|위원회|협회|주식회사|은행|보험)")
ISSUER_LINE_RE = re.compile(r"(?:발행|발급|작성)\s*(?:기관|처|자)?\s*[:：]\s*(?P<org>[^\n]{2,40})|(?P<head>[^\n]{2,30}(?:병원|의원)장)")


def incident_dates(doc: NormalizedDocument) -> List[date]:
    """본문이 사고·사건이 일어난 날로 적은 날짜(사실 저장소의 추출 기준과 같다).

    '사고' 낱말이 든 문장의 모든 날짜를 쓰면 시효 만료일·사고경위서 작성일까지 사건일로 잡힌다. 날짜 바로 뒤에
    사고 서술이 오거나 '사고일·범행일' 바로 뒤에 온 날짜만 쓴다.
    """
    from .fact_store import incident_dates as stated_incident_dates
    return [date.fromisoformat(value) for value in stated_incident_dates(doc)]


def _org_key(text: str) -> str:
    return re.sub(r"[\s○△□()（）㈜]|주식회사", "", text or "")


def _attached_originals(doc: NormalizedDocument, rows: List[Dict[str, Any]]) -> List[Finding]:
    """같은 파일에 붙은 원문(진단서 등)의 발급기관을 증거목록의 작성자와 대조한다(G5)."""
    text = build_reading_text(doc).text
    lines = text.split("\n")
    out: List[Finding] = []
    for row in rows:
        author, name = row.get("author") or "", re.sub(r"\s", "", row.get("name") or "")
        if not name or not ORG_RE.search(author):
            continue
        for index, line in enumerate(lines):
            if re.sub(r"\s", "", line) != name:
                continue  # 원문 첫머리의 제목 줄(예: '진 단 서')
            window = "\n".join(lines[index + 1:index + 25])
            issuers = [m.group("org") or m.group("head") for m in ISSUER_LINE_RE.finditer(window)]
            issuers = [ORG_RE.search(i).group(0) for i in issuers if i and ORG_RE.search(i)]
            if issuers and not any(_org_key(i) in _org_key(author) or _org_key(author) in _org_key(i)
                                   for i in issuers):
                where = f"{row['label']} {row.get('name', '')}".strip()
                out.append(_finding(doc, FindingType.EVIDENCE_LIST_MISMATCH, EvidenceGrade.B, Severity.MEDIUM,
                                    f"증거목록의 작성자와 첨부 원문의 발급기관이 다르다: {where} — 목록 '{author}', "
                                    f"원문 '{issuers[0]}'",
                                    "같은 파일 안의 증거목록과 첨부 원문이 발급기관을 다르게 적었다. 원본을 확인해야 한다.",
                                    f"{where} | 목록: {author} | 원문: {issuers[0]}", page=row.get("page"),
                                    features={"exhibit": row["label"], "list_author": author,
                                              "original_issuer": issuers[0]}))
            break
    return out


def _numbering(doc: NormalizedDocument, rows: List[Dict[str, Any]]) -> List[Finding]:
    out: List[Finding] = []
    # 같은 호증 번호(가지번호까지 같음)가 목록에 두 번 이상 나온다(v4 P4)
    seen: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in rows:
        keys = [(row["party"], row["number"], b) for b in row.get("branches") or []] or [(row["party"], row["number"], None)]
        for key in keys:
            seen.setdefault(key, []).append(row)
    for (party, number, branch), same in seen.items():
        if len(same) < 2:
            continue
        label = f"{party} 제{number}호증" + (f"의 {branch}" if branch else "")
        names = ", ".join(r.get("name") or "(이름 없음)" for r in same)
        out.append(_finding(doc, FindingType.EVIDENCE_LIST_MISMATCH, EvidenceGrade.A, Severity.MEDIUM,
                            f"같은 호증 번호가 두 번 쓰였다: {label} — {names}",
                            "증거 목록에서 한 번호를 서로 다른 증거(또는 같은 증거)에 두 번 붙였다. 어느 증거를 가리키는지 "
                            "특정할 수 없으므로 번호를 바로잡아야 한다.", f"{label}: {names}",
                            features={"rule_id": "EVI.EVIDENCE_NUMBER_DUPLICATE",
                                      "defect_code": "EVIDENCE_NUMBER_DUPLICATE", "exhibit": label,
                                      "names": [r.get("name") for r in same]}))
    listed: Dict[str, set] = {}
    for row in rows:
        listed.setdefault(row["party"], set()).add(row["number"])
    # 가지번호: '의 2'만 있고 '의 1'이 없으면 결번이다(G5). 범위 표기('의 1 내지 3')는 모두 있는 것으로 본다.
    branches: Dict[tuple, set] = {}
    for row in rows:
        if row.get("branches"):
            branches.setdefault((row["party"], row["number"]), set()).update(row["branches"])
    for (party, number), present in sorted(branches.items()):
        missing = [b for b in range(1, max(present) + 1) if b not in present]
        if missing:
            labels = ", ".join(f"{party} 제{number}호증의 {b}" for b in missing)
            out.append(_finding(doc, FindingType.EVIDENCE_NUMBERING_GAP, EvidenceGrade.B, Severity.MEDIUM,
                                f"가지번호가 비어 있다: {labels} 결번",
                                "같은 호증의 가지번호가 1부터 이어지지 않는다. 누락된 증거가 있는지 확인해야 한다.",
                                ", ".join(f"{party} 제{number}호증의 {b}" for b in sorted(present)),
                                features={"party": party, "number": number, "missing_branches": missing}))
    for party, numbers in listed.items():
        gaps = [n for n in range(1, max(numbers) + 1) if n not in numbers]
        if gaps:
            out.append(_finding(doc, FindingType.EVIDENCE_NUMBERING_GAP, EvidenceGrade.B, Severity.MEDIUM,
                                f"호증 번호가 비어 있다: {party} 제{', '.join(map(str, gaps))}호증 결번",
                                "증거 목록의 번호가 연속하지 않는다. 누락된 증거가 있는지 확인해야 한다.",
                                ", ".join(f"{party} 제{n}호증" for n in sorted(numbers)),
                                features={"party": party, "missing": gaps}))
    text = build_reading_text(doc).text
    mentioned = exhibit_keys(text)
    missing = sorted((p, n) for p, n in mentioned if p in listed and n not in listed[p])
    if missing:
        labels = ", ".join(f"{p} 제{n}호증" for p, n in missing)
        out.append(_finding(doc, FindingType.EVIDENCE_LIST_MISMATCH, EvidenceGrade.B, Severity.MEDIUM,
                            f"본문이 언급한 증거가 증거 목록에 없다: {labels}",
                            "본문에서 입증 근거로 든 호증이 증거 목록에 없다.", labels,
                            features={"missing_from_list": [f"{p} 제{n}호증" for p, n in missing]}))
    return out


# --- 진술서 ------------------------------------------------------------------------
# 사람 이름: 가명 표기(성 + ○○) 또는 2~4글자 실명. 목록의 작성자 칸에서 사람 이름 하나만 있을 때 쓴다.
PERSON_NAME_RE = re.compile(r"(?<![가-힣])([가-힣])([○△□＊*]{1,3})(?![가-힣○△□＊*])")


def _statement_fields(text: str) -> List[Dict[str, Any]]:
    out = []
    for m in NAME_FIELD_RE.finditer(text):
        window = text[m.end():m.end() + 160]
        affiliation = AFFILIATION_FIELD_RE.search(window)
        value = affiliation.group("value") if affiliation else ""
        # 진술서 앞 300자 안의 가장 가까운 호증 표시('[갑 제6호증]')로 목록의 어느 행인지 정한다
        before = parse_exhibits(text[max(0, m.start() - 300):m.start()])
        out.append({"name": m.group("name"), "ranks": set(RANK_RE.findall(value)),
                    "units": {(n, u) for n, u in UNIT_RE.findall(value)}, "raw": value.strip(),
                    "exhibit": (before[-1]["party"], before[-1]["number"]) if before else None})
    return out


def _surname_conflict(listed_author: str, stated_name: str) -> Optional[str]:
    """목록 작성자 칸의 가명(성 + ○○)과 진술서 성명의 성이 다르면 두 표기를 돌려준다. 같은 가림 길이만 비교한다."""
    listed = PERSON_NAME_RE.findall(listed_author or "")
    stated = PERSON_NAME_RE.fullmatch(stated_name or "")
    if len(listed) != 1 or not stated:
        return None
    surname, mask = listed[0]
    if len(mask) != len(stated.group(2)) or surname == stated.group(1):
        return None
    return f"{surname}{mask} ↔ {stated_name}"


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
            # 같은 호증(진술서 앞 호증 표시)인데 성이 다르면 작성 명의가 다르다(v5 3-3)
            if fields.get("exhibit") == (row["party"], row["number"]):
                conflict = _surname_conflict(row.get("author", ""), fields["name"])
                if conflict:
                    out.append(_finding(doc, FindingType.EVIDENCE_PERSON_INCONSISTENT, EvidenceGrade.B, Severity.HIGH,
                                        f"증거 목록의 작성자와 첨부 문서의 성명이 다르다({row['label']}): {conflict}",
                                        "같은 호증의 작성자를 증거 목록과 첨부 문서가 서로 다른 사람으로 적었다(성이 다름).",
                                        f"목록: {row.get('author')} / 첨부: 성명 {fields['name']}",
                                        features={"rule_id": "EVI.PERSON_NAME_MISMATCH", "exhibit": row["label"],
                                                  "listed": row.get("author"), "stated": fields["name"]}))
                    continue
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
