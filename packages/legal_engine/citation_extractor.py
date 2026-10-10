"""제9.1장 Citation Extraction.

판례·법령·헌재결정·법령해석례·행정심판·학술자료를 Regex/Rule 기반으로 먼저 구조화한다.
주변 문맥의 의미분석만 LLM Structured Output을 사용한다(선택적).
"""
from __future__ import annotations

import bisect
import re
from array import array
from dataclasses import fields, make_dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from packages.common.enums import CitationType
from packages.common.schemas import Citation, NormalizedDocument, new_id

from packages.document_engine.reading_text import (QUOTE_SPAN_RE, build_reading_text, ensure_running_heads,
                                                    iter_sentence_bounds, join_separator, sentence_bounds)

from .normalize import (canonical_case_number, canonical_date, canonical_law_name as _raw_canonical_law_name,
                        law_name_suffix)

# 법령명 정규화 결과 캐시 (문서 내 반복 인용 시 수십 개 정규식 재컴파일/탐색 방지, TK-72)
canonical_law_name = lru_cache(maxsize=4096)(_raw_canonical_law_name)

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
    rf"(?P<case_no>(?:(?:19|20)\d{{2}}|\d{{2}})\s*헌\s*[가-힣]{{1,2}}\s*\d{{1,6}}(?!\d))"
    # 병합 표기: 2004헌마554·566(병합), 2011헌바379 등(병합), 2004헌마554, 2004헌마566(병합)
    rf"(?P<merged>(?:\s*[·ㆍ,]\s*(?:(?:(?:19|20)\d{{2}}|\d{{2}})\s*헌\s*[가-힣]{{1,2}}\s*)?\d{{1,6}}(?!\d))*\s*(?:등\s*)?\(\s*병합\s*\))?"
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
_LAW_NAME_PATTERN = r"[「『]?[가-힣A-Za-z· ]{1,40}?(?:법|법률|령|규칙|조례|훈령|예규|규정|고시|지침)[」』]?"
LAW_RE = re.compile(
    rf"(?P<law>{_LAW_NAME_PATTERN})\s*"
    r"(?:부칙\s*)?"
    r"제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<article_sub>\d+))?"
    r"(?:\s*제\s*(?P<paragraph>\d+)\s*항)?"
    r"(?:\s*제\s*(?P<item>\d+)\s*호(?:\s*의\s*(?P<item_sub>\d+))?)?"
    r"(?:\s*(?P<subitem>[가-힣])\s*목)?"
)
_LAW_ARTICLE_ANCHOR_RE = re.compile(r"제\s*\d+\s*조")
_LAW_NAME_END_RE = re.compile(_LAW_NAME_PATTERN + r"\Z")
# 원래 문법: 이름 본체 최대 40자 + 접미사 최대 2자 + 낫표 2자.
_LAW_NAME_MAX_LENGTH = 40 + 2 + 2


@lru_cache(maxsize=4096)
def _law_prefix_start(prefix: str) -> Optional[int]:
    match = _LAW_NAME_END_RE.search(prefix)
    return match.start() if match else None


def _law_matches(text: str):
    """필수 조 위치에서 원래 이름 문법을 확인하고 원래 Match를 반환한다.

    이름 밖 공백/부칙은 길이를 제한하지 않는다. 문법상 가능한 이름 구간만
    캐시하므로 인용문 뒤 일반 문장을 시작점마다 반복 탐색하지 않는다.
    """
    previous_end = 0
    for article in _LAW_ARTICLE_ANCHOR_RE.finditer(text):
        if article.start() < previous_end:
            continue
        name_end = article.start()
        while name_end > previous_end and text[name_end - 1].isspace():
            name_end -= 1
        if text[max(previous_end, name_end - 2):name_end] == "부칙":
            name_end -= 2
            while name_end > previous_end and text[name_end - 1].isspace():
                name_end -= 1
        begin = max(previous_end, name_end - _LAW_NAME_MAX_LENGTH)
        offset = _law_prefix_start(text[begin:name_end])
        if offset is None:
            continue
        match = LAW_RE.match(text, begin + offset)
        if match is not None:
            yield match
            previous_end = match.end()


# 앞 조문 인용에 이어지는 조문: "및 제751조", ", 제4조 제2항", "와 제9조의2"
CONTINUED_ARTICLE_RE = re.compile(
    r"\s*(?:,|및|또는|와|과|·|ㆍ|(?:은|는)\s*[^.?!。\n「」『』,]{1,90},|"
    # "제10조의 누설죄 또는 제11조의 탐지·수집죄": 죄명·규정을 사이에 두고 이어진 같은 법령의 조문
    # "제750조의 불법행위 책임 또는 제756조"도 같다(죄명·책임 이름은 한 번까지 띄어 쓸 수 있다).
    r"의\s*(?:[가-힣·ㆍ]{1,12}\s)?[가-힣·ㆍ]{0,12}(?:죄|규정|조항|책임)\s*(?:또는|및|,|이나|과|와))"
    r"\s*(?P<ref>제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<article_sub>\d+))?"
    r"(?:\s*제\s*(?P<paragraph>\d+)\s*항)?(?:\s*제\s*(?P<item>\d+)\s*호)?)")
# "같은 법", "동법", "같은 법률": 앞서 인용한 법령을 가리킨다.
# "동법 시행령"·"같은 법 시행규칙"은 앞서 인용한 법률의 하위 법령이다.
SAME_LAW_RE = re.compile(r"(?:^|\s)(?:같은|동|위)\s*법(?:률)?(?:\s*(?P<sub>시행령|시행규칙))?$")
# 앞 인용의 조를 가리키는 표현(추가지시 G3): "같은 조 제2항", "동조 제2항", "위 조항", 그리고 조 없이 쓴 "제2항".
SAME_ARTICLE_REF_RE = re.compile(
    # '같은 조건'·'위조한'·'동조하였다'는 조 인용이 아니다. 조(항) 뒤가 공백·문장부호·조사일 때만 잡는다.
    r"(?P<ref>(?:같은|동|위)\s*조(?:항)?|동조(?:항)?)(?=\s|[,.)」』]|은|는|이|가|의|에|을|를|도|$)"
    r"(?:\s*제\s*(?P<paragraph>\d+)\s*항)?(?:\s*제\s*(?P<item>\d+)\s*호)?")
