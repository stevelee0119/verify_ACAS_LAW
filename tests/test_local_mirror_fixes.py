"""TK-10 로컬 법령 미러 개선 단위 테스트.

- 가지조문(조의N) 및 항(제N항) 파싱 보존 검증 (양성 3건 이상)
- 시행일 정밀 파싱 및 임의 날짜 배제 검증 (양성 3건 이상)
- 판례 URL 및 헌재 결정례 URL 배제 검증 (대조군 3건 이상)
- 조문 번호 표기 정규화 검색 검증
"""
import pytest
from packages.source_adapters.local_mirror import (
    LocalLegalMirror,
    _canon_article,
    _extract_effective_date,
    _is_official_law_url,
    _LAW_KEY_PATTERN,
)


# ==============================================================================
# 1. 양성 테스트: 가지조문 및 항 추출 (3건 이상)
# ==============================================================================
@pytest.mark.parametrize(
    "raw_key, expected_law, expected_art, expected_para",
    [
        ("군인사법 제51조의2", "군인사법", "51의2", None),
        ("군인사법 제59조의2", "군인사법", "59의2", None),
        ("정보통신망법 제44조의7", "정보통신망법", "44의7", None),
        ("개인정보 보호법 제39조의3", "개인정보 보호법", "39의3", None),
        ("헌법 제13조 제2항", "헌법", "13", "2"),
        ("민법 제398조 제2항", "민법", "398", "2"),
        ("대한민국헌법 제37조 제2항", "대한민국헌법", "37", "2"),
    ],
)
def test_law_key_pattern_parsing(raw_key, expected_law, expected_art, expected_para):
    """법령 조문 키에서 법령명, 가지조문, 항을 정확히 분리 추출하는지 검증한다."""
    m = _LAW_KEY_PATTERN.match(raw_key)
    assert m is not None, f"패턴 매칭 실패: {raw_key}"
    law = m.group("law").strip()
    art = m.group("art")
    sub = m.group("art_sub")
    para = m.group("para")
    article = f"{art}의{sub}" if sub else art

    assert law == expected_law
    assert article == expected_art
    assert para == expected_para


# ==============================================================================
# 2. 양성 테스트: 시행일 파싱 및 임의 날짜 배제 (3건 이상)
# ==============================================================================
@pytest.mark.parametrize(
    "version_str, expected_date",
    [
        ("MST 281865, 2026-07-01 시행", "2026-07-01"),
        ("MST 61603, 1988-02-25 시행", "1988-02-25"),
        ("MST 285913, 2026-05-12 시행", "2026-05-12"),
        ("MST 258873, 2024-05-17 시행", "2024-05-17"),
    ],
)
def test_extract_effective_date_positive(version_str, expected_date):
    """버전 문구에 명시된 시행일을 정상 파싱하는지 검증한다."""
    assert _extract_effective_date(version_str) == expected_date


@pytest.mark.parametrize(
    "version_str",
    [
        "MST 284415, 2026-09-27 확인, 제1항 발췌",
        "국가법령정보센터 판결요지, 2026-09-27 확인",
        "",
        None,
    ],
)
def test_extract_effective_date_negative(version_str):
    """시행일이 명시되지 않은 경우 None을 반환하며 지어낸 날짜(1980-01-01 등)를 반환하지 않는지 검증한다."""
    assert _extract_effective_date(version_str) is None


# ==============================================================================
# 3. 대조군 테스트: 판례/결정례 배제 및 공식 법령 링크 선별 (대조군 3건 이상)
# ==============================================================================
@pytest.mark.parametrize(
    "url, expected_result",
    [
        # 대조군 1: 대법원 판례 URL
        ("https://www.law.go.kr/precInfoP.do?precSeq=64694", False),
        # 대조군 2: 판례 간이 링크
        ("https://www.law.go.kr/판례/(95다38677)", False),
        # 대조군 3: 헌법재판소 결정례 링크
        ("https://www.law.go.kr/DRF/lawService.do?target=detc&ID=134879", False),
        # 대조군 4: 판례 상세 파라미터 포함
        ("https://www.law.go.kr/DRF/lawService.do?target=prec&ID=99999", False),
        # 양성: 공식 법령 조문 링크
        ("https://www.law.go.kr/법령/형사소송법/제368조", True),
        ("https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joNo=0751", True),
        ("https://www.law.go.kr/LSW/lsLinkCommonInfo.do?lsJoLnkSeq=1031511213", True),
    ],
)
def test_is_official_law_url(url, expected_result):
    """판례 및 헌재 결정례는 조문 미러 등록에서 제외되고 공식 조문만 선별되는지 검증한다."""
    assert _is_official_law_url(url) is expected_result


# ==============================================================================
# 4. 기능 테스트: 조문 번호 정규화 및 검색
# ==============================================================================
@pytest.mark.parametrize(
    "input_val, expected_norm",
    [
        ("202", "202"),
        ("제202조", "202"),
        ("202조의2", "202의2"),
        ("제202조의2", "202의2"),
        ("51의2", "51의2"),
        ("제51조의2", "51의2"),
    ],
)
def test_canon_article(input_val, expected_norm):
    """조문 번호의 다양한 서식 표기가 일관되게 정규화되는지 검증한다."""
    assert _canon_article(input_val) == expected_norm


def test_local_legal_mirror_integration():
    """LocalLegalMirror가 rules.json에서 보강될 때 가지조문과 비공식 출처 표기를 갖추는지 검증한다."""
    mirror = LocalLegalMirror()
    # 가지조문(군인사법 제51조의2) 검색 검증
    law_entry = mirror.find_law("군인사법", article="51조의2")
    assert law_entry is not None, "군인사법 제51조의2 검색 실패"
    assert law_entry.get("article") == "51의2"
    assert law_entry.get("authority") == "USER_REFERENCE_NOT_OFFICIAL"

    # 시행일이 없는 조문(민법 제751조)에 시점 검토 요청 시 UNRESOLVED_MIRROR 처리 확인 (오탐 방지)
    entry_as_of = mirror.find_law("민법", article="751", as_of="2020-01-01")
    assert entry_as_of is not None
    assert entry_as_of.get("temporal_scope") == "UNRESOLVED_MIRROR"
