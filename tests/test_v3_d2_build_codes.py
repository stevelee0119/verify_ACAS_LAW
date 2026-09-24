"""v3 D2: 공식 별표(HWP 표)에서 사건부호표를 만드는 규칙."""
from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "build_case_codes", Path(__file__).resolve().parents[1] / "scripts" / "build_case_codes.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_pairs_follow_two_column_layout_and_merged_rows():
    table = [["사회봉사허가청구사건,", "초사", "소년보호재항고사건", "트"],
             ["사회봉사허가취소청구사건", "", "소년보호신청사건", "푸초"],
             ["", "", "", ""],
             ["행정1심사건", "구합", "행정상고사건", "두"]]
    pairs = dict(build.code_pairs([table]))
    assert pairs["초사"] == "사회봉사허가청구사건, 사회봉사허가취소청구사건"
    assert pairs["트"] == "소년보호재항고사건" and pairs["구합"] == "행정1심사건" and pairs["두"] == "행정상고사건"


def test_level_from_case_type_name():
    assert build.level_of("행정상고사건") == "SUPREME"
    assert build.level_of("가사재항고사건") == "SUPREME"
    assert build.level_of("치료감호비상상고사건") == "SUPREME"
    assert build.level_of("가사특별항고사건") == "SUPREME"
    assert build.level_of("특허특별(준)항고사건") == "ANY"
    assert build.level_of("선거항고(재항고, 준항고, 특별항고)사건") == "ANY"
    assert build.level_of("행정항소사건") == "APPELLATE"
    assert build.level_of("행정항고사건") == "APPELLATE"
    assert build.level_of("행정1심사건") == "FIRST"
    assert build.level_of("가사1심합의사건") == "FIRST"
    assert build.level_of("가사비송단독사건") == "FIRST"
    assert build.level_of("선거소송사건") == "ANY"
    assert build.level_of("행정신청사건") == "ANY"