BARE_PARAGRAPH_REF_RE = re.compile(r"제(?<![\d조]제)(?<!조\s제)\s*(?P<paragraph>\d+)\s*항(?:\s*제\s*(?P<item>\d+)\s*호)?")
REFERENCE_WINDOW = 300  # 앞 인용과 이 거리 안에 있을 때만 결합한다(문단을 건너 결합하지 않는다)
# 행정규칙(훈령·예규·고시·지침). 법령 검증과 다른 경로로 검증한다.
ADMIN_RULE_KINDS = ("훈령", "예규", "고시", "지침")
_KIND = "|".join(ADMIN_RULE_KINDS)
AGENCY_RE = r"[가-힣]{1,20}?(?:부|처|청|원|위원회|본부|사령부|총장|실)"
# "국방부훈령 제2345호", "행정안전부 예규 제12호", "국방부 훈령 제2024-3호"
ADMIN_RULE_REF_RE = re.compile(
    rf"(?P<agency>{AGENCY_RE})\s*(?P<kind>{_KIND})\s*제\s*(?P<number>\d+(?:\s*-\s*\d+)?)\s*호"
)
# 행정규칙 이름 인용부호: 낫표(「」『』) 및 따옴표(' " ‘ ’ “ ”) 지원
BRACKET_NAME_RE = re.compile(r"(?:[「『]|['\"‘“])(?P<name>[^」』'\"’”\n]{2,60})(?:[」』]|['\"’”])")
EFFECTIVE_RE = re.compile(rf"(?P<date>{DATE_RE})\s*(?:부터\s*)?시행")
ARTICLE_RE = re.compile(r"제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?(?:\s*\([^)\n]{1,40}\))?(?:\s*제\s*(?P<paragraph>\d+)\s*항)?")
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

# --- 줄바꿈으로 갈라진 법령명 결합 전처리 (TK-07) --------------------------------
# 낫표(「」,『』) 안의 줄바꿈: 「군인\n징계령」→「군인 징계령」
_BRACKET_NEWLINE_RE = re.compile(r"([「『][^」』\n]{1,30})\n([^」』\n]{1,30}[」』])")
# 법령명 접미사(법/령/규칙/훈령 등) 직전 줄바꿈: "징계업무\n처리 훈령"→"징계업무 처리 훈령"
_PRESUFFIX_NEWLINE_RE = re.compile(
    r"([가-힣])\n([가-힣·\s]{0,20}?(?:법률|법|령|규칙|조례|훈령|예규|규정|고시|지침)[」』]?\s*제\s*\d)"
)


def _join_hard_wrapped_citations(text: str) -> str:
    """텍스트 입력에서 줄바꿈으로 갈라진 법령 인용을 공백으로 결합한다.

    '\\n' → ' ' 치환이므로 문자열 길이가 보존되어 span 보정이 필요 없다.
    두 가지 패턴을 처리한다:
    1) 낫표(「」,『』) 안의 줄바꿈
    2) 한글 뒤의 줄바꿈 + 법령명 접미사(법/령/규칙/훈령 등)로 이어지는 줄바꿈
    """
    # 개행 문자가 없는 텍스트는 결합 전처리를 생략한다
    if "\n" not in text:
        return text
    # 낫표 안의 줄바꿈 — 한 번의 줄바꿈만 허용(두 줄 이상 떨어진 것은 별도 인용)
    text = _BRACKET_NEWLINE_RE.sub(r"\1 \2", text)
    # 법령명 접미사 직전 줄바꿈
    text = _PRESUFFIX_NEWLINE_RE.sub(r"\1 \2", text)
    return text


def _admin_rule_citation(text: str, anchor_start: int, anchor_end: int, *, agency=None, kind=None,
                         number=None, name=None, article=None, sub=None, paragraph=None,
                         document_id=None, block_id=None, page=None, sentence_index=None, _create=None) -> Citation:
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
    if sentence_index is None:
        sentence_index = _AdminSentences(text)
    delegation, effect = sentence_index.context(anchor_start, anchor_end)
    article_text = f"{article}의{sub}" if article and sub else article
    return (_create or Citation.create)(
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
            "delegation_basis": " ".join(delegation.split()) if delegation else None,
            "claimed_effect": effect,
        },
    )


# 법령해석례 / 행정심판재결례
# 03fdcdb 원본 구조를 유지하여 앞 공백 경계 어긋남으로 인한 중복 추출(1건->2건) 방지 (TK-72)
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

# 제목을 먼저 찾고 출판정보의 공백은 한 경로에서만 소비한다.
_ACADEMIC_ORIGINAL_BODY = (
    r'(?:[「『\"“](?P<title>[^」』\"”]{5,120})[」』\"”])\s*,\s*'
    r'(?P<journal>[가-힣A-Za-z\s]{2,40}?)\s*'
    r'(?:제?\s*(?P<volume>\d+)\s*권)?\s*(?:제?\s*(?P<issue>\d+)\s*호)?\s*[,(]?\s*'
    r'(?P<year>(?:19|20)\d{2})'
)
_ACADEMIC_BODY_MATCH_RE = re.compile(_ACADEMIC_ORIGINAL_BODY)
_ACADEMIC_OPEN_RE = re.compile(r'[「『\"“]')
_ACADEMIC_TITLE_RE = re.compile(r'[「『\"“][^」』\"”]{5,120}[」』\"”]\s*+,')
_ACADEMIC_PUBLICATION_RE = re.compile(
    r'[가-힣A-Za-z\s]{2,40}?\s*+'
    r'(?:(?:제\s*+)?\d+\s*+권\s*+)?'
    r'(?:(?:제\s*+)?\d+\s*+호\s*+)?[,(]?\s*+(?:19|20)\d{2}'
)
_ACADEMIC_MATCH_RE = re.compile(
    r'(?P<authors>[가-힣][가-힣○△□*]{1,3}(?:\s*[·,]\s*[가-힣][가-힣○△□*]{1,3})*)\s*,\s*'
    + _ACADEMIC_ORIGINAL_BODY
)
_SPACE_RE = re.compile(r'\s*')
_AUTHOR_RE = re.compile(r'[가-힣][가-힣○△□*]{1,3}')
AUTHOR_TOKEN_RE = re.compile(r'^[가-힣][가-힣○△□*]{1,3}$')


def _author_start(text: str, body_start: int, lower: int) -> Optional[int]:
    """원본 저자 문법의 가장 이른 시작을 찾는다. 전체 prefix나 문장 창을 복사하지 않는다."""
    i = body_start
    while i > lower and text[i - 1].isspace():
        i -= 1
    if i <= lower or text[i - 1] != ',':
        return None
    i -= 1
    first = None
    while i > lower:
        while i > lower and text[i - 1].isspace():
            i -= 1
        end = i
        # 이름 한 개의 원래 2~4자 문법이다. 저자 수에는 상한이 없다.
        begin = max(lower, end - 4)
        for j in range(begin, end - 1):
            if _AUTHOR_RE.fullmatch(text, j, end):
                first = j
                break
        else:
            break
        i = first
        while i > lower and text[i - 1].isspace():
            i -= 1
        if i <= lower or text[i - 1] not in '·,':
            break
        i -= 1
    return first


def _academic_candidates(text, pos, endpos):
    for anchor in _ACADEMIC_OPEN_RE.finditer(text, pos, endpos):
        body = _ACADEMIC_TITLE_RE.match(text, anchor.start(), endpos)
        if body is None:
            continue
        publication_start = _SPACE_RE.match(text, body.end(), endpos).end()
        # 쉼표 뒤 공백은 원본 journal의 최소 2자에도 쓰일 수 있다.
        if any(_ACADEMIC_PUBLICATION_RE.match(text, at, endpos)
               for at in range(publication_start, max(body.end(), publication_start - 2) - 1, -1)):
            yield body.start()


