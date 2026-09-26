"""제9.1장 Citation Extraction.

판례·법령·헌재결정·법령해석례·행정심판·학술자료를 Regex/Rule 기반으로 먼저 구조화한다.
주변 문맥의 의미분석만 LLM Structured Output을 사용한다(선택적).
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from packages.common.enums import CitationType
from packages.common.schemas import Citation, NormalizedDocument

from packages.document_engine.reading_text import (QUOTE_SPAN_RE, build_reading_text, ensure_running_heads,
                                                    join_separator, sentence_bounds)

from .normalize import (canonical_case_number, canonical_date, canonical_law_name, law_name_suffix)

# 스캔 OCR은 '헌법 재판소'처럼 법원명을 띄어 읽기도 한다(추가지시 G2). 법원명 안의 공백은 표준화 때 없앤다.
COURT_RE = r"(?:대법원|헌법\s?재판소|헌재|[가-힣]{2,10}(?:지방|고등|가정|행정|회생|특허|군사)?법원(?:\s*[가-힣]{2,6}지원)?|서울행정법원|특허법원|군사법원|중앙지역군사법원|고등군사법원)"
COURT_ALIASES = {"헌재": "헌법재판소"}  # 약칭은 조회·호환성 검사에 쓰는 공식 명칭으로 바꾼다


def _court_name(raw: str) -> str:
    name = raw.strip()
    if re.fullmatch(r"헌법\s+재판소", name):
        name = "헌법재판소"
    return COURT_ALIASES.get(name, name)
DATE_RE = r"(?:19|20)\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?"
# 1999년까지의 사건번호는 연도를 두 자리로 적는다(예: 94누4615).
CASE_NO_RE = r"(?<!\d)(?:(?:19|20)\d{2}|\d{2})\s*[가-힣]{1,3}\s*\d{1,6}"
KIND_RE = r"(?:전원합의체\s*)?(?:판결|결정|명령|선고|자)"

# 대법원 2024. 1. 15. 선고 2023도12345 판결
FULL_CASE_RE = re.compile(
    rf"(?P<court>{COURT_RE})(?:\s*(?P<particle>은|는|도|이|가|의))?\s*"
    rf"(?P<date>{DATE_RE})\s*"
    rf"(?:선고|자)?\s*"
    rf"(?P<case_no>{CASE_NO_RE})"
    # 사건번호와 판결 사이의 사건명("2006두20631 징계처분취소 판결"). 판결·결정이 바로 뒤따를 때만 잡는다.
    rf"(?:\s*(?!전원합의체)(?P<case_name>[가-힣·()]{{2,24}}?)(?=\s*(?:전원합의체\s*)?(?:판결|결정)))?\s*"
    rf"(?P<kind>{KIND_RE})?"
)
# 법원명 없이 "2023도12345 판결"
BARE_CASE_RE = re.compile(rf"(?P<case_no>{CASE_NO_RE})\s*(?P<kind>판결|결정|명령)")
# 헌재 2020. 3. 26. 2018헌바123
CONST_RE = re.compile(
    rf"(?P<court>헌법\s?재판소|헌재)\s*(?P<date>{DATE_RE})?\s*"
    # 일련번호 자릿수를 제한하면 뒷자리가 잘린 다른 사건번호가 된다(2018헌바 90044 → 2018헌바9004). 숫자 경계까지 읽는다.
    rf"(?P<case_no>(?:19|20)\d{{2}}\s*헌\s*[가-힣]{{1,2}}\s*\d{{1,6}}(?!\d))"
    # 병합 표기: 2004헌마554·566(병합), 2011헌바379 등(병합), 2004헌마554, 2004헌마566(병합)
    rf"(?P<merged>(?:\s*[·ㆍ,]\s*(?:(?:19|20)\d{{2}}\s*헌\s*[가-힣]{{1,2}}\s*)?\d{{1,6}}(?!\d))*\s*(?:등\s*)?\(\s*병합\s*\))?"
    rf"\s*(?P<kind>결정|전원재판부)?"
)


def _merged_attributes(main: str, merged: str) -> dict:
    """병합 표기의 다른 사건번호. 조회·판정은 대표 사건번호로 하고, 병합 사건은 기록으로 남긴다."""
    if not merged or "병합" not in merged:
        return {}
    head = re.match(r"((?:19|20)\d{2})\s*(헌\s*[가-힣]{1,2})", main)
    numbers = []
    for part in re.findall(r"(?:(?:19|20)\d{2}\s*헌\s*[가-힣]{1,2}\s*)?\d{1,6}", merged):
        part = re.sub(r"\s+", "", part)
        numbers.append(part if not part.isdigit() or not head else f"{head.group(1)}{re.sub(chr(32), '', head.group(2))}{part}")
    return {"merged_case_numbers": numbers, "merged_notation": True}


# 「형법」 제250조 제1항 제2호 / 형법 제250조
LAW_RE = re.compile(
    r"(?P<law>[「『]?[가-힣A-Za-z· ]{1,40}?(?:법|법률|령|규칙|조례|훈령|예규|규정|고시|지침)[」』]?)\s*"
    r"(?:부칙\s*)?"
    r"제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<article_sub>\d+))?"
    r"(?:\s*제\s*(?P<paragraph>\d+)\s*항)?"
    r"(?:\s*제\s*(?P<item>\d+)\s*호(?:\s*의\s*(?P<item_sub>\d+))?)?"
    r"(?:\s*(?P<subitem>[가-힣])\s*목)?"
)
# 앞 조문 인용에 이어지는 조문: "및 제751조", ", 제4조 제2항", "와 제9조의2"
CONTINUED_ARTICLE_RE = re.compile(
    r"\s*(?:,|및|또는|와|과|·|ㆍ)\s*(?P<ref>제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<article_sub>\d+))?"
    r"(?:\s*제\s*(?P<paragraph>\d+)\s*항)?(?:\s*제\s*(?P<item>\d+)\s*호)?)")
# "같은 법", "동법", "같은 법률": 앞서 인용한 법령을 가리킨다.
SAME_LAW_RE = re.compile(r"(?:^|\s)(?:같은|동|위)\s*법(?:률)?$")
# 앞 인용의 조를 가리키는 표현(추가지시 G3): "같은 조 제2항", "동조 제2항", "위 조항", 그리고 조 없이 쓴 "제2항".
SAME_ARTICLE_REF_RE = re.compile(
    # '같은 조건'·'위조한'·'동조하였다'는 조 인용이 아니다. 조(항) 뒤가 공백·문장부호·조사일 때만 잡는다.
    r"(?P<ref>(?:같은|동|위)\s*조(?:항)?|동조(?:항)?)(?=\s|[,.)」』]|은|는|이|가|의|에|을|를|도|$)"
    r"(?:\s*제\s*(?P<paragraph>\d+)\s*항)?(?:\s*제\s*(?P<item>\d+)\s*호)?")
BARE_PARAGRAPH_REF_RE = re.compile(r"(?<![\d조])(?<!조\s)제\s*(?P<paragraph>\d+)\s*항(?:\s*제\s*(?P<item>\d+)\s*호)?")
REFERENCE_WINDOW = 300  # 앞 인용과 이 거리 안에 있을 때만 결합한다(문단을 건너 결합하지 않는다)
# 행정규칙(훈령·예규·고시·지침). 법령 검증과 다른 경로로 검증한다.
ADMIN_RULE_KINDS = ("훈령", "예규", "고시", "지침")
_KIND = "|".join(ADMIN_RULE_KINDS)
AGENCY_RE = r"[가-힣]{1,20}?(?:부|처|청|원|위원회|본부|사령부|총장|실)"
# "국방부훈령 제2345호", "행정안전부 예규 제12호", "국방부 훈령 제2024-3호"
ADMIN_RULE_REF_RE = re.compile(
    rf"(?P<agency>{AGENCY_RE})\s*(?P<kind>{_KIND})\s*제\s*(?P<number>\d+(?:\s*-\s*\d+)?)\s*호"
)
BRACKET_NAME_RE = re.compile(r"[「『](?P<name>[^」』]{2,60})[」』]")
EFFECTIVE_RE = re.compile(rf"(?P<date>{DATE_RE})\s*(?:부터\s*)?시행")
ARTICLE_RE = re.compile(r"제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?(?:\s*제\s*(?P<paragraph>\d+)\s*항)?")
# 문서가 위임 근거로 드는 법령 조문. "「병역법」 제5조의 위임에 따라", "…제5조에 근거하여"
DELEGATION_RE = re.compile(
    r"(?P<basis>[「『]?[가-힣A-Za-z·\s]{2,40}?(?:법|법률|령|규칙)[」』]?\s*제\s*\d+\s*조(?:\s*의\s*\d+)?"
    r"(?:\s*제\s*\d+\s*항)?)\s*(?:의\s*위임|에서\s*위임|에\s*따라|에\s*근거|에\s*의하여|의\s*규정에\s*따라)"
)
# 문서가 행정규칙의 효력을 어떻게 주장하는지. 확인이 아니라 사람 검토 대상으로만 남긴다.
CLAIMED_EFFECT_RE = re.compile(
    r"(법률과\s*(?:같은|동일한|동등한)\s*효력|법규명령(?:의|으로서의)?\s*효력|대외적\s*(?:구속력|효력)|"
    r"국민(?:을|에\s*대하여)\s*구속|구속력(?:이|을)\s*(?:있|가지|갖))"
)


SENTENCE_END_RE = re.compile(r"(?:다|음|함)\s*\.|[\n。!?]")


def _admin_rule_citation(text: str, anchor_start: int, anchor_end: int, *, agency=None, kind=None,
                         number=None, name=None, article=None, sub=None, paragraph=None,
                         document_id=None, block_id=None, page=None) -> Citation:
    """행정규칙 인용 하나를 구조화한다. 주변 문맥에서 이름·시행일·조항·위임 근거를 찾는다."""
    window_start, window_end = max(0, anchor_start - 80), min(len(text), anchor_end + 120)
    window = text[window_start:window_end]
    if name is None:
        names = list(BRACKET_NAME_RE.finditer(window))
        if names:
            anchor = anchor_start - window_start
            name = min(names, key=lambda m: min(abs(m.start() - anchor), abs(m.end() - anchor))).group("name")
    effective = EFFECTIVE_RE.search(window)
    if article is None:
        found = ARTICLE_RE.search(text[anchor_end:anchor_end + 40])
        if found:
            article, sub, paragraph = found.group("article"), found.group("sub"), found.group("paragraph")
    # 문장 경계는 "다."·줄바꿈으로 잡는다. "2025. 3. 1." 같은 날짜의 마침표에서 끊지 않는다.
    before = [m.end() for m in SENTENCE_END_RE.finditer(text, 0, anchor_start)]
    after = SENTENCE_END_RE.search(text, anchor_end)
    sentence = text[before[-1] if before else 0:after.end() if after else len(text)]
    delegation = DELEGATION_RE.search(sentence)
    effect = CLAIMED_EFFECT_RE.search(sentence)
    article_text = f"{article}의{sub}" if article and sub else article
    return Citation.create(
        CitationType.ADMIN_RULE, text[anchor_start:anchor_end].strip(),
        document_id=document_id, block_id=block_id, page=page, span=(anchor_start, anchor_end),
        law_name=canonical_law_name(name) if name else None,
        article=article_text, paragraph=paragraph,
        quoted_text=_quote_near(text, anchor_end),
        context=text[max(0, anchor_start - 120):anchor_end + 200],
        attributes={
            "rule_name": canonical_law_name(name) if name else None,
            "issuing_agency": agency, "rule_kind": kind,
            "rule_number": re.sub(r"\s+", "", number) if number else None,
            "effective_date": canonical_date(effective.group("date")) if effective else None,
            "delegation_basis": " ".join(delegation.group("basis").split()) if delegation else None,
            "claimed_effect": effect.group(0) if effect else None,
        },
    )


# 법령해석례 / 행정심판재결례
INTERPRETATION_RE = re.compile(
    r"(?P<authority>법제처|법무부|국방부|행정안전부)?\s*(?:법령해석|유권해석)\s*(?:례)?\s*"
    r"(?P<no>\d{2}\s*-\s*\d{4}(?!\d))?"
)
# "국방부 법무관리관실 2025. 4. 31.자 유권해석", "○○부 2024. 3. 2. 질의회신"
DATED_INTERPRETATION_RE = re.compile(
    rf"(?P<authority>[가-힣]{{2,12}}(?:\s*[가-힣]{{2,12}})?(?:부|처|청|원|실|관|국|과|위원회))"
    r"(?:도|은|는|이|가|의|에서)?\s*"  # 기관명 뒤 조사("법무관리관실도 2025. 4. 30.자")
    rf"(?P<date>{DATE_RE})\s*자?\s*(?:유권해석|법령해석|질의\s*회신|회신|해석)(?P<no>)"
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
    r"(?P<authors>[가-힣][가-힣○△□*]{1,3}(?:\s*[·,]\s*[가-힣][가-힣○△□*]{1,3})*)\s*,\s*"
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
        (DATED_INTERPRETATION_RE, CitationType.INTERPRETATION),
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
                attributes=_merged_attributes(m.group("case_no"), m.group("merged")),
            )
        )
        consumed.append((m.start(), m.end()))

    # 2) 완전한 판례 인용
    for m in FULL_CASE_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        case_no = m.group("case_no")
        citations.append(
            Citation.create(
                CitationType.CASE,
                # 법원명 뒤 조사("헌법재판소는")는 인용 표기가 아니다
                (f"{m.group('court').strip()} {text[m.start('date'):m.end()].strip()}" if m.group("particle")
                 else m.group(0).strip()),
                document_id=document_id,
                block_id=block_id,
                page=page,
                span=(m.start(), m.end()),
                court=_court_name(m.group("court")),
                decision_date=canonical_date(m.group("date")),
                case_number=re.sub(r"\s+", "", case_no),
                canonical_case_number=canonical_case_number(case_no),
                case_kind=(m.group("kind") or "판결").replace("선고", "판결"),
                quoted_text=_quote_near(text, m.end()),
                context=text[max(0, m.start() - 120) : m.end() + 200],
            )
        )
        if m.group("case_name"):
            citations[-1].attributes["case_name"] = m.group("case_name")
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

    # 4-1) 행정규칙: "OO부훈령 제N호"처럼 발령기관·종류·번호가 있는 인용
    for m in ADMIN_RULE_REF_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        start, end = m.start(), m.end()
        # 규칙 이름은 번호 바로 앞("「…」(OO부훈령 제N호")이나 바로 뒤("OO부훈령 제N호 「…」")에만
        # 붙인다. 같은 문장의 다른 괄호(위임 근거 법령명 등)를 끌어오지 않는다.
        name = None
        before = list(BRACKET_NAME_RE.finditer(text, max(0, start - 70), start))
        if before and re.fullmatch(r"[\s(（]*", text[before[-1].end():start]):
            name, start = before[-1].group("name"), before[-1].start()
        after = BRACKET_NAME_RE.match(text, end + len(re.match(r"[\s,]*", text[end:]).group(0)))
        if name is None and after:
            name, end = after.group("name"), after.end()
        # 번호 뒤 "(…, 2025. 3. 1. 시행) 제12조 제2항"처럼 괄호·시행일을 건너 조항이 오면 범위에 넣는다.
        trailing = re.match(rf"[\s,)]*(?:{DATE_RE}\s*(?:부터\s*)?시행\s*[,)]?\s*)?[\s)]*", text[end:end + 60])
        article = ARTICLE_RE.match(text, end + (trailing.end() if trailing else 0))
        located = {}
        if article:
            end = article.end()
            located = {"article": article.group("article"), "sub": article.group("sub"),
                       "paragraph": article.group("paragraph")}
        citations.append(_admin_rule_citation(
            text, start, end, agency=m.group("agency").strip(), kind=m.group("kind"),
            number=m.group("number"), name=name, document_id=document_id, block_id=block_id, page=page,
            **located))
        consumed.append((start, end))

    # 4) 법령
    previous_law: Optional[str] = None
    for m in LAW_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        raw_law = m.group("law")
        same_law = SAME_LAW_RE.search(raw_law)
        if same_law:
            # "같은 법 제60조"는 앞서 인용한 법령을 가리킨다. 앞 법령이 없으면 식별할 수 없으므로 뺀다.
            if previous_law is None:
                continue
            law_name, start = previous_law, m.start("law") + same_law.start()
        else:
            law_name = canonical_law_name(raw_law)
            start = _law_name_start(m)
        if len(law_name) < 2:
            continue
        previous_law = law_name
        if law_name.endswith(ADMIN_RULE_KINDS):
            # 이름이 훈령·예규·고시·지침으로 끝나면 법령이 아니라 행정규칙이다.
            kind = next(k for k in ADMIN_RULE_KINDS if law_name.endswith(k))
            citations.append(_admin_rule_citation(
                text, m.start(), m.end(), kind=kind, name=law_name,
                article=m.group("article"), sub=m.group("article_sub"), paragraph=m.group("paragraph"),
                document_id=document_id, block_id=block_id, page=page))
            consumed.append((m.start(), m.end()))
            continue
        article = m.group("article")
        if m.group("article_sub"):
            article = f"{article}의{m.group('article_sub')}"
        citations.append(
            Citation.create(
                CitationType.STATUTE,
                text[start:m.end()].strip(),
                document_id=document_id,
                block_id=block_id,
                page=page,
                span=(start, m.end()),
                law_name=law_name,
                article=article,
                paragraph=m.group("paragraph"),
                item=(f"{m.group('item')}의{m.group('item_sub')}" if m.group("item_sub") else m.group("item")),
                quoted_text=_quote_near(text, m.end()),
                context=text[max(0, start - 100) : m.end() + 150],
            )
        )
        consumed.append((m.start(), m.end()))
        # "제750조 및 제751조", "제3조, 제4조": 법령명 없이 이어진 조문도 같은 법령의 인용이다.
        head_id, position = citations[-1].citation_id, m.end()
        while (more := CONTINUED_ARTICLE_RE.match(text, position)):
            number = more.group("article") + (f"의{more.group('article_sub')}" if more.group("article_sub") else "")
            span_start = more.start("ref")
            citations.append(Citation.create(
                CitationType.STATUTE, f"{law_name} {text[span_start:more.end()].strip()}",
                document_id=document_id, block_id=block_id, page=page, span=(span_start, more.end()),
                law_name=law_name, article=number, paragraph=more.group("paragraph"), item=more.group("item"),
                quoted_text=_quote_near(text, more.end()),
                context=text[max(0, start - 100): more.end() + 150],
                attributes={"continued_from": head_id}))
            consumed.append((span_start, more.end()))
            position = more.end()

    # 4-2) 앞 인용의 조를 가리키는 표현을 그 조의 인용으로 푼다(추가지시 G3). 뒤따르는 수치가 가장 가까운
    #      항·호 인용에 결합되도록, 가리킨 항을 별도 인용으로 둔다.
    _resolve_article_references(text, citations, consumed, overlaps, document_id=document_id,
                                block_id=block_id, page=page)

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

    bind_quotes(text, citations)
    attach_claim_text(text, citations)
    return citations


_STATUTE_TYPES = (CitationType.STATUTE,)


def _resolve_article_references(text, citations, consumed, overlaps, *, document_id, block_id, page) -> None:
    references = []
    for pattern in (SAME_ARTICLE_REF_RE, BARE_PARAGRAPH_REF_RE):
        references += [m for m in pattern.finditer(text) if not overlaps(m.start(), m.end())]
    for m in sorted(references, key=lambda r: r.start()):
        if overlaps(m.start(), m.end()):
            continue
        statutes = [c for c in citations if c.type in _STATUTE_TYPES and c.span and c.span[1] <= m.start()
                    and m.start() - c.span[1] <= REFERENCE_WINDOW]
        if not statutes:
            continue
        base = max(statutes, key=lambda c: c.span[1])
        bare = m.re is BARE_PARAGRAPH_REF_RE
        paragraph = m.group("paragraph") or (None if bare else base.paragraph)
        if bare and not paragraph:
            continue
        item = m.group("item") or (None if (bare or m.group("paragraph")) else base.item)
        label = f"{base.law_name} 제{base.article}조" + (f" 제{paragraph}항" if paragraph else "") + (f" 제{item}호" if item else "")
        citation = Citation.create(
            CitationType.STATUTE, m.group(0).strip(), document_id=document_id, block_id=block_id, page=page,
            span=(m.start(), m.end()), law_name=base.law_name, article=base.article, paragraph=paragraph, item=item,
            quoted_text=_quote_near(text, m.end()), context=text[max(0, m.start() - 100):m.end() + 150])
        citation.attributes.update({"resolved_label": label, "reference_to": base.raw_text,
                                    "reference_kind": "BARE_PARAGRAPH" if bare else "SAME_ARTICLE"})
        citations.append(citation)
        consumed.append((m.start(), m.end()))


def attach_claim_text(text: str, citations: List[Citation]) -> None:
    """법령 인용마다 문서가 그 조문에 대해 주장한 부분(같은 문장)을 attributes["claim_text"]에 남긴다.

    - 괄호 안의 근거 표시("…정직 2개월(군인사법 제57조 제1항 참조)")는 괄호 앞 절이 주장이다.
    - 그 밖에는 인용 뒤부터 같은 문장의 다음 인용 또는 문장 끝까지가 주장이다.
    본문 대조(provision_content)가 이 부분만 조문 본문과 비교한다.
    """
    located = sorted((c for c in citations if c.span), key=lambda c: c.span[0])
    if not located:
        return
    for s_start, s_end in _sentences(text):
        inside = [c for c in located if s_start <= c.span[0] < s_end]
        for position, citation in enumerate(inside):
            if citation.type in (CitationType.CASE, CitationType.CONSTITUTIONAL):
                # 판례를 근거로 서면이 말하는 내용: 같은 문장에서 인용 표시를 뺀 부분(의견 귀속·결론 방향 검사용)
                sentence = text[s_start:s_end]
                claim = sentence[:citation.span[0] - s_start] + " " + sentence[citation.span[1] - s_start:]
                claim = re.sub(r"\(\s*\)|\[\s*\]", " ", claim)
                citation.attributes["case_claim"] = " ".join(claim.split())[:400]
                continue
            if citation.type not in _STATUTE_TYPES:
                continue
            start, end = citation.span
            before = text[s_start:start]
            opened = before.rfind("(")
            if opened > before.rfind(")"):
                clause_start = max(before.rfind(",", 0, opened), before.rfind("，", 0, opened)) + 1
                claim = before[clause_start:opened]
                citation.attributes["claim_mode"] = "PARENTHETICAL_BASIS"
            else:
                stop = inside[position + 1].span[0] if position + 1 < len(inside) else s_end
                claim = text[end:stop]
                # 문장 첫머리의 주어("정직은 …법 제57조에 따른 …")는 조문 안에서 비교할 구절을 고르는 데 쓴다.
                lead = re.sub(r"^[\s\d가-하.)(]*[.)]\s*", "", text[s_start:start]).split()
                if lead:
                    subject = re.sub(r"(은|는|이|가|의|도)$", "", lead[0])
                    if 2 <= len(subject) <= 10 and re.fullmatch(r"[가-힣]+", subject):
                        citation.attributes["claim_subject"] = subject
            citation.attributes["claim_text"] = " ".join(claim.split())[:400]


def _law_name_start(m: "re.Match") -> int:
    """법령명 앞에 붙어 잡힌 문장 조각을 뺀 법령명의 시작 위치."""
    raw = m.group("law")
    kept = law_name_suffix(raw).split()
    tokens = list(re.finditer(r"[^\s「」『』]+", raw))
    if not kept or len(kept) > len(tokens):
        return m.start("law")
    start = tokens[-len(kept)].start()
    if start > 0 and raw[start - 1] in "「『":
        start -= 1
    return m.start("law") + start


# --- 직접 인용문 결합 --------------------------------------------------------------
_sentences = sentence_bounds
_CASE_TYPES = (CitationType.CASE, CitationType.CONSTITUTIONAL, CitationType.INTERPRETATION,
               CitationType.ADMIN_APPEAL)


def bind_quotes(text: str, citations: List[Citation]) -> None:
    """직접 인용문을 그 출처 인용 하나에만 결합한다.

    1) 같은 문장 안에서 인용문 바로 뒤의 괄호 출처 → 판례·결정을 법령보다 우선
    2) 괄호 출처가 없으면 인용문 뒤 같은 문장의 첫 판례·결정
    3) 그래도 없으면 인용문 앞 같은 문장의 가장 가까운 인용("…제27조는 "…"라고 규정")
    같은 문장에 결합할 출처가 없으면 결합하지 않는다. 거리만 보고 가까운 인용에 붙이지 않는다.
    """
    for citation in citations:
        citation.quoted_text = None
    located = [c for c in citations if c.span]
    if not located:
        return
    for s_start, s_end in _sentences(text):
        for quote in QUOTE_SPAN_RE.finditer(text, s_start, s_end):
            inside = [c for c in located if s_start <= c.span[0] < s_end]
            after = sorted((c for c in inside if c.span[0] >= quote.end()), key=lambda c: c.span[0])
            before = sorted((c for c in inside if c.span[1] <= quote.start()), key=lambda c: -c.span[1])
            target = None
            paren = re.match(r"[^(（]{0,40}?[(（]", text[quote.end():s_end])
            if paren:
                open_at = quote.end() + paren.end()
                close = text.find(")", open_at, s_end)
                close = close if close != -1 else s_end
                in_paren = [c for c in after if open_at <= c.span[0] < close]
                target = next((c for c in in_paren if c.type in _CASE_TYPES), in_paren[0] if in_paren else None)
            if target is None:
                target = next((c for c in after if c.type in _CASE_TYPES), None)
            if target is None and before:
                target = before[0]
            if target is None:
                continue
            if target.quoted_text is None:
                target.quoted_text = quote.group(1)
            else:
                target.attributes.setdefault("additional_quotes", []).append(quote.group(1))


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
        (citation.attributes or {}).get("rule_number"),
    )


def _cell_text(cell: str) -> str:
    """표 칸 안 줄바꿈을 한국어 줄바꿈 규칙으로 잇는다("선\n고 2018두47215" → "선고 2018두47215")."""
    lines = [line.strip() for line in str(cell or "").splitlines() if line.strip()]
    text = ""
    for line in lines:
        text = (text + join_separator(text, line) + line) if text else line
    return text.replace("\n", " ")


def extract_citations(doc: NormalizedDocument) -> List[Citation]:
    """본문(표시 텍스트·스캔본 OCR)에서 인용을 추출한다. 숨은 레이어는 적대적 콘텐츠로 별도 처리한다.

    줄 블록을 한 번에 이어 붙인 본문(머리글·바닥글 제외, 한국어 줄바꿈 결합)에서 한 번만 추출한다.
    줄 단위와 쪽 단위로 두 번 훑으면 같은 인용이 범위만 달리해 두 번 잡히고(R11), 줄 단위로는
    두 줄에 걸친 법원·선고일이 잘린다(R3). 위치는 인용이 시작하는 블록 기준으로 되돌린다.
    표는 칸 단위로 따로 추출한다(칸 좌표가 인용 위치다).
    """
    ensure_running_heads(doc)
    reading = build_reading_text(doc)
    out: List[Citation] = []
    seen: set = set()
    for citation in extract_from_text(reading.text, document_id=doc.document_id):
        if citation.span:
            block, offset = reading.locate(citation.span[0])
            if block is not None:
                citation.block_id, citation.page = block.block_id, block.page
                citation.attributes["reading_span"] = list(citation.span)
                citation.span = (offset, offset + citation.span[1] - citation.span[0])
        key = (_identity(citation), citation.block_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(citation)

    _attach_law_alias_candidates(reading.text, out)

    for block in doc.body_blocks():
        if block.block_type != "table":
            continue
        rows = (block.attributes or {}).get("cells") or [line.split(" | ") for line in block.text.splitlines()]
        for r_index, row in enumerate(rows):
            for c_index, cell in enumerate(row):
                text = _cell_text(cell)
                if len(text) < 6:
                    continue
                for citation in extract_from_text(text, document_id=doc.document_id,
                                                  block_id=block.block_id, page=block.page):
                    citation.attributes["table_cell"] = {"table_ref": (block.attributes or {}).get("table_ref"),
                                                         "row": r_index, "column": c_index}
                    key = (_identity(citation), block.block_id, r_index)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(citation)
    return out


# "「…에 관한 법률」(이하 '○○법'이라 한다)"처럼 문서가 스스로 정한 약칭
ALIAS_DEFINITION_RE = re.compile(
    r"[「『](?P<full>[^」』]{3,80})[」』]\s*[(（]\s*(?:이하\s*)?[‘'\"“「『]?(?P<abbr>[가-힣A-Za-z·]{2,30}?)[’'\"”」』]?"
    r"\s*(?:이?라\s*(?:한다|함|칭한다|약칭한다))?\s*[)）]")


def _attach_law_alias_candidates(text: str, citations: List[Citation]) -> None:
    """짧게 쓴 법령명에 같은 문서 안의 정식 법령명을 약칭 후보로 붙인다(교체하지 않는다).

    적힌 이름으로 먼저 조회하고, 목록에 없을 때만 후보로 다시 조회한다(source_review). 근거는
    ① 문서의 약칭 정의("(이하 '○○법'이라 한다)") ② 같은 문서에 인용된 정식 법령명이 짧은 이름의
    어간(끝의 '법'을 뗀 4자 이상)으로 시작하는 경우이며, 후보가 하나일 때만 붙인다.
    """
    statutes = [c for c in citations if c.type == CitationType.STATUTE and c.law_name]
    defined = {}
    for m in ALIAS_DEFINITION_RE.finditer(text):
        full, abbr = canonical_law_name(m.group("full")), m.group("abbr").strip()
        if abbr.endswith("법") and full.replace(" ", "") != abbr.replace(" ", ""):
            defined[abbr.replace(" ", "")] = full
    full_names = {c.law_name for c in statutes if " " in c.law_name}
    for citation in statutes:
        written = citation.law_name.replace(" ", "")
        if " " in citation.law_name or not written.endswith("법"):
            continue
        if written in defined:
            citation.attributes.update(law_alias_candidate=defined[written], law_alias_basis="DOCUMENT_DEFINITION")
            continue
        stem = written[:-1]
        if len(stem) < 4:
            continue
        candidates = sorted(f for f in full_names if f.replace(" ", "").startswith(stem) and f.replace(" ", "") != written)
        if len(candidates) == 1:
            citation.attributes.update(law_alias_candidate=candidates[0], law_alias_basis="DOCUMENT_FULL_NAME_PREFIX")
