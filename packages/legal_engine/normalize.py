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


def same_case_number(a: str, b: str) -> bool:
    """두 사건번호가 같은 사건을 가리키는지 판정한다.

    공식 Source는 "서울행정법원-2021-구합-70769"처럼 법원명과 구분자를 붙여 돌려주기도 한다.
    연도·사건부호·일련번호 세 요소가 모두 같을 때만 같은 사건으로 본다.
    부분 일치(예: 2023다284910 vs 2024도12341)를 같은 사건으로 보면
    존재하지 않는 판례가 "확인됨"으로 둔갑한다.
    """
    left, right = split_case_number(a or ""), split_case_number(b or "")
    if left is None or right is None:
        return False
    return left == right


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
}


# 법령명 앞에 붙어 나오기 쉬운 접속·부사어. 정규식이 함께 잡아도 법령명에서 제외한다.
LAW_NAME_PREFIX_NOISE = [
    "또한", "그리고", "및", "한편", "따라서", "이에", "아울러", "특히", "나아가",
    "위", "본", "동", "구", "현행", "당시", "관련", "해당", "각", "위반한", "위반하여",
]


# 공백 없이 법령명에 붙어도 떼어 낼 수 있는 접속·부사어. 한 글자 접두("위", "구", "동")는
# 법령명 첫 글자와 구별되지 않으므로(예: 위치정보법, 구강보건법, 동물보호법) 띄어 쓴 경우에만 뗀다.
_GLUED_NOISE = {"또한", "그리고", "한편", "따라서", "아울러", "특히", "나아가"}

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


# 법령명 안에서 앞말을 뒤 토큰에 잇는 말. "…에 관한 법률", "…의 처벌 등에 관한 특례법"
LAW_NAME_LINKS = {"관한", "대한", "위한", "따른", "의한", "관하는", "및", "등", "또는"}
# 법령명 안 토큰이 이 글자로 끝나면 뒤 토큰에 이어진다(공공기관의 / 정보공개에 / 자본시장과).
LAW_NAME_JOINING_TAILS = set("의에과와")
# 이 글자로 끝나는 토큰은 문장 성분(주어·목적어·부사어·어미)이다. 법령명은 여기서 끊는다.
SENTENCE_TAILS = set("는은이가을를로서도만며고다면게해여니나요까야든데지")


def law_name_suffix(raw: str) -> str:
    """정규식이 법령명 앞 문장까지 함께 잡았을 때, 끝에서부터 법령명이 될 수 있는 토큰만 남긴다.

    "에게 폭언을 하였다는 이유로 군인사법" → "군인사법",
    "원고는 공공기관의 정보공개에 관한 법률" → "공공기관의 정보공개에 관한 법률".
    """
    tokens = re.sub(r"[「」『』]", " ", raw or "").split()
    if not tokens:
        return ""
    kept = [tokens[-1]]
    for token in reversed(tokens[:-1]):
        if token in LAW_NAME_PREFIX_NOISE:
            break
        if token in LAW_NAME_LINKS or token[-1] in LAW_NAME_JOINING_TAILS:
            kept.insert(0, token)
            continue
        if token[-1] in SENTENCE_TAILS or not re.fullmatch(r"[가-힣A-Za-z·]{2,}", token):
            break
        kept.insert(0, token)  # 조사가 붙지 않은 명사(개인정보 보호법의 '개인정보', 처벌 등에 관한의 '처벌')
    while kept and (kept[0] in LAW_NAME_LINKS or kept[0][-1] in LAW_NAME_JOINING_TAILS) and len(kept) > 1 \
            and not _joins_forward(kept):
        kept.pop(0)
    return " ".join(kept)


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
