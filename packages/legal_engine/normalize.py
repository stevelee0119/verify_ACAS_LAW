"""제9.3장 사건번호 Normalization.

"2023 도 12345", "2023도 12345", "2023도12345"를 동일 canonical value로 정규화한다.
"""
from __future__ import annotations

import re
from typing import Optional

# 1999년까지의 사건번호는 연도를 두 자리로 적는다(예: 94누4615). 네 자리 연도와 함께 받는다.
CASE_NUMBER_RE = re.compile(r"(?<!\d)(?P<year>(?:19|20)\d{2}|\d{2})\s*(?P<code>[가-힣]{1,3})\s*(?P<serial>\d{1,6})")
CONSTITUTIONAL_RE = re.compile(r"(?P<year>(?:19|20)\d{2})\s*(?P<code>헌[가-힣]{1,2})\s*(?P<serial>\d{1,4})")

# 대표 사건부호 (대법원 재판예규 기준 주요 항목)
CASE_CODE_MEANING = {
    "가단": "민사 1심 단독", "가합": "민사 1심 합의", "가소": "소액", "나": "민사 항소",
    "다": "민사 상고", "라": "민사 항고", "마": "민사 재항고",
    "고단": "형사 1심 단독", "고합": "형사 1심 합의", "고정": "형사 약식정식재판",
    "노": "형사 항소", "도": "형사 상고", "초": "형사 신청", "모": "형사 재항고",
    "구단": "행정 1심 단독", "구합": "행정 1심 합의", "누": "행정 항소", "두": "행정 상고",
    "드단": "가사 단독", "드합": "가사 합의", "르": "가사 항소", "므": "가사 상고",
    "허": "특허 1심", "후": "특허 상고",
    "헌가": "위헌법률심판", "헌나": "탄핵심판", "헌다": "정당해산심판",
    "헌라": "권한쟁의심판", "헌마": "헌법소원(권리구제형)", "헌바": "헌법소원(위헌심사형)",
}

SUPREME_COURT_CODES = {"도", "다", "두", "무", "므", "후", "마", "재도", "재다"}


def canonical_case_number(raw: str) -> Optional[str]:
    """공백을 제거한 canonical 형태를 만든다."""
    if not raw:
        return None
    text = raw.strip()
    m = CONSTITUTIONAL_RE.search(text) or CASE_NUMBER_RE.search(text)
    if not m:
        return None
    return f"{m.group('year')}{m.group('code')}{int(m.group('serial'))}"


def extract_all_case_numbers(text: str):
    """문자열에 포함된 모든 사건번호를 (연도, 부호, 일련번호) 튜플 목록으로 추출한다.

    병합 판결(예: '2005가합100279, 2006가합62053')이나 복수 인용을 포괄한다.
    """
    if not text:
        return []
    results = []
    for m in CONSTITUTIONAL_RE.finditer(text):
        results.append((m.group("year"), m.group("code"), str(int(m.group("serial")))))
    for m in CASE_NUMBER_RE.finditer(text):
        item = (m.group("year"), m.group("code"), str(int(m.group("serial"))))
        if item not in results:
            results.append(item)
    return results


def same_case_number(a: str, b: str) -> bool:
    """두 사건번호가 같은 사건을 가리키는지 판정한다.

    공식 Source는 "서울행정법원-2021-구합-70769"처럼 법원명과 구분자를 붙여 돌려주기도 하고,
    병합 판결의 경우 "2005가합100279, 2006가합62053"처럼 여러 사건번호가 함께 수록된다.
    어느 한쪽에 병합 사건번호가 포함된 경우에도 정확한 (연도, 부호, 일련번호) 단위의 교집합이 있으면
    동일 사건으로 인정한다. 부분 숫자만 같은 다른 사건의 오연결은 철저히 방지한다.
    """
    left_cases = extract_all_case_numbers(a or "")
    right_cases = extract_all_case_numbers(b or "")
    if not left_cases or not right_cases:
        return False
    return bool(set(left_cases) & set(right_cases))


def split_case_number(raw: str):
    m = CONSTITUTIONAL_RE.search(raw or "") or CASE_NUMBER_RE.search(raw or "")
    if not m:
        return None
    return m.group("year"), m.group("code"), str(int(m.group("serial")))


def case_number_possible(raw: str) -> bool:
    """그 사건번호가 실재할 수 있는 형태인지 본다.

    공식 DB에서 확인하지 못한 것과, 애초에 성립할 수 없는 표기는 전혀 다르다.
    국가법령정보 판례 DB는 모든 재판을 수록하지 않으므로 미확인은 미확인일 뿐이다.
    실재하는 판례를 "가공"이라 적으면 그 서면을 쓴 변호사에게 실제 손해가 간다.

    아직 오지 않은 해의 사건번호이거나 재판예규에 없는 사건부호이면 그 표기로는
    사건이 존재할 수 없다. 그때만 False를 돌려준다.
    """
    from datetime import date

    parts = split_case_number(raw or "")
    if parts is None:
        return True  # 사건번호를 읽지 못한 것은 성립 불가의 근거가 아니다
    year, code, _ = parts
    if int(year) > date.today().year:
        return False
    return bool(case_code_meaning(code)) or code.startswith("헌")


