"""제9.3장 사건번호 Normalization.

"2023 도 12345", "2023도 12345", "2023도12345"를 동일 canonical value로 정규화한다.
"""
from __future__ import annotations

import re
from typing import Optional

CASE_NUMBER_RE = re.compile(r"(?P<year>(?:19|20)\d{2})\s*(?P<code>[가-힣]{1,3})\s*(?P<serial>\d{1,6})")
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


def split_case_number(raw: str):
    m = CONSTITUTIONAL_RE.search(raw or "") or CASE_NUMBER_RE.search(raw or "")
    if not m:
        return None
    return m.group("year"), m.group("code"), str(int(m.group("serial")))


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


# 법령명 앞 토큰이 조사로 끝나면 법령명이 아니다(예: "적용법조는 테스트법" -> "테스트법").
JOSA_TAILS = set("는은이가을를의에로과와도만며고서")


def canonical_law_name(raw: str) -> str:
    """법령명 앞에 붙은 접속어·조사 토큰을 제거해 표준 법령명을 만든다."""
    name = re.sub(r"[「」『』]", "", raw or "").strip()
    changed = True
    while changed:
        changed = False
        tokens = name.split()
        # 1) 앞 토큰이 조사로 끝나면 법령명이 아니다
        if len(tokens) > 1 and tokens[0] and tokens[0][-1] in JOSA_TAILS:
            name = " ".join(tokens[1:])
            changed = True
            continue
        # 2) 알려진 접속·부사어 접두 제거
        for noise in LAW_NAME_PREFIX_NOISE:
            if tokens and tokens[0] == noise and len(tokens) > 1:
                name = " ".join(tokens[1:])
                changed = True
                break
            if not tokens and name.startswith(noise):
                break
            if name.startswith(noise) and len(name) > len(noise) + 1 and " " not in name:
                name = name[len(noise) :].strip()
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
