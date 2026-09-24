"""비식별(익명) 표기 허용 목록.

판결문·서면은 개인정보를 ○○○, 김○○, △△사단, 010-0000-0000처럼 가린다. 이것은 작성자가 채워야 할
빈칸이 아니라 의도한 비식별 처리이므로 '미기재 자리표시'나 '예시 번호'로 보지 않는다(v2 Phase 1).
반대로 "[원고 주소 입력]", "[날짜]"처럼 각괄호 안에 채울 항목을 적은 것은 미완성 자리표시다.
"""
from __future__ import annotations

import re

MASK_CHARS = "○◯△▲□■◇◆☆＊*"
# 가림 기호 한 글자 이상(이름·기관명 일부를 가린 경우 포함)
MASK_RUN_RE = re.compile(f"[{re.escape(MASK_CHARS)}]+")
# 채울 항목을 적은 각괄호 자리표시
BRACKET_PLACEHOLDER_RE = re.compile(
    r"\[[^\]\n]{0,20}(입력|기재|날짜|이름|성명|주소|서명|금액|일자|연락처|전화|번호|사건번호|기관명)[^\]\n]{0,10}\]")


def is_masked_digits(digits: str) -> bool:
    """전부 0이거나 가림 기호인 번호(010-0000-0000 등)는 비식별 처리다."""
    body = re.sub(r"[\s\-–]", "", digits or "")
    return bool(body) and all(ch == "0" or ch in MASK_CHARS for ch in body)