def case_code_meaning(code: str) -> Optional[str]:
    return CASE_CODE_MEANING.get(code)


def is_supreme_court_code(code: str) -> bool:
    return code in SUPREME_COURT_CODES


# ---------------------------------------------------------------------------
# 날짜 정규화
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    re.compile(r"(?P<y>(?:19|20)\d{2})\s*[.\-년]\s*(?P<m>\d{1,2})\s*[.\-월]\s*(?P<d>\d{1,2})\s*[.일]?"),
    re.compile(r"(?P<y>(?:19|20)\d{2})(?P<m>\d{2})(?P<d>\d{2})"),
]


def canonical_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    for pattern in DATE_PATTERNS:
        m = pattern.search(raw)
        if m:
            try:
                y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            except (ValueError, IndexError):
                continue
    return None


# ---------------------------------------------------------------------------
# 법령명 정규화
# ---------------------------------------------------------------------------
LAW_ALIASES = {
    "형소법": "형사소송법",
    "민소법": "민사소송법",
    "행소법": "행정소송법",
    "국배법": "국가배상법",
    "군형법": "군형법",
    "정통망법": "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
    "개인정보법": "개인정보 보호법",
    "부경법": "부정경쟁방지 및 영업비밀보호에 관한 법률",
    "근기법": "근로기준법",
    # 공식 제명은 '대한민국헌법'(https://www.law.go.kr/법령/대한민국헌법). 서면은 흔히 '헌법'으로 쓴다.
    "헌법": "대한민국헌법",
    # 국가법령정보센터가 표시하는 공식 약칭. 법령명 검색(lawSearch.do, section=lawNm)은 약칭으로 찾지 못한다
    # (0.9.8 실제 실행: '국가계약법' 조회 결과 0건).
    "국가계약법": "국가를 당사자로 하는 계약에 관한 법률",
    "지방계약법": "지방자치단체를 당사자로 하는 계약에 관한 법률",
    "공정거래법": "독점규제 및 공정거래에 관한 법률",
    "성폭력처벌법": "성폭력범죄의 처벌 등에 관한 특례법",
    "특정범죄가중법": "특정범죄 가중처벌 등에 관한 법률",
    "정보통신망법": "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
    "학교폭력예방법": "학교폭력예방 및 대책에 관한 법률",
    # 혁신의료기기지원법 공식 제명 및 약칭
    "혁신의료기기법": "의료기기산업 육성 및 혁신의료기기 지원법",
    "혁신의료기기지원법": "의료기기산업 육성 및 혁신의료기기 지원법",
    "의료기기산업법": "의료기기산업 육성 및 혁신의료기기 지원법",
    "의료기기산업육성및혁신의료기기지원법": "의료기기산업 육성 및 혁신의료기기 지원법",
}


# 법령명 앞에 붙어 나오기 쉬운 접속·부사어. 정규식이 함께 잡아도 법령명에서 제외한다.
LAW_NAME_PREFIX_NOISE = [
    "또한", "그리고", "및", "한편", "따라서", "이에", "아울러", "특히", "나아가",
    "위", "본", "동", "구", "현행", "당시", "관련", "해당", "각", "위반한", "위반하여",
    "이상",  # "…위험이 배제된 이상 군사기밀보호법 제10조"
]


# 공백 없이 법령명에 붙어도 떼어 낼 수 있는 접속·부사어. 한 글자 접두("위", "구", "동")는
# 법령명 첫 글자와 구별되지 않으므로(예: 위치정보법, 구강보건법, 동물보호법) 띄어 쓴 경우에만 뗀다.
_GLUED_NOISE = {"또한", "그리고", "한편", "따라서", "아울러", "특히", "나아가"}

# 기본 주요 법전 (약칭 매핑과 별도로 단독 법령명으로 최우선 인식)
CORE_LEGAL_CODES = {"민법", "형법", "상법", "헌법", "대한민국헌법", "민사소송법", "형사소송법", "행정소송법", "국가배상법", "근로기준법"}

# 법령명 앞 토큰이 조사로 끝나면 법령명이 아니다(예: "적용법조는 테스트법" -> "테스트법").
JOSA_TAILS = set("는은이가을를의에로과와도만며고서")


ARTICLE_RE = re.compile(r"(?P<no>\d+)\s*(?:조)?\s*(?:의\s*(?P<sub>\d+))?")


