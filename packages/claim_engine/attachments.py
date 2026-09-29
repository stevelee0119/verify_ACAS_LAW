"""첨부자료·증거 목록과 해시 기재값 대조.

문서가 근거로 든 자료(첨부 목록 표, 본문의 "갑 제N호증"·"별지 N", "첨부되지 않았다"는
진술)를 모으고, 실제로 함께 입력된 파일과 대조해 자료마다 상태를 매긴다.

상태
  ATTACHED           같은 실행에 입력된 파일과 이름이 대응한다
  NOT_PROVIDED       문서 스스로 첨부·제출하지 않았다고 밝혔다(허위·위조의 근거가 아니다)
  REFERENCE_MISSING  문서는 첨부·제출했다고 하거나 증거번호로 인용했으나 입력 파일에 없다
  UNVERIFIED         첨부 여부를 판단할 단서가 없다

해시 판단은 서로 다른 세 가지로 나눈다.
  format   기재값이 주장한 알고리즘의 형식에 맞는가 (SHA-256은 16진수 64자)
  compare  실제 파일이 있을 때만 파일 바이트의 해시와 비교한다
  원본성·작성자·수집경위는 해시로 확인되지 않는다. 해시가 일치해도 진정성립이나 내용의
  진실성을 보증하지 않는다.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument

from .exhibits import parse_exhibit_label

ENGINE_NAME = "claim_engine.attachments"

NOT_PROVIDED_RE = re.compile(
    r"(첨부(?:되지|하지)\s*(?:않|아니)|미\s*첨부|제출(?:되지|하지)\s*(?:않|아니)|미\s*제출|"
    r"포함(?:되지|하지)\s*(?:않|아니)|누락(?:되었|됐|하였|했)|별도\s*제출\s*예정|추후\s*제출|없음|not\s+attached|not\s+provided)",
    re.IGNORECASE,
)
ATTACHED_STATUS_RE = re.compile(r"^(첨부|제출|있음|o|○|◯|y|yes|첨부함|제출함)$", re.IGNORECASE)
MISSING_STATUS_RE = re.compile(r"(미\s*첨부|미\s*제출|없음|^x$|^×$|^-$|^n$|^no$|첨부\s*안\s*됨|제출\s*안\s*됨|추후)",
                               re.IGNORECASE)
NAME_HEADER_RE = re.compile(r"(서증명|자료명|증거명|문서명|서류명|첨부\s*자료|증거\s*자료|명칭|자료)")
STATUS_HEADER_RE = re.compile(r"(첨부\s*여부|제출\s*여부|첨부|제출|비고|상태|여부)")
ID_HEADER_RE = re.compile(r"(번호|증거번호|호증|순번|no\.?)", re.IGNORECASE)
LIST_ITEM_RE = re.compile(
    r"^\s*(?:[-•·※]\s*)?(?P<label>(?:첨부|별지|별첨|붙임)\s*(?:자료)?\s*(?:제?\s*\d+\s*호?)?|(?:갑|을)\s*제?\s*\d+\s*호증(?:의\s*\d+)?)"
    r"\s*[:.)\-]?\s*(?P<name>[^\n]{2,80})$"
)
EVIDENCE_NOUN_RE = re.compile(
    r"(?P<name>[가-힣A-Za-z0-9·()\s]{0,16}?(?:녹음\s*파일|녹취록|파일|보고서|점수표|사진|영상|확인서|진술서|계약서|"
    r"영수증|내역서|기록|대장|문자메시지|메시지|캡처|원본|사본))"
)
HASH_RE = re.compile(
    r"(?P<algo>(?:(?:해시(?:값)?|hash)\s*[:：=]\s*)?(?:SHA[-\s]?256|SHA[-\s]?1|MD5)|해시(?:값)?|hash)\s*(?:값)?\s*(?:은|는|:|：|=)?\s*"
    r"[\"'“]?(?P<value>[0-9A-Za-z][0-9A-Za-z\-_]{5,127})",
    re.IGNORECASE,
)
FORMATS = {"SHA256": 64, "SHA1": 40, "MD5": 32}


def _norm(text: str) -> str:
    return re.sub(r"[\s·()\[\]「」『』\"'_.\-]", "", unicodedata.normalize("NFKC", text or "")).lower()


def _algorithm(label: str, context: str) -> str:
    joined = f"{label} {context}".upper().replace(" ", "").replace("-", "")
    for name in ("SHA256", "SHA1", "MD5"):
        if name in joined:
            return name
    return "UNSPECIFIED"


def hash_check(value: str, algorithm: str, file_digest: Optional[str]) -> Dict[str, Any]:
    """형식 판정과 파일 대조를 따로 한다. 파일이 없으면 불일치·위조로 단정하지 않는다."""
    compact = value.strip()
    is_hex = bool(re.fullmatch(r"[0-9a-fA-F]+", compact))
    expected = FORMATS.get(algorithm)
    if expected:
        format_status = "FORMAT_OK" if is_hex and len(compact) == expected else "FORMAT_INVALID"
    else:  # 알고리즘을 밝히지 않았으면 흔한 길이(64·40·32)의 16진수만 형식상 가능하다고 본다
        format_status = "FORMAT_OK" if is_hex and len(compact) in FORMATS.values() else "FORMAT_INVALID"
    if file_digest is None:
        comparison, note = "NO_FILE", "실제 파일이 입력되지 않아 대조할 수 없다"
    elif format_status != "FORMAT_OK" or (algorithm not in ("SHA256", "UNSPECIFIED")):
        comparison, note = "NOT_COMPARABLE", "기재값 형식이 맞지 않거나 SHA-256이 아니어서 파일과 비교하지 않았다"
    elif compact.lower() == file_digest.lower():
        comparison, note = "MATCH", "파일 바이트의 SHA-256과 일치한다(진정성립·내용 진실성의 증명은 아님)"
    else:
        comparison, note = "MISMATCH", "파일 바이트의 SHA-256과 다르다"
    reason = {
        "FORMAT_INVALID": f"'{compact}'는 {algorithm if expected else 'SHA-256 등'} 형식(16진수 "
                          f"{expected or '64·40·32'}자)이 아니다",
        "FORMAT_OK": "형식은 맞다",
    }[format_status]
    return {"claimed_value": compact, "algorithm": algorithm, "format_status": format_status,
            "format_note": reason, "comparison": comparison, "comparison_note": note,
            "authenticity": "NOT_ESTABLISHED_BY_HASH"}


def _uploaded_match(name: str, uploads: List[Dict[str, Any]], exclude: Optional[str]) -> Optional[Dict[str, Any]]:
    key = _norm(name)
    if len(key) < 2:
        return None
    for upload in uploads:
        if upload.get("document_id") == exclude:
            continue
        stem = _norm(re.sub(r"\.[A-Za-z0-9]{1,5}$", "", upload.get("filename") or ""))
        if stem and (key in stem or stem in key):
            return upload
    return None


def _table_items(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """첨부·증거 목록 표에서 행마다 (자료명, 첨부 여부)를 읽는다. 행·열 관계를 그대로 쓴다."""
    items = []
    tables = list(doc.structure.get("tables") or [])
    known = {t.get("table_ref") for t in tables}
    for block in doc.blocks:  # 표 블록만 있고 structure에 없는 예전 파서 결과도 읽는다
        if block.block_type == "table" and block.attributes.get("table_ref") not in known:
            tables.append({"table_ref": block.attributes.get("table_ref") or block.block_id, "page": block.page,
                           "cells": block.attributes.get("cells") or [], "title": None})
    for table in tables:
        rows = table.get("cells") or []
        if len(rows) < 2:
            continue
        header = [str(c or "") for c in rows[0]]
        name_col = next((i for i, h in enumerate(header) if NAME_HEADER_RE.search(h)), None)
        status_col = next((i for i, h in enumerate(header) if i != name_col and STATUS_HEADER_RE.search(h)), None)
        id_col = next((i for i, h in enumerate(header) if i not in (name_col, status_col) and ID_HEADER_RE.search(h)), None)
        if name_col is None:
            continue
        for row_index, row in enumerate(rows[1:], start=1):
            cells = [str(c or "").strip() for c in row]
            name = cells[name_col] if name_col < len(cells) else ""
            if not name:
                continue
            status_text = cells[status_col] if status_col is not None and status_col < len(cells) else ""
            items.append({"name": name, "reference": cells[id_col] if id_col is not None and id_col < len(cells) else None,
                          "source": "TABLE", "table_ref": table.get("table_ref"), "table_title": table.get("title"),
                          "row": row_index, "columns": {"name": header[name_col],
                                                        "status": header[status_col] if status_col is not None else None},
                          "stated_status": status_text, "page": table.get("page"), "row_cells": cells})
    return items


NUMBERING_RE = re.compile(r"^\s*(?:\d{1,2}\s*[.)]\s*|[-•·※]\s*)?")


def _exhibit_table_items(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """호증 목록 표(서증명·작성일 등 칸)가 있으면 셀 단위로 자료명을 읽는다(v3 D6)."""
    from .evidence_consistency import exhibit_rows

    items = []
    for row in exhibit_rows(doc):
        if row.get("from_lines") or not row.get("name"):
            continue
        items.append({"name": " ".join(row["name"].split()), "reference": row.get("label"), "source": "TABLE",
                      "table_ref": row.get("table_ref"), "page": row.get("page"),
                      "stated_status": " ".join(str(row.get(k) or "") for k in ("label", "name", "date")).strip()})
    return items


# [첨부자료], [첨부서류] 등 첨부 목록 표제어 인식
ATTACHMENT_SECTION_HEADER_RE = re.compile(
    r"^\s*[\[【(]?\s*(?:첨부|별지|별첨|붙임)\s*(?:자료|서류|목록|서류\s*등)?\s*[\]】)]?\s*$"
)


def _line_items(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    items = []
    in_attachment_section = False
    # A DOCX paragraph may contain the entire numbered list as line breaks.
    lines = [(block, line.strip()) for block in doc.prose_blocks() for line in block.text.splitlines()]
    for block, text in lines:
        # [첨부자료], [첨부서류] 등 섹션 헤더 단독 줄은 첨부 아이템으로 잡지 않고 첨부 목록 모드로 전환
        if ATTACHMENT_SECTION_HEADER_RE.match(text):
            in_attachment_section = True
            continue
        # 청구원인, 청구취지 등 새로운 주요 구역이 시작되면 첨부 섹션 종료
        if in_attachment_section and re.match(r"^[\[【(]?(?:청구\s*취지|청구\s*원인|이\s*유|결\s*론|별지|별첨|붙임)[\]】)]?", text):
            in_attachment_section = False

        body = NUMBERING_RE.sub("", text, count=1)
        exhibit = parse_exhibit_label(body) if body.startswith(("갑", "을", "병", "정", "증", "피고인", "검사")) else None
        if exhibit and exhibit["span"][0] == 0 and len(_norm(exhibit["name"])) >= 2:
            items.append({"name": exhibit["name"], "reference": exhibit["label"], "source": "LIST",
                          "page": block.page, "block_id": block.block_id, "stated_status": text,
                          "branches": exhibit["branches"]})
            continue
        m = LIST_ITEM_RE.match(text)
        if m:
            name_cand = m.group("name").strip()
            if re.match(r"(?:위|본|해당)\s*(?:서증|자료|첨부|문서)", name_cand):
                continue
            if ATTACHMENT_SECTION_HEADER_RE.match(name_cand):
                continue
            items.append({"name": name_cand, "reference": " ".join(m.group("label").split()),
                          "source": "LIST", "page": block.page, "block_id": block.block_id,
                          "stated_status": text})
            continue

        # Numbered merits paragraphs are not evidence-list entries.
        num_m = re.match(r"^\s*(?P<num>\d{1,2})\s*[.)]\s*(?P<name>[^\n]{2,80})$", text)
        if num_m and in_attachment_section:
            items.append({
                "name": num_m.group("name").strip(),
                "reference": f"첨부 {num_m.group('num')}",
                "source": "LIST",
                "page": block.page,
                "block_id": block.block_id,
                "stated_status": text,
            })
    return items


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=다)\s*\.\s*|\n", text) if s.strip()]


def _statement_items(doc: NormalizedDocument) -> List[Dict[str, Any]]:
    """본문에서 '…은 첨부되지 않았다' 같은 진술과 그 대상 자료를 찾는다."""
    items = []
    for block in doc.prose_blocks():
        for sentence in _sentences(block.text):
            if not NOT_PROVIDED_RE.search(sentence) or not re.search(r"첨부|제출|자료|증거|파일", sentence):
                continue
            names = [" ".join(m.group("name").split()) for m in EVIDENCE_NOUN_RE.finditer(sentence)]
            for name in dict.fromkeys(n for n in names if len(_norm(n)) >= 2):
                name = re.sub(r"^(?:및|또는)\s+", "", name).strip()
                if re.fullmatch(r"(?:본|원본|사본|해당|위|증거|서증)\s*(?:파일|자료)", name):
                    continue
                items.append({"name": name, "source": "STATEMENT", "page": block.page,
                              "block_id": block.block_id, "stated_status": sentence.strip()[:200]})
    return items


def _inline_key(name: str) -> str:
    # '별지 자료: 전자우편 발췌' 등 접두·접미 표현을 정규화하여 항목명과 인라인 구획 매칭 보장
    cleaned = re.sub(r"^(?:첨부|별지|별첨|붙임)(?:\s*(?:자료|서류|목록))?\s*\d*\s*[:.)]?", "", name or "")
    cleaned = re.sub(r"사본|원본|발췌|\d+\s*부\s*$|[()\[\]【】:·\s]", "", cleaned)
    return _norm(cleaned)


def _inline_sections(doc):
    """Require actual content after an appendix heading, never a list heading."""
    from .fact_store import ATTACHED_HEAD_RE

    sections, current = [], None
    for block in doc.prose_blocks():
        offset = 0
        for raw in block.text.splitlines(keepends=True):
            text = raw.strip()
            start = offset + len(raw) - len(raw.lstrip())
            offset += len(raw)
            if ATTACHMENT_SECTION_HEADER_RE.fullmatch(text):
                current = None
            elif ATTACHED_HEAD_RE.match(text) and len(text) <= 80:
                current = {"name": text, "body": [], "source_refs": []}
                sections.append(current)
            elif re.fullmatch(r"[\[【(]?(?:청구\s*취지|청구\s*원인|이\s*유|결\s*론)[\]】)]?", text):
                current = None
            elif current is not None and text:
                current["body"].append(text)
                current["source_refs"].append({"document_id": doc.document_id, "sha256": doc.sha256,
                    "block_id": block.block_id, "page": block.page, "span": [start, start + len(text)]})
    return sections



def analyze_attachments(doc: NormalizedDocument, uploads: Iterable[Dict[str, Any]] = (),
                        claims: Iterable[Any] = ()) -> Dict[str, Any]:
    """첨부 목록·본문 인용·입력 파일을 대조한 결과와 finding을 만든다."""
    uploads = list(uploads)
    raw = _table_items(doc) + _exhibit_table_items(doc) + _line_items(doc) + _statement_items(doc)
    merged: Dict[str, Dict[str, Any]] = {}
    references = {}
    for item in raw:
        key = _norm(item["name"])
        ref = _norm(item.get("reference") or "")
        target = references.get(ref) if ref else None
        target = target or merged.get(key)
        if target is None:
            merged[key] = {**item, "mentions": [dict(item)]}
            if ref:
                references[ref] = merged[key]
        else:
            target["mentions"].append(dict(item))
            for field_name in ("reference", "table_ref", "row", "columns", "table_title"):
                target.setdefault(field_name, item.get(field_name))
                if target.get(field_name) is None:
                    target[field_name] = item.get(field_name)
    text = doc.visible_text
    inline = {}
    inline_by_num = {}
    for section in _inline_sections(doc):
        name, body = section["name"], section["body"]
        if not body:
            continue
        # A bare numbered heading followed only by a title is still not a copy.
        if re.fullmatch(r"[\[【(]?(?:별지|별첨|붙임)\s*\d+[\]】)]?", name) and len(body) < 2:
            continue
        k = _inline_key(name)
        if k:
            inline[k] = section
        if body:
            first_text = body[0]
            k_first = _inline_key(first_text)
            if k_first:
                inline[k_first] = section
            k_comb = _inline_key(f"{name} {first_text}")
            if k_comb:
                inline[k_comb] = section
        # 별지/별첨 번호(예: 별지 1, 별지 2) 추출 및 등록
        num_m = re.search(r"(?:별지|별첨|붙임)\s*(\d+)", name)
        if num_m:
            inline_by_num[num_m.group(1)] = section

    items = []
    for key, item in merged.items():
        upload = _uploaded_match(item["name"], uploads, doc.document_id)
        stated = " ".join(m.get("stated_status") or "" for m in item["mentions"])
        table_status = next((m.get("stated_status") for m in item["mentions"] if m["source"] == "TABLE"), "")
        copy = inline.get(_inline_key(item["name"]))
        if not copy:
            # 항목명과 인라인 구획 표제 간의 상호 부분 매칭 지원 (예: '전자우편발췌' <-> '전자우편')
            item_k = _norm(item["name"])
            for sec_k, sec in inline.items():
                if item_k and (item_k in sec_k or sec_k in item_k):
                    copy = sec
                    break
        if not copy:
            # 별지 번호로도 인라인 구획 대조
            item_num_m = re.search(r"(?:별지|별첨|붙임)\s*(\d+)",
                                   (item.get("reference") or "") + " " + item["name"])
            if item_num_m and item_num_m.group(1) in inline_by_num:
                copy = inline_by_num[item_num_m.group(1)]

        if upload:
            status, basis = "ATTACHED", f"입력 파일 '{upload.get('filename')}'과 이름이 대응한다"
        elif copy:
            status, basis = "ATTACHED", f"같은 문서 안에 사본·별지 본문이 있다('{copy['name']}')"
        elif any(m["source"] == "STATEMENT" for m in item["mentions"]) or (
                table_status and MISSING_STATUS_RE.search(table_status)) or NOT_PROVIDED_RE.search(stated):
            status, basis = "NOT_PROVIDED", "문서 스스로 첨부·제출하지 않았다고 밝혔다"
        elif table_status and ATTACHED_STATUS_RE.match(table_status.strip()):
            status, basis = "REFERENCE_MISSING", "목록에는 첨부했다고 되어 있으나 입력 파일에서 찾지 못했다"
        elif item.get("reference") or item["source"] in ("LIST", "TABLE"):
            status, basis = "REFERENCE_MISSING", "첨부·증거로 적혀 있으나 입력 파일에서 찾지 못했다"
        else:
            status, basis = "UNVERIFIED", "첨부 여부를 판단할 단서가 부족하다"

        linked = [c.claim_id for c in claims
                  if _norm(item["name"]) and _norm(item["name"]) in _norm(getattr(c, "text", ""))]
        items.append({"name": item["name"], "reference": item.get("reference"), "status": status, "basis": basis,
                      "sources": sorted({m["source"] for m in item["mentions"]}),
                      "table_ref": item.get("table_ref"), "table_title": item.get("table_title"),
                      "row": item.get("row"), "columns": item.get("columns"),
                      "page": item.get("page"), "linked_claim_ids": linked,
                      "uploaded_document_id": upload.get("document_id") if upload else None,
                      "availability_detail": ("UPLOADED_FILE" if upload else "INLINE_CONTENT_PRESENT" if copy else status),
                      "authenticity": "UNVERIFIED",
                      "source_refs": copy["source_refs"] if copy and not upload else [],
                      "mentions": item["mentions"][:5]})
    hashes = []
    for m in HASH_RE.finditer(text):
        start = max(text.rfind("\n", 0, m.start()) + 1, m.start() - 160)
        window = text[start:m.end() + 40]
        algorithm = _algorithm(m.group("algo"), window)
        owner = next((i for i in items if i.get("reference") and _norm(i["reference"]) in _norm(window)), None)
        if owner is None:
            matches = [i for i in items if _norm(i["name"]) and _norm(i["name"]) in _norm(window)]
            owner = matches[0] if len(matches) == 1 else None
        upload = next((u for u in uploads if owner and u.get("document_id") == owner.get("uploaded_document_id")), None)
        check = hash_check(m.group("value"), algorithm, upload.get("sha256") if upload else None)
        check.update(excerpt=" ".join(window.split()), related_item=owner["name"] if owner else None,
                     related_reference=owner.get("reference") if owner else None)
        hashes.append(check)
        if owner is not None:
            owner["hash"] = check
    findings = _findings(doc, items, hashes)
    return {"items": items, "hashes": hashes, "findings": findings,
            "summary": {status: sum(1 for i in items if i["status"] == status)
                        for status in ("ATTACHED", "NOT_PROVIDED", "REFERENCE_MISSING", "UNVERIFIED")}}


def _missing_notice(doc: NormalizedDocument, missing: List[Dict[str, Any]]) -> Finding:
    """증거 파일을 함께 올리지 않은 실행: 문서당 INFO 알림 1건(v3 D6). 목록은 features와 근거에 싣는다."""
    listing = [f"{i.get('reference') or ''} {i['name']}".strip() for i in missing]
    return Finding.create(
        type=FindingType.EVIDENCE_REFERENCE_MISSING, status=VerificationStatus.UNVERIFIED, severity=Severity.INFO,
        evidence_grade=EvidenceGrade.C, title=f"첨부 증거 {len(missing)}건이 입력에 없음 — 목록 보기",
        detail=("이번 실행에는 증거 파일이 함께 입력되지 않아 첨부 자료와 대조하지 않았다(미제출 상태). 목록: "
                + "; ".join(listing[:30]) + (f" 외 {len(listing) - 30}건" if len(listing) > 30 else "")
                + ". 내용 불일치(모순)가 아니며 자료 미제출로 인한 미확인이다. 자료가 없다는 사실만으로 주장이 허위이거나 자료가 위조되었다고 판단하지 않는다."),
        document_id=doc.document_id, engine=ENGINE_NAME,
        confidence_features={"attachment_status": "NOT_UPLOADED", "missing_items": listing,
                             "rule_id": "EVI.ATTACHMENTS_NOT_UPLOADED", "evidence_state": "NOT_UPLOADED"},
        tags=["EVIDENCE", "ATTACHMENT", "MISSING_EVIDENCE"],
        evidence=[Evidence.create(description="입력되지 않은 첨부 증거 목록", grade=EvidenceGrade.C,
                                  document_id=doc.document_id, excerpt="; ".join(listing)[:300])])


def _findings(doc: NormalizedDocument, items: List[Dict[str, Any]], hashes: List[Dict[str, Any]]) -> List[Finding]:
    out: List[Finding] = []
    evidence_uploaded = any(i["status"] == "ATTACHED" for i in items)
    missing = [i for i in items if i["status"] == "REFERENCE_MISSING"]
    if missing and not evidence_uploaded:
        out.append(_missing_notice(doc, missing))
    for item in items:
        if item["status"] not in ("NOT_PROVIDED", "REFERENCE_MISSING"):
            continue
        if item["status"] == "REFERENCE_MISSING" and not evidence_uploaded:
            continue  # 증거 파일을 함께 올린 실행에서만 자료별로 대조한다
        provided = item["status"] == "NOT_PROVIDED"
        out.append(Finding.create(
            type=FindingType.EVIDENCE_NOT_PROVIDED if provided else FindingType.EVIDENCE_REFERENCE_MISSING,
            status=VerificationStatus.UNVERIFIED, severity=Severity.LOW, evidence_grade=EvidenceGrade.C,
            title=(f"근거 자료가 입력되지 않음(문서가 미첨부를 밝힘): {item['name']}" if provided
                   else f"첨부·증거로 적힌 자료를 입력 파일에서 찾지 못함: {item['name']}"),
            detail=(f"{item['basis']}. 이 자료에 기댄 사실 주장은 미제출로 인하여 검증되지 않은 사실(내용 불일치가 아닌 미제출)로 남는다. "
                    "자료가 없다는 사실만으로 주장이 허위이거나 자료가 위조되었다고 판단하지 않는다."),
            document_id=doc.document_id, page=item.get("page"), engine=ENGINE_NAME,
            confidence_features={"attachment_status": item["status"], "linked_claim_ids": item["linked_claim_ids"],
                                 "table_ref": item.get("table_ref"), "row": item.get("row"),
                                 "evidence_state": "NOT_PROVIDED" if provided else "REFERENCE_MISSING"},
            tags=["EVIDENCE", "ATTACHMENT", "MISSING_EVIDENCE"],
            evidence=[Evidence.create(description="문서의 첨부·증거 기재", grade=EvidenceGrade.C,
                                      document_id=doc.document_id, page=item.get("page"),
                                      excerpt=(item["mentions"][0].get("stated_status") or item["name"])[:300])],
        ))
    for check in hashes:
        if check["format_status"] == "FORMAT_INVALID":
            out.append(Finding.create(
                type=FindingType.HASH_FORMAT_INVALID, status=VerificationStatus.UNVERIFIED,
                severity=Severity.LOW, evidence_grade=EvidenceGrade.B,
                title=f"해시 형식 이상 / 실제 파일과 대조 불가: {check['claimed_value']}",
                detail=(f"{check['format_note']}. {check['comparison_note']}. 형식 이상은 기재 오류일 수 있으며 "
                        "그것만으로 파일 불일치나 위조를 뜻하지 않는다."),
                document_id=doc.document_id, engine=ENGINE_NAME, confidence_features=dict(check),
                tags=["EVIDENCE", "HASH"],
                evidence=[Evidence.create(description="문서의 해시 기재", grade=EvidenceGrade.B,
                                          document_id=doc.document_id, excerpt=check["excerpt"][:300])],
            ))
        elif check["comparison"] == "MISMATCH":
            out.append(Finding.create(
                type=FindingType.HASH_MISMATCH, status=VerificationStatus.CONTRADICTED,
                severity=Severity.MEDIUM, evidence_grade=EvidenceGrade.A,
                title=f"기재된 해시와 입력 파일의 SHA-256이 다름: {check.get('related_item') or check['claimed_value']}",
                detail=("문서에 적힌 해시값과 함께 입력된 파일 바이트의 SHA-256이 다르다. 다른 파일이거나 "
                        "파일이 바뀌었을 수 있다. 원본성·작성자·수집경위는 별도로 확인해야 한다."),
                document_id=doc.document_id, engine=ENGINE_NAME, confidence_features=dict(check),
                tags=["EVIDENCE", "HASH"],
            ))
    return out
