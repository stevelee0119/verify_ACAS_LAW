"""TK-01 (PUA 글리프 동적 복원) 및 TK-02 (개인정보 주소 마스킹 확장 / 대리인·법원 보존) 단위 테스트.

- 양성 3건 이상: 당사자 주소(도로명+동호, 지번, 층·호 표기 등 다양한 주소 마스킹)
- 대조군 3건 이상: 소송대리인 변호사 사무소 주소 보존, 법원 주소 보존, 법률 조문(제305조, 제108조 제801항 등) 비마스킹
- PUA 글리프 동적 매핑 복원 검증
"""
import pytest
from packages.common.schemas import Block, NormalizedDocument, Page, new_id
from packages.pii_engine.detector import detect
from packages.pii_engine.engine import PIIEngine
from packages.pii_engine.pseudonym import PseudonymStore
from packages.document_engine.pdf_parser import _map_pua_chars


# ==============================================================================
# 1. TK-01: PUA 글리프 동적 복원 단위 테스트
# ==============================================================================

def test_map_pua_chars_dynamic_restoration():
    """PUA(Private Use Area Co 범주) 글리프가 pypdfium2 텍스트와 동적으로 매핑 복원되는지 검증."""
    # 합성 데이터: pdfplumber에서는 PUA 문자로 디코딩되고, pypdfium2에서는 정상 문자로 나오는 상황
    plumber_str = "군번: 11\ue088203948\r\n조문\ue081지휘관\r\n\ue083AUDIT\ue092TEST\ue084"
    pdfium_str = "군번: 11-203948\r\n조문(지휘관\r\n[AUDIT:TEST]"
    
    mapping = _map_pua_chars(plumber_str, pdfium_str)
    assert mapping.get("\ue088") == "-"
    assert mapping.get("\ue081") == "("
    assert mapping.get("\ue083") == "["
    assert mapping.get("\ue092") == ":"
    assert mapping.get("\ue084") == "]"


# ==============================================================================
# 2. TK-02 양성 테스트: 당사자 주소 상세 마스킹 (3건 이상)
# ==============================================================================

def _make_engine() -> PIIEngine:
    store = PseudonymStore("test_proj")
    return PIIEngine(store)


def test_party_address_road_and_dongho_positive():
    """양성 1: 당사자 도로명 주소 + 동·호수 전체가 마스킹되는지 검증."""
    text = (
        "원 고 이 철 수\n"
        "경기도 성남시 분당구 판교역로 166, 105동 1204호\n"
        "주민등록번호: 850101-1234567"
    )
    engine = _make_engine()
    res = engine.mask_text(text)
    # 도로명과 동·호수까지 남김없이 마스킹되어야 함
    assert "판교역로" not in res.masked_text
    assert "105동 1204호" not in res.masked_text
    assert "[ADDRESS_" in res.masked_text


def test_party_address_jibun_positive():
    """양성 2: 당사자 지번 주소(읍/면/리/번지) 전체가 마스킹되는지 검증."""
    text = (
        "피고인 홍 길 동\n"
        "강원도 원주시 소초면 흥양리 456-7번지\n"
    )
    engine = _make_engine()
    res = engine.mask_text(text)
    assert "소초면" not in res.masked_text
    assert "456-7" not in res.masked_text
    assert "[ADDRESS_" in res.masked_text


def test_party_address_floor_room_positive():
    """양성 3: 당사자 빌딩 층·호수 상세 주소가 마스킹되는지 검증."""
    text = (
        "신청인 김 영 희\n"
        "서울특별시 마포구 마포대로 89, 7층 702호\n"
    )
    engine = _make_engine()
    res = engine.mask_text(text)
    assert "마포대로 89" not in res.masked_text
    assert "702호" not in res.masked_text
    assert "[ADDRESS_" in res.masked_text


# ==============================================================================
# 3. TK-02 대조군 테스트: 대리인·법원 주소 보존 및 비주소 비마스킹 (3건 이상)
# ==============================================================================

def test_lawyer_office_address_preserved_control():
    """대조군 1: 소송대리인 변호사 사무소 주소는 마스킹하지 않고 보존(사용자 정책 결정)."""
    text = (
        "소송대리인 변호사 김 변 호\n"
        "서울 서초구 서초중앙로 123, 401호 (법률사무소 정의)\n"
    )
    engine = _make_engine()
    res = engine.mask_text(text)
    # 대리인 주소는 원문 그대로 보존되어야 함
    assert "서울 서초구 서초중앙로 123, 401호" in res.masked_text
    assert "[ADDRESS_" not in res.masked_text


def test_court_address_preserved_control():
    """대조군 2: 법원 주소는 마스킹하지 않고 보존."""
    text = (
        "서울행정법원 귀중\n"
        "서울 서초구 강남대로 215\n"
    )
    engine = _make_engine()
    res = engine.mask_text(text)
    assert "서울 서초구 강남대로 215" in res.masked_text
    assert "[ADDRESS_" not in res.masked_text


def test_statute_numbers_not_masked_control():
    """대조군 3: 법률 조문 번호(제305조, 제108조 제801항)가 주소로 오탐되어 마스킹되지 않음."""
    text = (
        "원고는 민법 제305조 및 상법 제108조 제801항에 의거하여 청구합니다."
    )
    engine = _make_engine()
    res = engine.mask_text(text)
    assert "민법 제305조" in res.masked_text
    assert "상법 제108조 제801항" in res.masked_text
    assert "[ADDRESS_" not in res.masked_text