def canonical_article(raw: str) -> str:
    """'390의2', '제390조의2', '390-2'를 같은 표기로 만든다."""
    text = re.sub(r"[\s제조]", "", str(raw or "")).replace("-", "의")
    m = ARTICLE_RE.search(text)
    if not m:
        return text
    base = str(int(m.group("no")))
    return f"{base}의{int(m.group('sub'))}" if m.group("sub") else base


# 법령명 안에서 앞말을 뒤 토큰에 잇는 말. "…에 관한 법률", "…의 처벌 등에 관한 특례법", "…를 당사자로 하는 계약에 관한 법률"
LAW_NAME_LINKS = {"관한", "대한", "위한", "따른", "의한", "관하는", "및", "등", "또는", "하는", "당사자로"}
# 법령명 안 토큰이 이 글자로 끝나면 뒤 토큰에 이어진다(공공기관의 / 정보공개에 / 자본시장과).
LAW_NAME_JOINING_TAILS = set("의에과와")
# 이 글자로 끝나는 토큰은 문장 성분(주어·목적어·부사어·어미)이다. 법령명은 여기서 끊는다.
SENTENCE_TAILS = set("는은이가을를로서도만며고다면게해여니나요까야든데지써바")
# 관형형 어미 '-한'으로 끝나는 서술어("기망한", "위반한"). 법령명 안의 '관한·대한·위한'은 LAW_NAME_LINKS가 먼저 받는다.
# '-된·-던'으로 끝나는 관형형("배제된", "개정된")도 법령명 앞에서 끊는다. 공식 법령명 토큰은 이 어미로 끝나지 않는다.
PREDICATE_TAIL_RE = re.compile(r"[가-힣]{2,}한$|[가-힣]+(?:된|던)$")
# 띄어쓰기 없이 서술어에 붙은 법령명: "기망한형법", "제출함으로써민법". 서술어 부분이 법령명 연결어로 끝나면
# (…에관한법률, 대한민국헌법) 나누지 않는다.
GLUED_PREDICATE_RE = re.compile(r"^(?P<pre>[가-힣]{2,}?(?:한|써))(?P<law>[가-힣]{1,20}(?:법률|법|령|규칙))$")


def law_name_suffix(raw: str) -> str:
    """정규식이 법령명 앞 문장까지 함께 잡았을 때, 끝에서부터 법령명이 될 수 있는 토큰만 남긴다.

    "에게 폭언을 하였다는 이유로 군인사법" → "군인사법",
    "원고는 공공기관의 정보공개에 관한 법률" → "공공기관의 정보공개에 관한 법률",
    "원고는 국가를 당사자로 하는 계약에 관한 법률" → "국가를 당사자로 하는 계약에 관한 법률".
    """
    bracketed = re.search(r"[「『]([^」』]+)[」』]?\s*$", raw or "")
    if bracketed and bracketed.group(1).strip():
        # 낫표는 법령명의 경계를 표시한다. 안쪽 전체가 법령명이다(「…예방 및 대책에 관한 법률」).
        return " ".join(bracketed.group(1).split())

    # 공식 제명 목록(LAW_ALIASES의 공식 명칭 및 주요 법전)이 raw 내에 완전 포함된 경우 최장 일치를 우선 보존한다
    clean_raw = re.sub(r"[「」『』]", " ", raw or "")
    matches = []
    targets = set(LAW_ALIASES.values()) | set(LAW_ALIASES.keys()) | CORE_LEGAL_CODES
    for official in targets:
        # 단어 시작 경계(공백 또는 문장 시작)에서 일치하는 법령명 탐색
        pattern = re.compile(r"(?<![가-힣])" + re.escape(official).replace(r"\ ", r"\s*")
                             + r"(?:\s*시행(?:령|규칙))?(?=$|[^가-힣]|(?:을|를|에|의|은|는)(?:\s|$))")
        for match in pattern.finditer(clean_raw):
            # A later, unlisted law must not be replaced by an earlier known one.
            tail = clean_raw[match.end():]
            if not re.search(r"(?:법률|법|령|규칙|조례|훈령|예규|규정|고시|지침)(?=$|[^가-힣]|[을를에의은는](?:\s|$))", tail):
                matches.append(match)
    if matches:
        # The rightmost complete title wins; preserve a subordinate decree/rule.
        match = max(matches, key=lambda m: (m.end(), len(m.group())))
        resolved = " ".join(match.group().split())
        compact = resolved.replace(" ", "")
        if compact in LAW_ALIASES:
            return LAW_ALIASES[compact]
        return resolved

    tokens = clean_raw.split()
    if not tokens:
        return ""
    kept = [tokens[-1]]
    remaining = tokens[:-1]
    for index in range(len(remaining) - 1, -1, -1):
        token = remaining[index]
        if token in LAW_NAME_ENUMERATORS and kept and index > 0 and _continues_name(remaining[index - 1]):
            # '및'·'또는' 앞 토큰이 법령명으로 끝나지 않고 조사도 붙지 않은 명사면, 법령명 안의 접속어다
            # (학교폭력예방 및 대책에 관한 법률). 앞 토큰이 법령명이면 두 법령을 나열한 것이다(형법 및 민법).
            kept.insert(0, token)
            continue
        if token in LAW_NAME_PREFIX_NOISE:
            break
        # '…를 당사자로 하는' 연결 구문 특수 보존
        if token == "당사자로" and kept and kept[0] == "하는":
            kept.insert(0, token)
            continue
        if token.endswith(("를", "을")) and index < len(remaining) - 1 and remaining[index + 1] == "당사자로":
            kept.insert(0, token)
            continue
        if token in LAW_NAME_LINKS or token[-1] in LAW_NAME_JOINING_TAILS:
            kept.insert(0, token)
            continue
        if token[-1] in SENTENCE_TAILS or not re.fullmatch(r"[가-힣A-Za-z·]{2,}", token) \
                or PREDICATE_TAIL_RE.search(token):
            break
        kept.insert(0, token)  # 조사가 붙지 않은 명사(개인정보 보호법의 '개인정보', 처벌 등에 관한의 '처벌')
    while kept and (kept[0] in LAW_NAME_LINKS or kept[0][-1] in LAW_NAME_JOINING_TAILS) and len(kept) > 1 \
            and not _joins_forward(kept):
        kept.pop(0)
    glued = GLUED_PREDICATE_RE.match(kept[0]) if len(kept) == 1 else None
    if glued and not any(glued.group("pre").endswith(link) for link in LAW_NAME_LINKS) \
            and " ".join(kept) not in LAW_ALIASES:
        kept = [glued.group("law")]
    return " ".join(kept)


