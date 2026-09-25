"""대한민국 주요 법률의 조문 상한(Max Article Number) 참고표와 조문 표기 형식 검사.

- 조문 상한은 정적 참고값이다. 공식 원문(국가법령정보센터) 조회를 대신하지 못하며, 개정·연혁을 증명하지 않으므로
  상한 초과만으로 부존재를 확정하지 않는다(verifier는 참고 메모로만 쓴다).
- 법률·시행령·시행규칙은 조문 번호 체계가 서로 독립이다. 법령명에서 법령 단계(LAW/DECREE/RULE)를 먼저 가르고,
  같은 단계의 참고표에서만 찾는다. 법률의 상한을 그 시행령·시행규칙에 적용하지 않는다.
- 가지번호(제N조의M)는 본조 N이 상한을 넘으면 그 가지조문도 있을 수 없다. N이 상한 이하이면 가지조문의 존재는
  원문으로만 확인한다(참고표로 판단하지 않음).
- 조문 표기 형식: 조·항·호 번호는 1부터 시작하므로 '제0조' 등은 성립할 수 없다. 가지번호는 조·호에만 쓰고
  항·목에는 쓰지 않는다(법제처 「법령 입안·심사 기준」). 항·목의 가지번호 표기는 형식 이상 후보로만 알린다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# 대한민국 주요 '법률'의 본칙 마지막 조문 번호 참고표(정적 값, 공식 원문과 대조하지 않았다 — 참고 메모 전용).
# 이 표는 법률 단계(LAW)에만 쓴다. 시행령·시행규칙 값은 공식 원문으로 확인한 것만 아래 표에 넣는다(현재 없음).
STATUTE_MAX_ARTICLES: Dict[str, int] = {
    # 기본 6법 및 헌법
    "대한민국헌법": 130,
    "헌법": 130,
    "민법": 1118,
    "형법": 372,
    "형사소송법": 493,
    "민사소송법": 502,
    "상법": 935,
    "행정소송법": 46,
    "행정기본법": 40,
    "행정심판법": 61,
    "행정절차법": 54,
    "민사집행법": 312,
    "가사소송법": 72,

    # 노동법 분야
    "근로기준법": 116,
    "노동조합및노동관계조정법": 96,
    "노동조합법": 96,
    "근로자퇴직급여보장법": 48,
    "근로자퇴직급여법": 48,
    "퇴직급여법": 48,
    "기간제및단시간근로자보호등에관한법률": 24,
    "기간제법": 24,
    "파견근로자보호등에관한법률": 46,
    "파견법": 46,
    "남녀고용평등과일ㆍ가정양립지원에관한법률": 39,
    "남녀고용평등법": 39,
    "산업안전보건법": 175,
    "산업재해보상보험법": 131,
    "산재보험법": 131,
    "최저임금법": 32,
    "근로복지기본법": 99,
    "노동위원회법": 31,

    # 공법 / 특별법 분야
    "국가배상법": 16,
    "국가를당사자로하는계약에관한법률": 35,
    "국가계약법": 35,
    "지방자치단체를당사자로하는계약에관한법률": 38,
    "지방계약법": 38,
    "공공기관의운영에관한법률": 54,
    "국가공무원법": 86,
    "지방공무원법": 83,
    "군인사법": 66,
    "군형법": 104,
    "군사법원법": 534,
    "소송촉진등에관한특례법": 38,
    "소송촉진법": 38,
    "제조물책임법": 10,
    "개인정보보호법": 76,
    "저작권법": 142,
    "특허법": 232,
    "상표법": 230,
    "부정경쟁방지및영업비밀보호에관한법률": 20,
    "부정경쟁방지법": 20,
    "독점규제및공정거래에관한법률": 130,
    "공정거래법": 130,
    "소비자기본법": 86,
    "약관의규제에관한법률": 34,
    "약관규제법": 34,
    "주택임대차보호법": 32,
    "상가건물임대차보호법": 22,
    "국유재산법": 84,
    "토지보상법": 99,
    "공익사업을위한토지등의취득및보상에관한법률": 99,
}

# 법령 단계별 참고표. 시행령·시행규칙은 모법과 조문 체계가 달라 법률 표를 빌려 쓰지 않는다.
DECREE_MAX_ARTICLES: Dict[str, int] = {}
RULE_MAX_ARTICLES: Dict[str, int] = {}
LEVEL_TABLES: Dict[str, Dict[str, int]] = {"LAW": STATUTE_MAX_ARTICLES, "DECREE": DECREE_MAX_ARTICLES,
                                           "RULE": RULE_MAX_ARTICLES}

_CLEAN_LAW_NAME_RE = re.compile(r"[\s\-_ㆍ·「」『』\[\]()]+")
_ARTICLE_NUM_RE = re.compile(r"제?\s*(\d+)(?:조(?:의\s*\d+)?)?")
_ARTICLE_PARTS_RE = re.compile(r"제?\s*(?P<main>\d+)\s*(?:조)?\s*(?:의\s*(?P<branch>\d+))?")
# 법령 단계 접미어: 시행규칙이 시행령보다 먼저(‘시행규칙’ 안에 ‘규칙’이 있으므로 긴 것부터)
_LEVEL_SUFFIXES: Tuple[Tuple[str, str], ...] = (("시행규칙", "RULE"), ("시행령", "DECREE"))


def normalize_statute_name(law_name: str) -> str:
    """법률명에서 공백 및 특수문자를 제거하여 정규화한다."""
    if not law_name:
        return ""
    return _CLEAN_LAW_NAME_RE.sub("", law_name)


def split_statute_name(law_name: str) -> Tuple[str, str]:
    """법령명 → (모법 이름, 단계). 단계는 LAW(법률)·DECREE(시행령)·RULE(시행규칙).

    '근로기준법 시행령' → ('근로기준법', 'DECREE'), '근로기준법시행규칙' → ('근로기준법', 'RULE').
    """
    norm = normalize_statute_name(law_name)
    for suffix, level in _LEVEL_SUFFIXES:
        if norm.endswith(suffix) and len(norm) > len(suffix):
            return norm[: -len(suffix)], level
    return norm, "LAW"


def get_statute_max_article(law_name: str) -> Optional[int]:
    """해당 법령의 본칙 최대 조문 번호(같은 단계의 참고표에서만). 알 수 없으면 None."""
    base, level = split_statute_name(law_name)
    if not base:
        return None
    table = LEVEL_TABLES.get(level) or {}
    # 모법 이름이 정확히 같을 때만 쓴다(부분 일치는 관련 법률·하위법령을 섞는다)
    for key, value in table.items():
        if normalize_statute_name(key) == base:
            return value
    return None


def parse_article(article_str: str | int | None) -> Tuple[Optional[int], Optional[int]]:
    """'제47조의2' → (47, 2), '116' → (116, None). 해석할 수 없으면 (None, None)."""
    if article_str is None:
        return None, None
    if isinstance(article_str, int):
        return article_str, None
    m = _ARTICLE_PARTS_RE.search(str(article_str))
    if not m:
        return None, None
    return int(m.group("main")), (int(m.group("branch")) if m.group("branch") else None)


def parse_article_number(article_str: str | int | None) -> Optional[int]:
    """조문 문자열(예: '제250조', '제47조의2', '116')에서 주 조문 번호(정수)를 추출한다."""
    if article_str is None:
        return None
    if isinstance(article_str, int):
        return article_str
    m = _ARTICLE_NUM_RE.search(str(article_str))
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def check_statute_article_range(law_name: str, article: Optional[str | int]) -> Optional[Dict[str, Any]]:
    """조문 번호가 같은 단계 참고표의 본칙 최대 조문 번호를 넘는지 검사한다(참고 메모용).

    넘으면 dict, 정상·알 수 없는 법령·가지조문 존재 여부 미정이면 None. 가지조문(제N조의M)은 본조 N이 상한을 넘을 때만
    '있을 수 없다'고 보고, N이 상한 이하이면 원문 확인 대상으로 남긴다.
    """
    if not law_name or article is None:
        return None
    art_num, branch = parse_article(article)
    if art_num is None:
        return None
    max_art = get_statute_max_article(law_name)
    if max_art is None or art_num <= max_art:
        return None
    _, level = split_statute_name(law_name)
    cited = f"제{art_num}조" + (f"의{branch}" if branch else "")
    return {
        "law_name": law_name,
        "statute_level": level,
        "cited_article": art_num,
        "cited_branch": branch,
        "max_article": max_art,
        "excess": art_num - max_art,
        "rule_id": "LAW.PROVISION_EXCEEDS_MAX",
        "defect_code": "LAW-NX",
        "message": f"'{law_name}' {cited}는 정적 참고표의 상한({max_art})을 초과합니다"
                   + ("(가지조문은 본조가 있어야 붙으므로 본조 번호로 판단)" if branch else "") + ". "
                   "참고표는 개정·연혁을 증명하지 않으므로 공식 원문 확인 전에는 부존재를 확정하지 않습니다."
    }


# --- 조문 표기 형식 ---------------------------------------------------------------------------------
# 법령명(…법·…령·…규칙) 뒤의 조문 표기. 항·목 뒤 가지번호와 0번 조·항·호를 본다.
_LAW_NAME = r"(?P<law>같은\s*법(?:\s*시행(?:령|규칙))?|동법|[가-힣A-Za-z0-9ㆍ·]{1,40}?(?:법률|법|령|규칙))"
PROVISION_RE = re.compile(
    _LAW_NAME + r"\s*제\s*(?P<article>\d+)\s*조(?:\s*의\s*(?P<article_branch>\d+))?"
    r"(?:\s*제\s*(?P<paragraph>\d+)\s*항(?:\s*의\s*(?P<paragraph_branch>\d+))?)?"
    r"(?:\s*제\s*(?P<item>\d+)\s*호(?:\s*의\s*(?P<item_branch>\d+))?)?"
    r"(?:\s*(?P<subitem>[가-하])\s*목(?:\s*의\s*(?P<subitem_branch>\d+))?)?")


def provision_form_violations(text: str) -> List[Dict[str, Any]]:
    """법령 조문 표기에서 성립할 수 없거나 입안 기준에 없는 형식을 찾는다.

    - 제0조·제0항·제0호, 가지번호 '의0'·'의1': 번호는 1부터, 가지번호는 2부터 붙는다 → 성립 불가(ZERO/BRANCH_ONE)
      ※ '의1'은 입안 기준 원문으로 확인하지 못해 형식 이상 후보(SUSPECT)로만 둔다.
    - 항·목의 가지번호(제3항의2, 가목의2): 입안 기준상 가지번호는 조·호에만 쓴다 → 형식 이상 후보(SUSPECT)
    """
    out: List[Dict[str, Any]] = []
    for m in PROVISION_RE.finditer(text or ""):
        problems: List[Tuple[str, str, str]] = []
        for field_name, label in (("article", "조"), ("paragraph", "항"), ("item", "호")):
            if m.group(field_name) is not None and int(m.group(field_name)) == 0:
                problems.append(("ZERO_NUMBER", "IMPOSSIBLE", f"제0{label}: 조·항·호 번호는 1부터 붙는다"))
        for field_name, label in (("article_branch", "조"), ("item_branch", "호")):
            value = m.group(field_name)
            if value is not None and int(value) == 0:
                problems.append(("BRANCH_ZERO", "IMPOSSIBLE", f"{label}의 가지번호 '의0'은 성립하지 않는다"))
            elif value is not None and int(value) == 1:
                problems.append(("BRANCH_ONE", "SUSPECT", f"{label}의 가지번호 '의1': 가지번호는 보통 '의2'부터 붙는다"))
        for field_name, label in (("paragraph_branch", "항"), ("subitem_branch", "목")):
            if m.group(field_name) is not None:
                problems.append(("BRANCH_ON_PARAGRAPH_OR_SUBITEM", "SUSPECT",
                                 f"{label}에 가지번호가 붙었다: 입안 기준상 가지번호는 조·호에만 쓴다"))
        for code, certainty, reason in problems:
            out.append({"raw": " ".join(m.group(0).split()), "law_name": m.group("law"), "code": code,
                        "certainty": certainty, "reason": reason, "span": (m.start(), m.end()),
                        "rule_id": f"LAW.PROVISION_FORM.{code}"})
    return out
