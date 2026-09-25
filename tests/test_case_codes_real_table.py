"""실제 공식 재판예규 별표 사건부호표(config/legal_rules/case_codes.yaml) 기반 법원-부호 호환성 검증 테스트.

검증 대상:
1. 대법원 + 항소부호 (나·노·누) 불일치 탐지
2. 대법원 + 1심부호 (가합·가단·고합·고단·구합) 불일치 탐지
3. 헌법재판소 + 법원부호 (다·고단 등) 불일치 탐지
4. 법원 + 헌재부호 (대법원 + 헌바 등) 불일치 탐지
5. 1998년 이전 대법원 '누' 부호 허용 예외 (예: 94누4615) 검증
"""
from __future__ import annotations

import datetime
from packages.common.enums import CitationType
from packages.legal_engine.citation_extractor import extract_from_text
from packages.legal_engine.citation_format import format_violations, case_code_table


def _get_violations(text: str, test_date: datetime.date = datetime.date(2026, 9, 25)) -> dict:
    """텍스트에서 인용을 추출하여 서지 형식 위반 규칙 목록을 딕셔너리로 반환한다."""
    citations = [c for c in extract_from_text(text) if c.type in (CitationType.CASE, CitationType.CONSTITUTIONAL)]
    assert len(citations) >= 1, f"인용 추출 실패: {text}"
    violations = format_violations(citations[0], today=test_date)
    return {v["rule_id"]: v for v in violations}


def test_real_table_loaded():
    """case_codes.yaml에 민사·형사·행정 기본 사건부호가 등재되어 있는지 확인."""
    table = case_code_table()
    codes = table.get("codes", {})
    assert "가합" in codes, "민사1심 가합 누락"
    assert "나" in codes, "민사항소 나 누락"
    assert "다" in codes, "민사상고 다 누락"
    assert "고합" in codes, "형사1심 고합 누락"
    assert "노" in codes, "형사항소 노 누락"
    assert "도" in codes, "형사상고 도 누락"
    assert "구합" in codes, "행정1심 구합 누락"
    assert "누" in codes, "행사항소 누 누락"
    assert "두" in codes, "행사상고 두 누락"


def test_supreme_court_with_appellate_codes():
    """대법원 + 항소심 부호(나, 노, 1998년 이후 누) 불일치 검증."""
    # 민사항소(나)
    v_na = _get_violations("대법원 2021. 5. 13. 선고 2020나12345 판결")
    assert "FMT.COURT_CODE_MISMATCH" in v_na
    assert v_na["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "하급법원"

    # 형사항소(노)
    v_no = _get_violations("대법원 2021. 6. 10. 선고 2020노1234 판결")
    assert "FMT.COURT_CODE_MISMATCH" in v_no
    assert v_no["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "하급법원"

    # 행사항소(누) - 1998년 이후 접수 사건은 대법원 부호로 사용 불가
    v_nu = _get_violations("대법원 2021. 7. 8. 선고 2020누1234 판결")
    assert ("FMT.CODE_OUT_OF_PERIOD" in v_nu) or ("FMT.COURT_CODE_MISMATCH" in v_nu)


def test_supreme_court_with_first_instance_codes():
    """대법원 + 1심 부호(가합, 가단, 고합, 고단, 구합) 불일치 검증."""
    # 민사합의 1심(가합)
    v_gahap = _get_violations("대법원 2020. 3. 12. 선고 2019가합51234 판결")
    assert "FMT.COURT_CODE_MISMATCH" in v_gahap
    assert v_gahap["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "하급법원"

    # 민사단독 1심(가단)
    v_gadan = _get_violations("대법원 2020. 3. 12. 선고 2019가단51234 판결")
    assert "FMT.COURT_CODE_MISMATCH" in v_gadan
    assert v_gadan["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "하급법원"

    # 형사합의 1심(고합)
    v_gohap = _get_violations("대법원 2020. 4. 15. 선고 2019고합1234 판결")
    assert "FMT.COURT_CODE_MISMATCH" in v_gohap
    assert v_gohap["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "하급법원"

    # 형사단독 1심(고단)
    v_godan = _get_violations("대법원 2020. 4. 15. 선고 2019고단1234 판결")
    assert "FMT.COURT_CODE_MISMATCH" in v_godan
    assert v_godan["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "하급법원"

    # 행정합의 1심(구합)
    v_guhap = _get_violations("대법원 2020. 5. 20. 선고 2019구합51234 판결")
    assert "FMT.COURT_CODE_MISMATCH" in v_guhap
    assert v_guhap["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "하급법원"


def test_constitutional_court_with_ordinary_court_codes():
    """헌법재판소 + 일반 법원 부호(다, 고단, 나 등) 불일치 검증."""
    # 헌재 + 대법원 상고부호(다)
    v_da = _get_violations("헌법재판소 2021. 3. 25. 2020다12345 결정")
    assert "FMT.COURT_CODE_MISMATCH" in v_da

    # 헌재 + 하급심 부호(고단)
    v_godan = _get_violations("헌법재판소 2021. 4. 22. 2020고단1234 결정")
    assert "FMT.COURT_CODE_MISMATCH" in v_godan


def test_ordinary_court_with_constitutional_court_codes():
    """일반 법원 + 헌법재판소 부호(헌바, 헌마 등) 불일치 검증."""
    v_court_const = _get_violations("대법원 2020. 6. 18. 선고 2019헌바123 판결")
    assert "FMT.COURT_CODE_MISMATCH" in v_court_const
    assert v_court_const["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "헌법재판소"


def test_historical_supreme_court_nu_code_allowed():
    """1998년 이전 대법원 '누' 사건부호는 역사적 정당 인용으로 허용(예외 정상 통과)."""
    # 94누4615 (1995년 선고) -> 불일치 위반이 없어야 함
    v_historical = _get_violations("대법원 1995. 7. 11. 선고 94누4615 전원합의체 판결")
    assert "FMT.COURT_CODE_MISMATCH" not in v_historical
    assert "FMT.CODE_OUT_OF_PERIOD" not in v_historical