class _PatternSearchMethods:
    def search(self, text, pos=0, endpos=None):
        return next(self.finditer(text, pos, endpos), None)

    def match(self, text, pos=0, endpos=None):
        match = self.search(text, pos, endpos)
        return match if match is not None and match.start() == pos else None

    def fullmatch(self, text, pos=0, endpos=None):
        match = self.match(text, pos, endpos)
        endpos = len(text) if endpos is None else min(endpos, len(text))
        return match if match is not None and match.end() == endpos else None

    def findall(self, text, pos=0, endpos=None):
        return [tuple('' if value is None else value for value in m.groups())
                for m in self.finditer(text, pos, endpos)]


class _AcademicBodyPattern(_PatternSearchMethods):
    """앞선 TK-72의 공개 BODY 심볼도 안전한 finditer 경로로 보존한다."""
    pattern = _ACADEMIC_BODY_MATCH_RE.pattern
    flags = _ACADEMIC_BODY_MATCH_RE.flags
    groups = _ACADEMIC_BODY_MATCH_RE.groups
    groupindex = _ACADEMIC_BODY_MATCH_RE.groupindex

    def finditer(self, text, pos=0, endpos=None):
        endpos = len(text) if endpos is None else endpos
        lower = max(0, pos)
        for start in _academic_candidates(text, lower, endpos):
            if start < lower:
                continue
            match = _ACADEMIC_BODY_MATCH_RE.match(text, start, endpos)
            if match is not None:
                yield match
                lower = match.end()


ACADEMIC_BODY_RE = _AcademicBodyPattern()


class _AcademicPattern(_PatternSearchMethods):
    """ACADEMIC_RE의 finditer/group 계약. 검증된 위치에만 원본 저자 문법을 match한다."""
    pattern = _ACADEMIC_MATCH_RE.pattern
    flags = _ACADEMIC_MATCH_RE.flags
    groups = _ACADEMIC_MATCH_RE.groups
    groupindex = _ACADEMIC_MATCH_RE.groupindex

    def finditer(self, text, pos=0, endpos=None):
        endpos = len(text) if endpos is None else endpos
        lower = max(0, pos)
        for body_start in _academic_candidates(text, lower, endpos):
            if body_start < lower:
                continue
            start = _author_start(text, body_start, lower)
            if start is None:
                continue
            match = _ACADEMIC_MATCH_RE.match(text, start, endpos)
            if match is not None:
                yield match
                lower = match.end()



ACADEMIC_RE = _AcademicPattern()


_INTERPRETATION_ANCHOR_RE = re.compile(r'법령해석|유권해석')
_INTERPRETATION_AUTHORITIES = ('법제처', '법무부', '국방부', '행정안전부')


def _interpretation_matches(text):
    """필수 낱말을 먼저 찾되 원본의 앞 공백 및 기관명 span을 보존한다."""
    lower = 0
    for anchor in _INTERPRETATION_ANCHOR_RE.finditer(text):
        if anchor.start() < lower:
            continue
        start = anchor.start()
        while start > lower and text[start - 1].isspace():
            start -= 1
        for authority in _INTERPRETATION_AUTHORITIES:
            at = start - len(authority)
            if at >= lower and text.startswith(authority, at, start):
                start = at
                break
        match = INTERPRETATION_RE.match(text, start)
        if match is not None:
            yield match
            lower = match.end()


QUOTE_RE = re.compile(r"[“\"]([^”\"]{10,600})[”\"]")


_LEAD_STRIP_RE = re.compile(r"^[\s\d가-하.)(]*[.)]\s*")


def _quote_near(text: str, index: int, window: int = 400) -> Optional[str]:
    """인용 앞뒤에서 직접 인용문을 찾는다."""
    segment = text[max(0, index - window) : index + window]
    if '"' not in segment and "“" not in segment:
        return None
    offset = max(0, index - window)
    quotes = list(QUOTE_RE.finditer(segment))
    nearest = min(quotes, key=lambda m: min(abs(offset + m.start() - index), abs(offset + m.end() - index)), default=None)
    return nearest.group(1) if nearest else None


class _SpanNode:
    __slots__ = ('start', 'end', 'left', 'right', 'height', 'maximum')

    def __init__(self, start, end):
        self.start, self.end = start, end
        self.left = self.right = None
        self.height = 1
        self.maximum = end


def _span_height(node):
    return node.height if node else 0


def _span_refresh(node):
    node.height = 1 + max(_span_height(node.left), _span_height(node.right))
    node.maximum = max(node.end, node.left.maximum if node.left else -1,
                       node.right.maximum if node.right else -1)
    return node


def _span_rotate(node, left):
    child = node.right if left else node.left
    if left:
        node.right, child.left = child.left, node
    else:
        node.left, child.right = child.right, node
    _span_refresh(node)
    return _span_refresh(child)


def _span_insert(node, start, end):
    if node is None:
        return _SpanNode(start, end)
    if start == node.start:
        node.end = max(node.end, end)
    elif start < node.start:
        node.left = _span_insert(node.left, start, end)
    else:
        node.right = _span_insert(node.right, start, end)
    _span_refresh(node)
    balance = _span_height(node.left) - _span_height(node.right)
    if balance > 1:
        if start > node.left.start:
            node.left = _span_rotate(node.left, True)
        return _span_rotate(node, False)
    if balance < -1:
        if start < node.right.start:
            node.right = _span_rotate(node.right, False)
        return _span_rotate(node, True)
    return node


def _span_max_before(node, at, inclusive):
    high = -1
    while node is not None:
        if node.start < at or inclusive and node.start == at:
            high = max(high, node.end, node.left.maximum if node.left else -1)
            node = node.right
        else:
            node = node.left
    return high


class SpanTracker:
    """원본 두 끝점의 겹침 조건을 미봉합 구간까지 즉시 질의한다.

    단조 증가 패턴은 append와 최대 종료 색인으로 처리한다. 확장 span이 역전되는
    패턴만 AVL 색인으로 바꿔 임의 순서에서도 O(log C) 질의/삽입을 보장한다.
    """
    __slots__ = ('starts', 'ends', 'cur_starts', 'cur_ends', '_cur_max', '_tree')

    def __init__(self):
        self.starts, self.ends = [], []
        self.cur_starts, self.cur_ends, self._cur_max = [], [], []
        self._tree = None

    def seal_pattern(self):
        if not self.cur_starts:
            return
        if not self.starts and self._tree is None:
            self.starts, self.ends = self.cur_starts, self._cur_max
            self.cur_starts, self.cur_ends, self._cur_max = [], [], []
            return
        pairs = list(zip(self.starts, self.ends)) + list(zip(self.cur_starts, self.cur_ends))
        pairs.sort()
        self.starts, self.ends = [], []
        high = -1
        for start, end in pairs:
            high = max(high, end)
            self.starts.append(start)
            self.ends.append(high)
        self.cur_starts, self.cur_ends, self._cur_max = [], [], []
        self._tree = None

    @staticmethod
    def _contains(starts, ends, start, end):
        if not starts or start >= ends[-1] and end > ends[-1]:
            return False
        i = bisect.bisect_right(starts, start) - 1
        if i >= 0 and ends[i] > start:
            return True
        i = bisect.bisect_left(starts, end) - 1
        return i >= 0 and ends[i] >= end

    def overlaps(self, start, end):
        if self._contains(self.starts, self.ends, start, end):
            return True
        if self._tree is not None:
            return (_span_max_before(self._tree, start, True) > start or
                    _span_max_before(self._tree, end, False) >= end)
        return self._contains(self.cur_starts, self._cur_max, start, end)

    def add(self, start, end):
        if self._tree is not None:
            self._tree = _span_insert(self._tree, start, end)
        elif self.cur_starts and start < self.cur_starts[-1]:
            for s, e in zip(self.cur_starts, self.cur_ends):
                self._tree = _span_insert(self._tree, s, e)
            self._tree = _span_insert(self._tree, start, end)
        self.cur_starts.append(start)
        self.cur_ends.append(end)
        self._cur_max.append(self._cur_max[-1] if self._cur_max and self._cur_max[-1] > end else end)

    def append(self, span):
        self.add(*span)