# 기본 주요 법전 (약칭 매핑과 별도로 단독 법령명으로 최우선 인식)
CORE_LEGAL_CODES = {"민법", "형법", "상법", "헌법", "대한민국헌법", "민사소송법", "형사소송법", "행정소송법", "국가배상법", "근로기준법"}

LAW_NAME_ENUMERATORS = {"및", "또는"}
LAW_KIND_TAIL_RE = re.compile(r"(?:법|법률|령|규칙|조례)$")
# 일반 법률 행위·위반 명사는 법령명 내부 연결어('및') 앞 토큰이 될 수 없다 (오탐 방지)
NON_STATUTE_NOUNS = {
    "채무불이행", "불법행위", "손해배상", "침해행위", "위반행위", "이행지체", "부당이득",
    "사기", "배임", "횡령", "과실", "고의", "하자", "의무위반", "계약위반"
}


def _continues_name(token: str) -> bool:
    """'및' 앞 토큰이 법령명의 일부(조사 없는 고유 명사)인지 판별한다.

    '학교폭력예방 및 대책에 관한 법률'의 '학교폭력예방'은 True이지만,
    '채무불이행 및 민법 제750조'의 '채무불이행'은 법률행위 명사이므로 False이다.
    """
    clean = re.sub(r"^[의에을를은는이가와과]+", "", token).strip()
    if clean in NON_STATUTE_NOUNS or token.startswith("의"):
        return False
    return (bool(re.fullmatch(r"[가-힣A-Za-z·]{2,}", token)) and not LAW_KIND_TAIL_RE.search(token)
            and token[-1] not in SENTENCE_TAILS and token[-1] not in JOSA_TAILS
            and token not in LAW_NAME_PREFIX_NOISE)



def _joins_forward(tokens) -> bool:
    """맨 앞 토큰이 뒤와 법령명 안에서 이어지는지(…의 …에 관한 …) 본다."""
    return any(t in LAW_NAME_LINKS for t in tokens[1:])


def canonical_law_name(raw: str) -> str:
    """법령명 앞에 붙은 문장 조각·접속어를 떼고 표준 법령명을 만든다."""
    name = law_name_suffix(raw) or re.sub(r"[「」『』]", "", raw or "").strip()
    changed = True
    while changed:
        changed = False
        tokens = name.split()
        for noise in LAW_NAME_PREFIX_NOISE:
            if tokens and tokens[0] == noise and len(tokens) > 1:
                name = " ".join(tokens[1:])
                changed = True
                break
            if name.startswith(noise) and len(name) > len(noise) + 1 and " " not in name \
                    and noise in _GLUED_NOISE:
                name = name[len(noise):].strip()
                changed = True
                break
    name = re.sub(r"\s+", " ", name).strip()
    compact = name.replace(" ", "")
    if compact in LAW_ALIASES:
        return LAW_ALIASES[compact]
    # 공백 없는 짧은 법령명은 압축형을 표준으로 본다 (예: "형사 소송법" -> "형사소송법")
    if len(compact) <= 10:
        return compact
    return name
