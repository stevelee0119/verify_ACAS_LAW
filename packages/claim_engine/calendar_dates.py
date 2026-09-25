"""본문의 달력에 없는 날짜(v5 3-8).

인용(선고일)과 증거표(작성일)만 보던 날짜 형식 검사를 본문 전체로 넓힌다('지급기일 2026. 4. 31.', '합의일 2025. 2. 29.').

OCR 글자층(스캔본)은 숫자를 비슷한 글자로 잘못 읽는다(O↔0, l·I·|↔1, S↔5, B↔8). 날짜 모양의 토큰 안에서만 이 글자를
숫자로 바꾼 뒤 검사하고, 보정했으면 판정 근거에 적는다. 판정 등급은 OCR 신뢰도를 반영한다.
- 텍스트 글자층: A
- OCR 신뢰도 0.85 이상이고 보정 없음: A / 0.6 이상 또는 보정함: B / 그 밖: C(사람 확인)
인용·증거표에서 같은 날짜 표기를 이미 판정했으면 다시 내지 않는다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable, List, Optional, Tuple

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text

ENGINE_NAME = "claim_engine.calendar_dates"
DATE_RE = re.compile(r"(?<![\d])(?P<y>(?:19|20)\d{2})\s*[.년]\s*(?P<m>\d{1,2})\s*[.월]\s*(?P<d>\d{1,2})\s*[.일]")
# OCR에서 숫자로 잘못 읽는 글자. 날짜 모양 토큰('2O26. 4. 3l.') 안에서만 바꾼다.
OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1", "|": "1", "i": "1",
                           "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})
OCR_DATE_RE = re.compile(r"(?<![\w])(?P<y>[12][0-9OoQDlI|iSsBZz]{3})\s*[.,]\s*(?P<m>[0-9OoQDlI|iSsBZz]{1,2})\s*[.,]\s*"
                         r"(?P<d>[0-9OoQDlI|iSsBZz]{1,2})\s*[.,]")
OCR_HIGH, OCR_MID = 0.85, 0.6


def normalize_ocr_dates(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """OCR 글의 날짜 모양 토큰에서 숫자 오인식을 바로잡는다. (보정한 글, [(원래, 보정)])."""
    changes: List[Tuple[str, str]] = []

    def fix(m: "re.Match[str]") -> str:
        raw = m.group(0)
        digits = sum(ch.isdigit() for ch in m.group("y") + m.group("m") + m.group("d"))
        if digits < 4:  # 숫자가 대부분인 토큰만(글자 낱말을 날짜로 만들지 않는다)
            return raw
        fixed = raw.translate(OCR_DIGIT).replace(",", ".")
        if fixed != raw:
            changes.append((raw.strip(), fixed.strip()))
        return fixed

    return OCR_DATE_RE.sub(fix, text), changes


def _impossible(m: "re.Match[str]") -> Optional[str]:
    y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
    if not (1 <= mo <= 12) or d < 1:
        return None  # 월이 13 이상이면 날짜가 아닌 번호일 수 있다(판단하지 않음)
    try:
        date(y, mo, d)
        return None
    except ValueError:
        return f"{y}. {mo}. {d}."


def calendar_date_findings(doc: NormalizedDocument, existing: Iterable[Finding] = ()) -> List[Finding]:
    judged = " ".join(f"{f.title} {f.detail}" for f in existing)
    out: List[Finding] = []
    seen: set = set()
    for block_text, blocks in _units(doc):
        ocr = [b for b in blocks if b.source_layer == "ocr_layer"]
        text, changes = normalize_ocr_dates(block_text) if ocr else (block_text, [])
        for m in DATE_RE.finditer(text):
            written = _impossible(m)
            if not written or written in seen or written in judged:
                continue
            seen.add(written)
            confidence = min((float(b.attributes.get("ocr_confidence") or 0) for b in ocr), default=None)
            corrected = [c for c in changes if c[1] in m.group(0) or m.group(0).strip() in c[1]]
            grade = _grade(confidence, bool(corrected))
            context = " ".join(text[max(0, m.start() - 30):m.end() + 20].split())
            features = {"deterministic_rule": True, "rule_id": "DATE.NOT_ON_CALENDAR", "defect_code": "DATE_NOT_ON_CALENDAR",
                        "written_date": written, "ocr": bool(ocr), "ocr_confidence": confidence,
                        "ocr_corrections": corrected, "human_review": grade == EvidenceGrade.C}
            note = ""
            if ocr:
                note = f" OCR로 읽은 글자다(신뢰도 {confidence:.2f})." if confidence is not None else " OCR로 읽은 글자다."
                if corrected:
                    note += f" 숫자 오인식을 보정했다: {', '.join(f'{a} → {b}' for a, b in corrected)}."
                note += " 원본 이미지로 확인해야 한다."
            out.append(Finding.create(
                type=FindingType.TIMELINE_CONTRADICTION,
                status=VerificationStatus.CONTRADICTED if grade != EvidenceGrade.C else VerificationStatus.SUSPICIOUS,
                severity=Severity.HIGH if grade == EvidenceGrade.A else Severity.MEDIUM, evidence_grade=grade,
                title=f"달력에 없는 날짜(DATE_NOT_ON_CALENDAR): {written}",
                detail=f"문서가 적은 '{written}'은 달력에 없는 날짜다. 오기인지 원본을 확인해야 한다." + note,
                confidence={EvidenceGrade.A: 0.95, EvidenceGrade.B: 0.75}.get(grade, 0.5), confidence_features=features,
                document_id=doc.document_id, page=blocks[0].page if blocks else None,
                block_id=blocks[0].block_id if blocks else None, engine=ENGINE_NAME, tags=["DATE", "CALENDAR"],
                evidence=[Evidence.create(description="날짜 기재", grade=grade, document_id=doc.document_id,
                                          page=blocks[0].page if blocks else None, excerpt=context[:200])]))
    return out


def _units(doc: NormalizedDocument) -> List[Tuple[str, list]]:
    """검사 단위: 텍스트 본문은 읽기 본문 전체(줄바꿈으로 나뉜 날짜 포함), OCR 글자층은 블록마다(신뢰도를 블록별로)."""
    text_blocks = [b for b in doc.body_blocks() if b.block_type not in ("table", "table_line", "running_head")
                   and b.source_layer != "ocr_layer"]
    reading = build_reading_text(doc, text_blocks)
    units = [(reading.text, [s.block for s in reading.segments])]
    for block in doc.body_blocks():
        if block.source_layer == "ocr_layer" and block.text:
            units.append((block.text, [block]))
    return units


def _grade(confidence: Optional[float], corrected: bool) -> EvidenceGrade:
    if confidence is None:
        return EvidenceGrade.A
    if confidence >= OCR_HIGH and not corrected:
        return EvidenceGrade.A
    if confidence >= OCR_MID:
        return EvidenceGrade.B
    return EvidenceGrade.C