def extract_from_text(
    text: str, *, document_id: Optional[str] = None, block_id: Optional[str] = None, page: Optional[int] = None,
    _create=None, _select=None, _collection=None
) -> List[Citation]:
    # TK-07: 줄바꿈으로 갈라진 법령 인용을 공백으로 결합 (길이 불변)
    text = _join_hard_wrapped_citations(text)
    _create = _create or Citation.create
    citations = _collection if _collection is not None else []
    consumed = SpanTracker()
    overlaps = consumed.overlaps

    has_quotes = any(q in text for q in ('"', "“"))
    quote_near = (lambda idx: _quote_near(text, idx)) if has_quotes else (lambda idx: None)

    # 해석례 및 행정심판: 관련 키워드가 있는 경우에만 정규식 탐색 수행 (TK-72)
    if any(k in text for k in ("해석", "회신", "심판", "법제처")):
        for pattern, kind in (
            (INTERPRETATION_FULL_RE, CitationType.INTERPRETATION),
            (DATED_INTERPRETATION_RE, CitationType.INTERPRETATION),
            (INTERPRETATION_RE, CitationType.INTERPRETATION),
            (ADMIN_APPEAL_RE, CitationType.ADMIN_APPEAL),
        ):
            for m in (_interpretation_matches(text) if pattern is INTERPRETATION_RE else pattern.finditer(text)):
                if overlaps(m.start(), m.end()):
                    continue
                number = re.sub(r"\s+", "", m.group("no")) if m.group("no") else None
                citations.append(_create(
                    kind, m.group(0).strip(), document_id=document_id, block_id=block_id,
                    page=page, span=(m.start(), m.end()), case_number=number,
                    canonical_case_number=number, court=m.group("authority"),
                    decision_date=canonical_date(m.groupdict().get("date") or ""),
                    quoted_text=quote_near(m.end()),
                    context=text[max(0, m.start() - 120):m.end() + 200],
                ))
                consumed.append((m.start(), m.end()))
            consumed.seal_pattern()

    # 필수 문자/종결어가 없는 패턴만 생략한다. FULL_CASE에는 kind를 요구하지 않는다.
    # 1) 헌재
    for m in (CONST_RE.finditer(text) if "헌" in text else ()):
        citations.append(
            _create(
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
                quoted_text=quote_near(m.end()),
                context=text[max(0, m.start() - 120) : m.end() + 120],
                attributes=_merged_attributes(m.group("case_no"), m.group("merged")),
            )
        )
        consumed.append((m.start(), m.end()))
    consumed.seal_pattern()

    # 2) 완전한 판례 인용. 종결어가 없어도 매칭한다.
    for m in (FULL_CASE_RE.finditer(text) if "원" in text or "헌" in text else ()):
        if overlaps(m.start(), m.end()):
            continue
        case_no = m.group("case_no")
        citations.append(
            _create(
                CitationType.CASE,
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
                quoted_text=quote_near(m.end()),
                context=text[max(0, m.start() - 120) : m.end() + 200],
            )
        )
        if m.group("case_name"):
            citations[-1].attributes["case_name"] = m.group("case_name")
        consumed.append((m.start(), m.end()))
    consumed.seal_pattern()

    for m in (BARE_CASE_RE.finditer(text) if any(k in text for k in ("판결", "결정", "명령")) else ()):
        if overlaps(m.start(), m.end()):
            continue
        case_no = m.group("case_no")
        citations.append(
            _create(
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
                quoted_text=quote_near(m.end()),
                context=text[max(0, m.start() - 120) : m.end() + 200],
            )
        )
        consumed.append((m.start(), m.end()))
    consumed.seal_pattern()

    admin_sentences = _AdminSentences(text) if any(k in text for k in ADMIN_RULE_KINDS) else None
    # 4-1) 행정규칙 (훈령, 예규, 고시, 지침이 있을 때만 수행)
    if any(k in text for k in ADMIN_RULE_KINDS):
        for m in ADMIN_RULE_REF_RE.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            start, end = m.start(), m.end()
            name = None
            before = list(BRACKET_NAME_RE.finditer(text, max(0, start - 70), start))
            if before and re.fullmatch(r"[\s(（]*", text[before[-1].end():start]):
                name, start = before[-1].group("name"), before[-1].start()
            after = BRACKET_NAME_RE.match(text, end + len(re.compile(r"[\s,]*").match(text, end).group(0)))
            if name is None and after:
                name, end = after.group("name"), after.end()
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
                sentence_index=admin_sentences, _create=_create, **located))
            consumed.append((start, end))
        consumed.seal_pattern()

    # 4) 법령 (조문 "조"가 있을 때만 수행)
    previous_law: Optional[str] = None
    if "조" in text:
        for m in _law_matches(text):
            if overlaps(m.start(), m.end()):
                continue
            raw_law = m.group("law")
            same_law = SAME_LAW_RE.search(raw_law) if ("법" in raw_law and ("같은" in raw_law or "동" in raw_law or "위" in raw_law)) else None
            if same_law:
                if previous_law is None:
                    continue
                base = re.sub(r"\s*시행(?:령|규칙)$", "", previous_law)
                law_name = f"{base} {same_law.group('sub')}" if same_law.group("sub") else previous_law
                start = m.start("law") + same_law.start()
            else:
                law_name = canonical_law_name(raw_law)
                start = _law_name_start(m)
            if len(law_name) < 2:
                continue
            previous_law = base if same_law and same_law.group("sub") else law_name
            if law_name.endswith(ADMIN_RULE_KINDS):
                kind = next(k for k in ADMIN_RULE_KINDS if law_name.endswith(k))
                if law_name == kind:
                    earlier = [n.group("name").strip() for n in BRACKET_NAME_RE.finditer(text, max(0, m.start() - 600), m.start())
                               if n.group("name").strip().endswith(kind)]
                    if earlier:
                        law_name = earlier[-1]
                citations.append(_admin_rule_citation(
                    text, m.start(), m.end(), kind=kind, name=law_name,
                    article=m.group("article"), sub=m.group("article_sub"), paragraph=m.group("paragraph"),
                    document_id=document_id, block_id=block_id, page=page, sentence_index=admin_sentences, _create=_create))
                consumed.append((m.start(), m.end()))
                continue
            article = m.group("article")
            if m.group("article_sub"):
                article = f"{article}의{m.group('article_sub')}"

            ext_end = m.end()
            attr_dict: Dict[str, Any] = {}
            if m.group("subitem") and m.group("item"):
                from .temporal_review import SUBITEM_WINDOW_LIMIT, parse_subitem_sequence
                subitems_seq, consumed_len = parse_subitem_sequence(
                    text[m.end():m.end() + SUBITEM_WINDOW_LIMIT], m.group("subitem"))
                if consumed_len > 0:
                    ext_end = m.end() + consumed_len
                if subitems_seq:
                    attr_dict["subitem"] = subitems_seq[0]
                    attr_dict["subitems"] = subitems_seq

            raw_cit = text[start:ext_end].strip()
            citations.append(
                _create(
                    CitationType.STATUTE,
                    raw_cit,
                    document_id=document_id,
                    block_id=block_id,
                    page=page,
                    span=(start, ext_end),
                    law_name=law_name,
                    article=article,
                    paragraph=m.group("paragraph"),
                    item=(f"{m.group('item')}의{m.group('item_sub')}" if m.group("item_sub") else m.group("item")),
                    quoted_text=quote_near(ext_end),
                    context=text[max(0, start - 100) : ext_end + 150],
                    attributes=attr_dict if attr_dict else {},
                )
            )
            consumed.append((start, ext_end))
            head_id, position = citations[-1].citation_id, ext_end
            while (more := CONTINUED_ARTICLE_RE.match(text, position)):
                bridge = text[position:more.start("ref")]
                if re.search(r"[가-힣]+법(?:률)?(?=[과와은는이가을를의에도만로]|[^가-힣]|$)|제\s*\d+\s*조", bridge):
                    break
                number = more.group("article") + (f"의{more.group('article_sub')}" if more.group("article_sub") else "")
                span_start = more.start("ref")
                citations.append(_create(
                    CitationType.STATUTE, f"{law_name} {text[span_start:more.end()].strip()}",
                    document_id=document_id, block_id=block_id, page=page, span=(span_start, more.end()),
                    law_name=law_name, article=number, paragraph=more.group("paragraph"), item=more.group("item"),
                    quoted_text=quote_near(more.end()),
                    context=text[max(0, start - 100): more.end() + 150],
                    attributes={"continued_from": head_id}))
                consumed.append((span_start, more.end()))
                position = more.end()

        consumed.seal_pattern()
        # 4-2) 앞 인용의 조를 가리키는 표현 해결
        _resolve_article_references(text, citations, consumed, overlaps, document_id=document_id,
                                    block_id=block_id, page=page, _create=_create)
        consumed.seal_pattern()

    # 5) 학술자료: 겹쳐진 제목 시작도 검사하고 검증된 저자·출판정보 위치만 매칭한다.
    if any(q in text for q in ("「", "『", '"', "“")):
        for m in ACADEMIC_RE.finditer(text):
            g_start, g_end = m.span()
            authors = [a.strip() for a in m.group('authors').split('·') if a.strip()]
            if overlaps(g_start, g_end):
                continue
            citations.append(
                _create(
                    CitationType.ACADEMIC,
                    text[g_start:g_end].strip(),
                    document_id=document_id,
                    block_id=block_id,
                    page=page,
                    span=(g_start, g_end),
                    title=m.group("title").strip(),
                    authors=authors,
                    journal=m.group("journal").strip(),
                    year=int(m.group("year")),
                    context=text[max(0, g_start - 80) : g_end + 120],
                )
            )
            consumed.append((g_start, g_end))
        consumed.seal_pattern()

    # DOI (10. 키워드가 있을 때만 수행)
    if "10." in text:
        for m in DOI_RE.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            citations.append(
                _create(
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
        consumed.seal_pattern()

    retained = _select(citations) if _select is not None else citations
    if not retained:
        return retained
    targets = {c.citation_id for c in retained} if _select is not None else None
    bind_quotes(text, citations, _targets=targets)
    attach_claim_text(text, citations, _targets=targets)
    return retained


_STATUTE_TYPES = (CitationType.STATUTE,)


def _resolve_article_references(text, citations, consumed, overlaps, *, document_id, block_id, page, _create=Citation.create) -> None:
    references = []
    patterns = [BARE_PARAGRAPH_REF_RE]
    if any(word in text for word in ("같은", "동", "위")):
        patterns.insert(0, SAME_ARTICLE_REF_RE)
    for pattern in patterns:
        references += [m for m in pattern.finditer(text) if not overlaps(m.start(), m.end())]
    if not references:
        return
    # 법령 인용 목록의 종료 위치들을 정렬된 리스트로 유지하여 O(log N) 이진 탐색 (TK-72)
    statute_citations = sorted(
        [c for c in citations if c.type in _STATUTE_TYPES and c.span],
        key=lambda c: c.span[1],
    )
    statute_ends = [c.span[1] for c in statute_citations]

    original_index = 0
    base = None
    for m in sorted(references, key=lambda r: r.start()):
        if overlaps(m.start(), m.end()):
            continue
        while original_index < len(statute_citations) and statute_ends[original_index] <= m.start():
            candidate = statute_citations[original_index]
            if base is None or candidate.span[1] > base.span[1]:
                base = candidate
            original_index += 1
        if base is None or m.start() - base.span[1] > REFERENCE_WINDOW:
            continue
        bare = m.re is BARE_PARAGRAPH_REF_RE
        paragraph = m.group("paragraph") or (None if bare else base.paragraph)
        if bare and not paragraph:
            continue
        item = m.group("item") or (None if (bare or m.group("paragraph")) else base.item)
        label = f"{base.law_name} 제{base.article}조" + (f" 제{paragraph}항" if paragraph else "") + (f" 제{item}호" if item else "")
        citation = _create(
            CitationType.STATUTE, m.group(0).strip(), document_id=document_id, block_id=block_id, page=page,
            span=(m.start(), m.end()), law_name=base.law_name, article=base.article, paragraph=paragraph, item=item,
            quoted_text=_quote_near(text, m.end()), context=text[max(0, m.start() - 100):m.end() + 150])
        citation.attributes.update({"resolved_label": label, "reference_to": base.raw_text,
                                    "reference_kind": "BARE_PARAGRAPH" if bare else "SAME_ARTICLE"})
        citations.append(citation)
        consumed.append((m.start(), m.end()))
        base = citation


class _AdminSentences:
    """행정규칙용 문장 경계와 문장별 공통 문맥을 한 번만 계산한다."""
    def __init__(self, text):
        self.text = text
        self.starts, self.ends = [], []
        for m in SENTENCE_END_RE.finditer(text):
            self.starts.append(m.start())
            self.ends.append(m.end())
        self.cache = {}

    def context(self, start, end):
        before = bisect.bisect_right(self.ends, start)
        after = bisect.bisect_left(self.starts, end)
        bounds = (self.ends[before - 1] if before else 0,
                  self.ends[after] if after < len(self.ends) else len(self.text))
        if bounds not in self.cache:
            delegation = DELEGATION_RE.search(self.text, *bounds)
            effect = CLAIMED_EFFECT_RE.search(self.text, *bounds)
            self.cache[bounds] = (delegation.group('basis') if delegation else None,
                                  effect.group(0) if effect else None)
        return self.cache[bounds]


class _ClaimIndex:
    """축약된 공백과 원래 위치의 색인. 400자 출력을 위해 긴 문장을 다시 복사하지 않는다."""
    def __init__(self, text, start, end):
        self.text = text
        self.starts, self.ends, self.offsets = [], [], []
        words, offset = [], 0
        for m in re.finditer(r'\S+', text[start:end]):
            self.starts.append(start + m.start())
            self.ends.append(start + m.end())
            self.offsets.append(offset)
            words.append(m.group(0))
            offset += len(m.group(0)) + 1
        self.clean = ' '.join(words)

    def bounds(self, start, end):
        lo = bisect.bisect_right(self.ends, start)
        hi = bisect.bisect_left(self.starts, end)
        if lo >= hi:
            return 0, 0
        begin = self.offsets[lo] + max(0, start - self.starts[lo])
        last = hi - 1
        stop = self.offsets[last] + min(self.ends[last], end) - self.starts[last]
        return begin, stop

    def claim(self, start, end):
        begin, stop = self.bounds(start, end)
        return self.clean[begin:min(stop, begin + 400)]

    def first_word(self, start, end):
        lo = bisect.bisect_right(self.ends, start)
        if lo == len(self.starts) or self.starts[lo] >= end:
            return ''
        begin, stop = max(start, self.starts[lo]), min(end, self.ends[lo])
        # 주어는 조사 한 글자를 뺀 뒤 2~10자여야 한다. 긴 어절을 반복 복사하지 않는다.
        return self.text[begin:stop] if stop - begin <= 11 else ''


_EMPTY_PARENS_RE = re.compile(r'\(\s*\)|\[\s*\]')
_PREFIX_RE = re.compile(r'[\s\d가-하.)(]*')
_PREFIX_END_RE = re.compile(r'[.)]')
_CLAUSE_PUNCT_RE = re.compile(r'[(),，]')



_UNWRAP_NEWLINE_RE = re.compile(r"(?<![.?!:;])\n")
_ENUMERATOR_HEAD_RE = re.compile(r"\d+[.)]|[가-하][.)]|[-•*]")


def _unwrap_claim_lines(text):
    """원본 개행 결합 규칙. 같은 공백 구간 끝의 열거표지는 한 번만 확인한다."""
    if "\n" not in text:
        return text
    whitespace_end, enumerator = -1, False

    def replace(match):
        nonlocal whitespace_end, enumerator
        if match.start() >= whitespace_end:
            whitespace_end = _SPACE_RE.match(text, match.end()).end()
            enumerator = _ENUMERATOR_HEAD_RE.match(text, whitespace_end) is not None
        return "\n" if enumerator else " "

    return _UNWRAP_NEWLINE_RE.sub(replace, text)

def attach_claim_text(text: str, citations: List[Citation], *, _targets=None) -> None:
    """원본 claim 계약을 문장별 병합 순회와 긴 문장의 위치 색인으로 계산한다."""
    target_candidates = citations.originals() if isinstance(citations, _CitationOccurrences) else citations
    if not any(c.span and (_targets is None or c.citation_id in _targets)
               and c.type in (CitationType.STATUTE, CitationType.CASE, CitationType.CONSTITUTIONAL)
               for c in target_candidates):
        return
    unwrapped = _unwrap_claim_lines(text)
    if _targets is None:
        located = sorted((c for c in citations if c.span), key=lambda c: c.span[0])
        bounds = iter_sentence_bounds(unwrapped)
    else:
        # 최종 반환할 인용이 있는 원래 문장만 구체화한다. 그 문장 안의 중복
        # 인용도 전부 포함하므로 다음 인용에서 claim을 끝내는 계약은 같다.
        target_candidates = citations.originals() if isinstance(citations, _CitationOccurrences) else citations
        target_starts = sorted(c.span[0] for c in target_candidates if c.span and c.citation_id in _targets)
        bounds, target_index = [], 0
        for start, end in iter_sentence_bounds(unwrapped):
            if target_index == len(target_starts):
                break
            if target_starts[target_index] < end:
                bounds.append((start, end))
                while target_index < len(target_starts) and target_starts[target_index] < end:
                    target_index += 1
        starts = [start for start, _ in bounds]
        located = []
        candidates = citations.in_bounds(bounds) if isinstance(citations, _CitationOccurrences) else citations
        for c in candidates:
            if c.span:
                index = bisect.bisect_right(starts, c.span[0]) - 1
                if index >= 0 and c.span[0] < bounds[index][1]:
                    located.append(c)
        located.sort(key=lambda c: c.span[0])
    if not located:
        return
    c_idx = 0
    for s_start, s_end in bounds:
        while c_idx < len(located) and located[c_idx].span[0] < s_start:
            c_idx += 1
        inside_end = c_idx
        while inside_end < len(located) and located[inside_end].span[0] < s_end:
            inside_end += 1
        inside = located[c_idx:inside_end]
        c_idx = inside_end
        if not inside:
            continue
        if _targets is not None and not any(c.citation_id in _targets for c in inside):
            continue
        # 작은 문장에서는 기존 split의 상수 비용을 유지한다. 긴 문장만 색인한다.
        indexed = s_end - s_start > 800 and len(inside) > 1
        index = _ClaimIndex(unwrapped, s_start, s_end) if indexed else None
        case_index = None
        if indexed:
            prefix = _PREFIX_RE.match(unwrapped, s_start, s_end)
            prefix_ends = [m.start() for m in _PREFIX_END_RE.finditer(unwrapped, s_start, prefix.end())]
            punct = iter(_CLAUSE_PUNCT_RE.finditer(unwrapped, s_start, s_end))
            next_punct = next(punct, None)
            opened = closed = s_start - 1
            comma = clause_start = s_start
        for position, citation in enumerate(inside):
            if _targets is not None and citation.citation_id not in _targets:
                continue
            start, end = citation.span
            if citation.type in (CitationType.CASE, CitationType.CONSTITUTIONAL):
                if not indexed:
                    claim = unwrapped[s_start:start] + ' ' + unwrapped[end:s_end]
                    citation.attributes['case_claim'] = ' '.join(_EMPTY_PARENS_RE.sub(' ', claim).split())[:400]
                else:
                    if case_index is None:
                        # 원본 정규식은 한 번만 치환한다. 길이를 보존하여 span을 그대로 쓴다.
                        masked = _EMPTY_PARENS_RE.sub(lambda m: ' ' * len(m.group(0)), unwrapped[s_start:s_end])
                        case_index = _ClaimIndex(masked, 0, len(masked))
                    left, right = start, end
                    # 인용을 지우면서 새로 비게 되는 괄호도 원본 한 번 치환과 같이 제거한다.
                    l = index.bounds(s_start, start)[1]
                    r = index.bounds(end, s_end)[0]
                    if l and r < len(index.clean) and (index.clean[l - 1], index.clean[r]) in (('(', ')'), ('[', ']')):
                        li = bisect.bisect_left(index.starts, start) - 1
                        ri = bisect.bisect_right(index.ends, end)
                        left = min(start, index.ends[li]) - 1
                        right = max(end, index.starts[ri]) + 1
                    a = case_index.claim(0, left - s_start)
                    b = case_index.claim(right - s_start, s_end - s_start)
                    citation.attributes['case_claim'] = (a + (' ' if a and b else '') + b)[:400]
                continue
            if citation.type not in _STATUTE_TYPES:
                continue
            if start == s_start:
                paren = False
            elif indexed:
                while next_punct is not None and next_punct.start() < start:
                    at, char = next_punct.start(), next_punct.group(0)
                    if char == '(':
                        opened, clause_start = at, comma
                    elif char == ')':
                        closed = at
                    else:
                        comma = at + 1
                    next_punct = next(punct, None)
                paren = opened > closed
            else:
                opened = unwrapped.rfind('(', s_start, start)
                paren = opened > unwrapped.rfind(')', s_start, start)
                if paren:
                    clause_start = max(unwrapped.rfind(',', s_start, opened), unwrapped.rfind('，', s_start, opened), s_start - 1) + 1
            if paren:
                claim_start, claim_end = clause_start, opened
                citation.attributes['claim_mode'] = 'PARENTHETICAL_BASIS'
            else:
                claim_start = end
                claim_end = inside[position + 1].span[0] if position + 1 < len(inside) else s_end
                if start == s_start:
                    lead = ''
                elif indexed:
                    p = bisect.bisect_left(prefix_ends, start) - 1
                    lead_start = prefix_ends[p] + 1 if p >= 0 else s_start
                    lead = index.first_word(lead_start, start)
                else:
                    words = _LEAD_STRIP_RE.sub('', unwrapped[s_start:start]).split()
                    lead = words[0] if words else ''
                if lead:
                    subject = re.sub(r'(은|는|이|가|의|도)$', '', lead)
                    if 2 <= len(subject) <= 10 and re.fullmatch(r'[가-힣]+', subject):
                        citation.attributes['claim_subject'] = subject
            citation.attributes['claim_text'] = (index.claim(claim_start, claim_end) if indexed else
                                                ' '.join(unwrapped[claim_start:claim_end].split())[:400])


@lru_cache(maxsize=4096)
def _law_name_offset(raw: str) -> int:
    """법령명 앞에 붙어 잡힌 문장 조각을 뺀 법령명의 상대 시작 위치 (TK-72 캐시)."""
    suffix = law_name_suffix(raw)
    clean_raw = re.sub(r"[「」『』]", " ", raw or "")
    first_word = suffix.split()[0] if suffix else ""
    if first_word:
        pos = clean_raw.rfind(first_word)
        if pos >= 0:
            if pos > 0 and raw[pos - 1] in "「『":
                pos -= 1
            return pos
    kept = suffix.split()
    tokens = list(re.finditer(r"[^\s「」『』]+", raw))
    if not kept or len(kept) > len(tokens):
        return 0
    start = tokens[-len(kept)].start()
    if start > 0 and raw[start - 1] in "「『":
        start -= 1
    return start


def _law_name_start(m: "re.Match") -> int:
    """법령명 앞에 붙어 잡힌 문장 조각을 뺀 법령명의 시작 위치."""
    return m.start("law") + _law_name_offset(m.group("law"))


# --- 직접 인용문 결합 --------------------------------------------------------------
_sentences = sentence_bounds
_CASE_TYPES = (CitationType.CASE, CitationType.CONSTITUTIONAL, CitationType.INTERPRETATION,
               CitationType.ADMIN_APPEAL)


def bind_quotes(text: str, citations: List[Citation], *, _targets=None) -> None:
    """직접 인용문을 원본 우선순위로 결합하며 문장마다 위치 색인을 공유한다."""
    originals = citations.originals() if isinstance(citations, _CitationOccurrences) else citations
    for citation in originals:
        citation.quoted_text = None
    if not any(q in text for q in ('"', '“')):
        return
    located = sorted((c for c in citations if c.span), key=lambda c: c.span[0])
    if not located:
        return
    order_key = (lambda c: c.citation_id) if _targets is not None else id
    original_order = {order_key(c): i for i, c in enumerate(citations)}
    c_idx = 0
    for s_start, s_end in _sentences(text):
        while c_idx < len(located) and located[c_idx].span[0] < s_start:
            c_idx += 1
        inside_end = c_idx
        while inside_end < len(located) and located[inside_end].span[0] < s_end:
            inside_end += 1
        inside = located[c_idx:inside_end]
        c_idx = inside_end
        quotes = list(QUOTE_SPAN_RE.finditer(text, s_start, s_end))
        if not inside or not quotes:
            continue
        starts = [c.span[0] for c in inside]
        cases = [c for c in inside if c.type in _CASE_TYPES]
        case_starts = [c.span[0] for c in cases]
        by_end = sorted(inside, key=lambda c: (c.span[1], -original_order[order_key(c)]))
        ends = [c.span[1] for c in by_end]
        closes = [m.start() for m in re.finditer(r'\)', text[s_start:s_end])]
        closes = [s_start + at for at in closes]
        for quote in quotes:
            target = None
            paren = re.compile(r'[^(（]{0,40}?[(（]').match(text, quote.end(), s_end)
            if paren:
                open_at = paren.end()
                close_idx = bisect.bisect_left(closes, open_at)
                close = closes[close_idx] if close_idx < len(closes) else s_end
                case_idx = bisect.bisect_left(case_starts, open_at)
                other_idx = bisect.bisect_left(starts, open_at)
                if case_idx < len(cases) and case_starts[case_idx] < close:
                    target = cases[case_idx]
                elif other_idx < len(inside) and starts[other_idx] < close:
                    target = inside[other_idx]
            if target is None:
                case_idx = bisect.bisect_left(case_starts, quote.end())
                if case_idx < len(cases):
                    target = cases[case_idx]
            if target is None:
                before_idx = bisect.bisect_right(ends, quote.start()) - 1
                if before_idx >= 0:
                    target = by_end[before_idx]
            if target is not None and (_targets is None or target.citation_id in _targets):
                if target.quoted_text is None:
                    target.quoted_text = quote.group(1)
                else:
                    target.attributes.setdefault('additional_quotes', []).append(quote.group(1))


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
    parts = []
    previous = ""
    for line in lines:
        if previous:
            parts.append(join_separator(previous, line))
        parts.append(line)
        previous = line
    return "".join(parts).replace("\n", " ")


_CITATION_FIELDS = fields(Citation)
# 실제 문서 경로의 임시 객체는 공개 스키마와 같은 필드/기본값을 갖는다.
# 인용마다 별도 instance dict를 할당하지 않고 최종 반환 시 Citation으로 만든다.
_PendingCitation = make_dataclass(
    "_PendingCitation", [(field.name, field.type, field) for field in _CITATION_FIELDS], slots=True,
)


class _DuplicateCitation:
    """반환에서 제외되는 인용도 원래 위치·원문·참조 ID를 가진다."""
    __slots__ = ("prototype", "citation_id", "raw_text", "span", "attributes", "quoted_text")

    def __init__(self, prototype, citation_id, raw_text, span, attributes=None):
        self.prototype, self.citation_id = prototype, citation_id
        self.raw_text, self.span = raw_text, span
        self.attributes = attributes if attributes is not None else {}
        self.quoted_text = None

    def __getattr__(self, name):
        return getattr(self.prototype, name)


class _CitationOccurrences:
    """중복 위치는 배열로 보관하고 순회 시 짧게 쓰는 뷰만 만든다."""
    def __init__(self):
        self.values, self.identifiers, self.raw_texts = [], [], []
        self.starts, self.ends = array('q'), array('q')
        self.duplicates = bytearray()

    def append(self, citation):
        duplicate = isinstance(citation, _DuplicateCitation)
        self.duplicates.append(duplicate)
        self.values.append(citation.prototype if duplicate else citation)
        self.identifiers.append(citation.citation_id if duplicate else '')
        self.raw_texts.append(citation.raw_text if duplicate else '')
        self.starts.append(citation.span[0] if duplicate else 0)
        self.ends.append(citation.span[1] if duplicate else 0)

    def __len__(self):
        return len(self.values)

    def __getitem__(self, index):
        if self.duplicates[index]:
            return _DuplicateCitation(self.values[index], self.identifiers[index], self.raw_texts[index],
                                      (self.starts[index], self.ends[index]))
        return self.values[index]

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]

    def originals(self):
        for index, duplicate in enumerate(self.duplicates):
            if not duplicate:
                yield self.values[index]

    def in_bounds(self, bounds):
        starts = [start for start, _ in bounds]
        for index, duplicate in enumerate(self.duplicates):
            span = None if duplicate else self.values[index].span
            if not duplicate and span is None:
                continue
            start = self.starts[index] if duplicate else span[0]
            bound = bisect.bisect_right(starts, start) - 1
            if bound >= 0 and start < bounds[bound][1]:
                yield self[index]


class _CitationBatch:
    """중복 제거가 끝난 뒤 필요한 UUID만 생성한다. 내부 참조도 함께 확정한다."""
    def __init__(self, reading=None):
        self.count = 0
        self.reading = reading
        self.prototypes = {}
        self.body = _CitationOccurrences()

    def create(self, type, raw_text, **fields):
        self.count += 1
        identifier = f'@extraction:{self.count}'
        key = None
        if self.reading is not None and type in (CitationType.STATUTE, CitationType.ACADEMIC) and fields.get('span'):
            block, _ = self.reading.locate(fields['span'][0])
            block_id = block.block_id if block is not None else fields.get('block_id')
            attributes = fields.get('attributes') or {}
            # _identity와 같은 키. 이 두 유형은 생성 뒤 키 필드가 바뀌지 않는다.
            key = (str(type), fields.get('canonical_case_number'), fields.get('law_name'), fields.get('article'),
                   fields.get('paragraph'), fields.get('item'), fields.get('doi'), (fields.get('title') or '').strip(),
                   attributes.get('rule_number'), block_id)
            prototype = self.prototypes.get(key)
            if prototype is not None:
                return _DuplicateCitation(prototype, identifier, raw_text, fields['span'], attributes)
        citation = _PendingCitation(identifier, type, raw_text, **fields)
        if key is not None:
            self.prototypes[key] = citation
        return citation

    def finish(self, citations):
        identifiers = {}
        def final_id(provisional):
            if provisional not in identifiers:
                identifiers[provisional] = new_id('CIT')
            return identifiers[provisional]
        for citation in citations:
            citation.citation_id = final_id(citation.citation_id)
            if 'continued_from' in citation.attributes:
                citation.attributes['continued_from'] = final_id(citation.attributes['continued_from'])
        return [Citation(**{field.name: getattr(citation, field.name) for field in _CITATION_FIELDS})
                for citation in citations]


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
    batch = _CitationBatch(reading)

    def select_body(citations):
        retained = []
        for citation in citations.originals():
            if citation.span:
                block, _ = reading.locate(citation.span[0])
                if block is not None:
                    citation.block_id, citation.page = block.block_id, block.page
            key = (_identity(citation), citation.block_id)
            if key not in seen:
                seen.add(key)
                retained.append(citation)
        return retained

    for citation in extract_from_text(reading.text, document_id=doc.document_id, _create=batch.create,
                                      _select=select_body, _collection=batch.body):
        block = None
        if citation.span:
            block, offset = reading.locate(citation.span[0])
            if block is not None:
                citation.block_id, citation.page = block.block_id, block.page
        if block is not None:
            citation.attributes["reading_span"] = list(citation.span)
            citation.span = (offset, offset + citation.span[1] - citation.span[0])
        out.append(citation)

    _attach_law_alias_candidates(reading.text, out)
    batch.reading = None

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
                                                  block_id=block.block_id, page=block.page, _create=batch.create):
                    key = (_identity(citation), block.block_id, r_index)
                    if key in seen:
                        continue
                    seen.add(key)
                    citation.attributes["table_cell"] = {"table_ref": (block.attributes or {}).get("table_ref"),
                                                         "row": r_index, "column": c_index}
                    out.append(citation)
    return batch.finish(out)


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
    if not statutes:
        return
    defined = {}
    for m in ALIAS_DEFINITION_RE.finditer(text):
        full, abbr = canonical_law_name(m.group("full")), m.group("abbr").strip()
        if abbr.endswith("법") and full.replace(" ", "") != abbr.replace(" ", ""):
            defined[abbr.replace(" ", "")] = full
    full_names = {c.law_name for c in statutes if " " in c.law_name}
    clean_full_names = sorted((f.replace(" ", ""), f) for f in full_names)
    clean_names = [clean for clean, _ in clean_full_names]
    prefix_candidates = {}
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
        if written not in prefix_candidates:
            lo = bisect.bisect_left(clean_names, stem)
            hi = bisect.bisect_left(clean_names, stem + chr(0x10ffff))
            count = hi - lo
            # 같은 적힌 이름은 후보에서 제외한다. 정렬 범위로 갯수만 판정한다.
            eq_lo = bisect.bisect_left(clean_names, written, lo, hi)
            eq_hi = bisect.bisect_right(clean_names, written, eq_lo, hi)
            count -= eq_hi - eq_lo
            at = lo if eq_lo != lo else eq_hi
            prefix_candidates[written] = clean_full_names[at][1] if count == 1 else None
        candidate = prefix_candidates[written]
        if candidate is not None:
            citation.attributes.update(law_alias_candidate=candidate, law_alias_basis="DOCUMENT_FULL_NAME_PREFIX")
