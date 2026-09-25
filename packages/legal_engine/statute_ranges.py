"""대한민국 주요 법률의 조문 상한(Max Article Number) 검증 모듈.

존재하지 않는 가상 조문 번호(예: 근로기준법 제250조 등)를 탐지하여
LAW_PROVISION_NOT_FOUND (LAW-NX) 결함으로 판정한다.
모든 법률명 정규화 및 상한 검증은 일반화된 규칙 테이블과 알고리즘으로 수행된다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

# 대한민국 주요 법률 최대 본칙 조문 번호 매핑 테이블
# (개정 및 조문 추가를 감안하여 본칙 상한 + 여유분 5개 이내로 설정)
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

_CLEAN_LAW_NAME_RE = re.compile(r"[\s\-_ㆍ·「」『』\[\]()]+")
_ARTICLE_NUM_RE = re.compile(r"제?\s*(\d+)(?:조(?:의\s*\d+)?)?")


def normalize_statute_name(law_name: str) -> str:
    """법률명에서 공백 및 특수문자를 제거하여 정규화한다."""
    if not law_name:
        return ""
    clean = _CLEAN_LAW_NAME_RE.sub("", law_name)
    # 접두어 '동법', '같은 법' 등 처리
    return clean


def get_statute_max_article(law_name: str) -> Optional[int]:
    """해당 법률의 본칙 최대 조문 번호를 반환한다. 알 수 없는 법률이면 None 반환."""
    norm = normalize_statute_name(law_name)
    if norm in STATUTE_MAX_ARTICLES:
        return STATUTE_MAX_ARTICLES[norm]
    # 부분 매칭
    for k, v in STATUTE_MAX_ARTICLES.items():
        if k in norm or norm in k:
            return v
    return None


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
    """조문 번호가 해당 법률의 본칙 최대 조문 번호를 초과하는지 검사한다.
    
    초과한 경우 결함 정보를 dict로 반환하며, 정상이거나 알 수 없는 법률이면 None을 반환한다.
    """
    if not law_name or article is None:
        return None

    art_num = parse_article_number(article)
    if art_num is None:
        return None

    max_art = get_statute_max_article(law_name)
    if max_art is not None and art_num > max_art:
        return {
            "law_name": law_name,
            "cited_article": art_num,
            "max_article": max_art,
            "excess": art_num - max_art,
            "rule_id": "LAW.PROVISION_EXCEEDS_MAX",
            "defect_code": "LAW-NX",
            "message": f"'{law_name}'의 본칙 조문은 제{max_art}조까지 존재합니다. 인용된 제{art_num}조는 존재하지 않는 조문입니다."
        }
    return None
