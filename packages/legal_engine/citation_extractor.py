"""제9.1장 Citation Extraction.

판례·법령·헌재결정·법령해석례·행정심판·학술자료를 Regex/Rule 기반으로 먼저 구조화한다.
주변 문맥의 의미분석만 LLM Structured Output을 사용한다(선택적).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from packages.common.enums import CitationType
from packages.common.schemas import Citation, NormalizedDocument

from .normalize import canonical_case_number, canonical_date, canonical_law_name, split_case_number

COURT_RE = r"(?:대법원|헌법재판소|헌재|[가-힣]{2,10}(?:지방|고등|가정|행정|회생|특허|군사)?법원(?:\s*[가-힣]{2,6}지원)?|서울행정법원|특허법원|군사법원|중앙지역군사법원|고등군사법원)"
DATE_RE = r"(?:19|20)\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?"
CASE_NO_RE = r"(?:19|20)\d{2}\s*[가-힣]{1,3}\s*\d{1,6}"
KIND_RE = r"(?:전원합의체\s*)?(?:판결|결정|명령|선고|자)"

# 대법원 2024. 1. 15. 선고 2023도12345 판결
FULL_CASE_RE = re.compile(
    rf"(?P<court>{COURT_RE})\s*"
    rf"(?P<date>{DATE_RE})\s*"
    rf"(?:선고|자)?\s*"
    rf"(?P<case_no>{CASE_NO_RE})\s*"
    rf"(?P<kind>{KIND_RE})?"
)
# 법원명 없이 "2023도12345 판결"
BARE_CASE_RE = re.compile(rf"(?P<case_no>{CASE_NO_RE})\s*(?P<kind>판결|결정|명령)")
# 헌재 2020. 3. 26. 2018헌바123
CONST_RE = re.compile(
    rf"(?P<court>헌법재판소|헌재)\s*(?P<date>{DATE_RE})?\s*"
    rf"(?P<case_no>(?:19|20)\d{{2}}\s*헌[가-힣]{{1,2}}\s*\d{{1,4}})\s*(?P<kind>결정|전원재판부)?"
)
# 「형법」 제250조 제1항 제2호 / 형법 제250조
LAW_RE = re.compile(
    r"(?P<law>[「『]?[가-힣A-Za-z·\s]{2,40}?(?:법|법률|령|규칙|조례|훈령|예규|규정)[」』]?)\s*"
    r"(?:부칙\s*)?"
    r"제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<article_sub>\d+))?"
    r"(?:\s*제\s*(?P<paragraph>\d+)\s*항)?"
    r"(?:\s*제\s*(?P<item>\d+)\s*호(?:\s*의\s*(?P<item_sub>\d+))?)?"
    r"(?:\s*(?P<subitem>[가-힣])\s*목)?"
)
# 법령해석례 / 행정심판재결례
INTERPRETATION_RE = re.compile(
    r"(?P<authority>법제처|법무부|국방부|행정안전부)?\s*(?:법령해석|유권해석)\s*(?:례)?\s*"
    r"(?P<no>\d{2}\s*-\s*\d{4}(?!\d))?"
)
INTERPRETATION_FULL_RE = re.compile(
    rf"(?P<authority>법제처)\s*(?:(?P<date>{DATE_RE})\s*)?(?:회신\s*)?"
    r"(?P<no>\d{2}\s*-\s*\d{4})(?!\d)\s*(?:해석례|법령해석례)?"
)
ADMIN_APPEAL_RE = re.compile(
    rf"(?P<authority>중앙행정심판위원회|행정심판위원회)\s*"
    rf"(?:(?P<date>{DATE_RE})\s*)?(?:재결\s*)?"
    r"(?P<no>\d{4}\s*-\s*\d{1,8}(?!\d))?\s*(?:재결)?"
)
# 학술: 저자, 「제목」, 학술지 권(호), 연도 / DOI
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
# 학술: 저자, 「논문 제목」 또는 『단행본 제목』, 게재지·출판사, 연도
#
# 국내 표기 관행은 논문에 「」, 단행본에 『』를 쓴다. 『』가 빠져 있어
# 단행본 인용(예: 홍길동, 『현대 계약법과 알고리즘 책임론』, 법문사, 2024, 312면)이
# 전혀 추출되지 않았다. 단행본은 권·호가 없으므로 그 부분도 선택으로 둔다.
ACADEMIC_RE = re.compile(
    r"(?P<authors>[가-힣]{2,4}(?:\s*[·,]\s*[가-힣]{2,4})*)\s*,\s*"
    r"(?:[「『\"“](?P<title>[^」』\"”]{5,120})[」』\"”])\s*,\s*"
    r"(?P<journal>[가-힣A-Za-z\s]{2,40}?)\s*"
    r"(?:제?\s*(?P<volume>\d+)\s*권)?\s*(?:제?\s*(?P<issue>\d+)\s*호)?\s*[,(]?\s*"
    r"(?P<year>(?:19|20)\d{2})"
)

QUOTE_RE = re.compile(r"[“\"]([^”\"]{10,600})[”\"]")


def _quote_near(text: str, index: int, window: int = 400) -> Optional[str]:
    """인용 앞뒤에서 직접 인용문을 찾는다."""
    segment = text[max(0, index - window) : index + window]
    offset = max(0, index - window)
    quotes = list(QUOTE_RE.finditer(segment))
    nearest = min(quotes, key=lambda m: min(abs(offset + m.start() - index), abs(offset + m.end() - index)), default=None)
    return nearest.group(1) if nearest else None


def extract_from_text(
    text: str, *, document_id: Optional[str] = None, block_id: Optional[str] = None, page: Optional[int] = None
) -> List[Citation]:
    citations: List[Citation] = []
    consumed: List[tuple] = []

    def overlaps(start: int, end: int) -> bool:
        return any(s <= start < e or s < end <= e for s, e in consumed)

    for pattern, kind in (
        (INTERPRETATION_FULL_RE, CitationType.INTERPRETATION),
        (INTERPRETATION_RE, CitationType.INTERPRETATION),
        (ADMIN_APPEAL_RE, CitationType.ADMIN_APPEAL),
    ):
        for m in pattern.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            number = re.sub(r"\s+", "", m.group("no")) if m.group("no") else None
            citations.append(Citation.create(
                kind, m.group(0).strip(), document_id=document_id, block_id=block_id,
                page=page, span=(m.start(), m.end()), case_number=number,
                canonical_case_number=number, court=m.group("authority"),
                decision_date=canonical_date(m.groupdict().get("date") or ""),
                quoted_text=_quote_near(text, m.end()),
                context=text[max(0, m.start() - 120):m.end() + 200],
            ))
            consumed.append((m.start(), m.end()))

    # 1) 헌재
    for m in CONST_RE.finditer(text):
        citations.append(
            Citation.create(
                CitationType.CONSTITUTIONAL,
                m.group(0).strip(),
                document_id=document_id,
                block_id=block_id,
                page=page,
                span=(m.start(), m.end()),
                court="헌법재판소",
                decision_date=canonical_date(m.group("date") or ""),
                case_number=re.sub(r"\s+", "", m.group("case_no")),
                canonical_case_number=canonical_case_number(m.group("case_no")),
                case_kind=m.group("kind") or "결정",
                quoted_text=_quote_near(text, m.end()),
                context=text[max(0, m.start() - 120) : m.end() + 120],
            )
        )
        consumed.append((m.start(), m.end()))

    # 2) 완전한 판례 인용
    for m in FULL_CASE_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        case_no = m.group("case_no")
        parts = split_case_number(case_no)
        citations.append(
            Citation.create(
                CitationType.CASE,
                m.group(0).strip(),
                document_id=document_id,
                block_id=block_id,
                page=page,
                span=(m.start(), m.end()),
                court=m.group("court").strip(),
                decision_date=canonical_date(m.group("date")),
                case_number=re.sub(r"\s+", "", case_no),
                canonical_case_number=canonical_case_number(case_no),
                case_kind=(m.group("kind") or "판결").replace("선고", "판결"),
                quoted_text=_quote_near(text, m.end()),
                context=text[max(0, m.start() - 120) : m.end() + 200],
            )
        )
        consumed.append((m.start(), m.end()))

    # 3) 법원명 없는 판례 인용
    for m in BARE_CASE_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        case_no = m.group("case_no")
        citations.append(
            Citation.create(
                CitationType.CASE,
                m.group(0).strip(),
                document_id=document_id,
                block_id=block_id,
                page=page,
                span=(m.start(), m.end()),
                court=None,
                decision_date=None,
                case_number=re.sub(r"\s+", "", case_no),
                canonical_case_number=canonical_case_number(case_no),
                case_kind=m.group("kind"),
                quoted_text=_quote_near(text, m.end()),
                context=text[max(0, m.start() - 120) : m.end() + 200],
            )
        )
        consumed.append((m.start(), m.end()))

    # 4) 법령
    for m in LAW_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        law_name = canonical_law_name(m.group("law"))
        if len(law_name) < 2:
            continue
        article = m.group("article")
        if m.group("article_sub"):
            article = f"{article}의{m.group('article_sub')}"
        citations.append(
            Citation.create(
                CitationType.STATUTE,
                m.group(0).strip(),
                document_id=document_id,
                block_id=block_id,
                page=page,
                span=(m.start(), m.end()),
                law_name=law_name,
                article=article,
                paragraph=m.group("paragraph"),
                item=(f"{m.group('item')}의{m.group('item_sub')}" if m.group("item_sub") else m.group("item")),
                quoted_text=_quote_near(text, m.end()),
                context=text[max(0, m.start() - 100) : m.end() + 150],
            )
        )
        consumed.append((m.start(), m.end()))

    # 5) 학술자료
    for m in ACADEMIC_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        authors = [a.strip() for a in re.split(r"·", m.group("authors")) if a.strip()]
        citations.append(
            Citation.create(
                CitationType.ACADEMIC,
                m.group(0).strip(),
                document_id=document_id,
                block_id=block_id,
                page=page,
                span=(m.start(), m.end()),
                title=m.group("title").strip(),
                authors=authors,
                journal=m.group("journal").strip(),
                year=int(m.group("year")),
                context=text[max(0, m.start() - 80) : m.end() + 120],
            )
        )
        consumed.append((m.start(), m.end()))

    for m in DOI_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        citations.append(
            Citation.create(
                CitationType.ACADEMIC,
                m.group(0),
                document_id=document_id,
                block_id=block_id,
                page=page,
                span=(m.start(), m.end()),
                doi=m.group(0),
                context=text[max(0, m.start() - 120) : m.end() + 120],
            )
        )
        consumed.append((m.start(), m.end()))

    return citations


def _identity(citation: Citation) -> Tuple[Any, ...]:
    """같은 인용인지 판정할 키. 블록 경계가 달라도 중복으로 세지 않기 위해 쓴다."""
    return (
        str(citation.type),
        citation.canonical_case_number,
        citation.law_name,
        citation.article,
        citation.paragraph,
        citation.item,
        citation.doi,
        (citation.title or "").strip(),
    )


def _joined_pages(doc: NormalizedDocument) -> List[Tuple[str, List[Tuple[int, Any]]]]:
    """페이지별로 줄 블록을 이어 붙인 텍스트와, 각 블록의 시작 위치를 만든다."""
    pages: Dict[Any, List[Any]] = {}
    for block in doc.body_blocks():
        pages.setdefault(block.page, []).append(block)

    out: List[Tuple[str, List[Tuple[int, Any]]]] = []
    for blocks in pages.values():
        parts: List[str] = []
        offsets: List[Tuple[int, Any]] = []
        cursor = 0
        for block in blocks:
            text = block.text.strip()
            if not text:
                continue
            offsets.append((cursor, block))
            parts.append(text)
            cursor += len(text) + 1  # 이어 붙일 때 넣는 공백 한 칸
        if parts:
            out.append((" ".join(parts), offsets))
    return out


def _owner_block(offsets: List[Tuple[int, Any]], index: int) -> Any:
    """이어 붙인 텍스트의 위치가 어느 블록에서 시작하는지 찾는다."""
    owner = offsets[0][1] if offsets else None
    for start, block in offsets:
        if start > index:
            break
        owner = block
    return owner


def extract_citations(doc: NormalizedDocument) -> List[Citation]:
    """본문(표시 텍스트·스캔본 OCR)에서 인용을 추출한다. 숨은 레이어는 적대적 콘텐츠로 별도 처리한다."""
    out: List[Citation] = []
    seen: set = set()
    for block in doc.body_blocks():
        for citation in extract_from_text(
            block.text, document_id=doc.document_id, block_id=block.block_id, page=block.page
        ):
            key = (_identity(citation), block.block_id, citation.span)
            if key in seen:
                continue
            seen.add(key)
            out.append(citation)

    # 줄바꿈으로 잘린 인용을 위해 페이지 단위로 이어 붙여 한 번 더 훑는다.
    # PDF의 블록은 시각적 '줄'이므로 "홍길동, 『현대 계약법과 알고리즘 / 책임론』, 법문사, 2024"처럼
    # 인용이 두 줄에 걸치면 블록 단위 검사로는 영원히 잡히지 않는다.
    for joined, offsets in _joined_pages(doc):
        for citation in extract_from_text(joined, document_id=doc.document_id, block_id=None, page=None):
            owner = _owner_block(offsets, citation.span[0] if citation.span else 0)
            if owner is not None:
                start = next(start for start, block in offsets if block.block_id == owner.block_id)
                citation.block_id = owner.block_id
                citation.page = owner.page
                if citation.span:
                    citation.span = (citation.span[0] - start, citation.span[1] - start)
            key = (_identity(citation), citation.block_id, citation.span)
            if key in seen:
                continue
            seen.add(key)
            out.append(citation)
    return out
