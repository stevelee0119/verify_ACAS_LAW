"""v6 P2 법령명 추출 경계: 낫표 안 전체, 법령명 안의 '및', 연속 조문, 문서 안 약칭 후보와 재조회.

모든 문장과 법령명은 시험용으로 새로 지었다(가상 법령명은 실재 법령과 겹치지 않게 '시험'을 넣었다).
공식 API는 모의 응답으로 대신한다(실제 국가법령정보 응답 형식의 약칭 필드는 이 환경에서 확인하지 못했다).
"""
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from packages.common.enums import AdapterStatus, CitationType
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine import LegalVerifier, extract_citations, extract_from_text
from packages.legal_engine.normalize import law_name_suffix
from packages.source_adapters.law_go_kr import LawGoKrAdapter, _normalize_law_payload
from packages.source_adapters.local_mirror import LocalLegalMirror


def statutes(text):
    return [(c.law_name, c.article, c.paragraph) for c in extract_from_text(text) if c.type == CitationType.STATUTE]


# --- 낫표 안 법령명 전체 --------------------------------------------------------------------------------
@pytest.mark.parametrize("text, name", [
    ("「시험물질 관리 및 안전에 관한 법률」 제7조는 신고 의무를 둔다.", "시험물질 관리 및 안전에 관한 법률"),
    ("피고는 「공공시험장 설치 및 운영 등에 관한 특별법」 제12조 제2항을 들었다.", "공공시험장 설치 및 운영 등에 관한 특별법"),
    ("이 사건은 『시험기록 보존 또는 폐기에 관한 규칙』 제3조에 관한 것이다.", "시험기록 보존 또는 폐기에 관한 규칙"),
])
def test_bracketed_name_is_kept_whole_even_with_conjunctions(text, name):
    assert statutes(text)[0][0] == name


# --- 괄호 없는 법령명 안의 '및'과, 두 법령을 나열한 '및' ---------------------------------------------------
@pytest.mark.parametrize("text, name", [
    ("원고는 시험정보 이용촉진 및 정보보호 등에 관한 법률 제44조를 근거로 든다.", "시험정보 이용촉진 및 정보보호 등에 관한 법률"),
    ("피고는 시험장비 검사 및 교정에 관한 법률 제5조를 위반하였다.", "시험장비 검사 및 교정에 관한 법률"),
    ("시험용역 계약 및 대금지급에 관한 법률 제9조 제1항이 적용된다.", "시험용역 계약 및 대금지급에 관한 법률"),
])
def test_conjunction_inside_an_unbracketed_name(text, name):
    assert statutes(text)[0][0] == name


@pytest.mark.parametrize("text, name", [
    ("근로기준법 및 민법 제3조를 함께 본다.", "민법"),
    ("형법 및 형사소송법 제200조의2가 문제된다.", "형사소송법"),
    ("원고 및 피고는 상법 제24조를 다툰다.", "상법"),
])
def test_conjunction_between_two_laws_is_a_boundary(text, name):
    assert statutes(text)[0][0] == name


def test_suffix_helper_directly():
    assert law_name_suffix("「시험 예방 및 대책에 관한 법률」") == "시험 예방 및 대책에 관한 법률"
    assert law_name_suffix("다만 위 조치는 형법") == "형법"


# --- 연속 조문 ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("「민법」 제750조 및 제751조에 따라 배상한다.", [("민법", "750", None), ("민법", "751", None)]),
    ("형법 제3조, 제4조 제2항과 제9조의2를 다툰다.", [("형법", "3", None), ("형법", "4", "2"), ("형법", "9의2", None)]),
    ("상법 제24조 또는 제25조가 문제된다.", [("상법", "24", None), ("상법", "25", None)]),
])
def test_consecutive_articles_share_the_law(text, expected):
    assert statutes(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("민법 제750조 및 형법 제257조를 든다.", [("민법", "750", None), ("형법", "257", None)]),
    ("민법 제750조이다. 제4조의 설명은 없다.", [("민법", "750", None)]),
    ("민법 제750조의 요건과 제2장의 구성은 다르다.", [("민법", "750", None)]),
])
def test_continuation_does_not_cross_other_laws_or_sentences(text, expected):
    assert statutes(text) == expected


# --- 문서 안 약칭 후보 ---------------------------------------------------------------------------------
def doc(*texts):
    return NormalizedDocument("d", "d.pdf", "application/pdf", "0",
                              pages=[Page(1, blocks=[Block(f"b{i}", t, 1) for i, t in enumerate(texts)])])


def aliases(*texts):
    return {c.law_name: (c.attributes.get("law_alias_candidate"), c.attributes.get("law_alias_basis"))
            for c in extract_citations(doc(*texts)) if c.type == CitationType.STATUTE}


@pytest.mark.parametrize("texts, short, full", [
    (["「시험물질 관리 및 안전에 관한 법률」(이하 '시험물질법'이라 한다) 제7조를 본다.", "시험물질법 제8조도 같다."],
     "시험물질법", "시험물질 관리 및 안전에 관한 법률"),
    (["「공공시험장 설치 및 운영에 관한 법률」(이하 “시험장법”) 제2조가 있다.", "시험장법 제4조에 따른다."],
     "시험장법", "공공시험장 설치 및 운영에 관한 법률"),
    (["「시험기록 보존에 관한 법률」(이하 「기록보존법」이라 함) 제1조를 본다.", "기록보존법 제9조를 본다."],
     "기록보존법", "시험기록 보존에 관한 법률"),
])
def test_alias_defined_in_the_document(texts, short, full):
    assert aliases(*texts)[short] == (full, "DOCUMENT_DEFINITION")


@pytest.mark.parametrize("texts, short, full", [
    (["「시험폭력예방 및 대책에 관한 법률」 제16조를 본다.", "시험폭력예방법 제17조의 조치가 있다."],
     "시험폭력예방법", "시험폭력예방 및 대책에 관한 법률"),
    (["「시험장비관리 등에 관한 법률」 제3조를 본다.", "시험장비관리법 제5조도 적용된다."],
     "시험장비관리법", "시험장비관리 등에 관한 법률"),
    (["시험용역계약 및 대금지급에 관한 법률 제2조를 본다.", "시험용역계약법 제9조 위반이다."],
     "시험용역계약법", "시험용역계약 및 대금지급에 관한 법률"),
])
def test_alias_inferred_from_a_full_name_in_the_same_document(texts, short, full):
    assert aliases(*texts)[short] == (full, "DOCUMENT_FULL_NAME_PREFIX")


@pytest.mark.parametrize("texts, short", [
    (["「민사집행 및 보전에 관한 법률」 제1조를 본다.", "민법 제750조를 본다."], "민법"),           # 어간 4자 미만
    (["「시험물질 관리에 관한 법률」 제1조", "「시험물질 운송에 관한 법률」 제2조", "시험물질법 제3조"], "시험물질법"),  # 후보 2개
    (["「시험장비관리 등에 관한 법률」 제3조를 본다.", "시험용역법 제5조도 적용된다."], "시험용역법"),  # 어간 불일치
])
def test_no_alias_when_short_ambiguous_or_unrelated(texts, short):
    assert aliases(*texts)[short] == (None, None)


# --- 적힌 이름이 목록에 없을 때만 정식명으로 재조회 -----------------------------------------------------------
FULL = "시험폭력예방 및 대책에 관한 법률"


def row(name=FULL, **extra):
    return {"법령명한글": name, "법령ID": "000777", "법령일련번호": "300", "공포일자": "20200101",
            "시행일자": "20200301", "공포번호": "11", "제개정구분명": "일부개정", **extra}


def body():
    return {"법령": {
        "기본정보": {"법령ID": "000777", "법령일련번호": "300", "법령명_한글": FULL, "시행일자": "20200301",
                 "공포일자": "20200101", "공포번호": "11"},
        "조문": {"조문단위": [{"조문번호": "17", "조문여부": "조문", "조문시행일자": "20200301",
                           "조문내용": "제17조(조치) 조치에 관한 본문이다."}]},
        "부칙": {"부칙단위": {"부칙공포일자": "20200101", "부칙공포번호": "11",
                         "부칙내용": ["제1조(시행일) 이 법은 2020년 3월 1일부터 시행한다."]}}}}


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    law = LawGoKrAdapter(mirror=LocalLegalMirror(tmp_path / "empty"))
    monkeypatch.setattr(law, "status", lambda: AdapterStatus.READY)
    monkeypatch.setattr(LawGoKrAdapter, "api_key", property(lambda self: "TEST_SECRET_OC"))
    return law


def install(monkeypatch, adapter, rows_for):
    queries = []

    def request(url, *, params):
        if "MST" in params:
            payload = body()
        else:
            queries.append(params.get("query") or params.get("LID"))
            rows = rows_for(params)
            payload = {"LawSearch": {"totalCnt": len(rows), "page": 1, "law": rows}}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
    monkeypatch.setattr(adapter, "_http_get", request)
    return queries


def cite(written, alias=None):
    from packages.common.schemas import Citation
    attributes = {"law_alias_candidate": alias, "law_alias_basis": "DOCUMENT_FULL_NAME_PREFIX"} if alias else {}
    return Citation.create(CitationType.STATUTE, f"{written} 제17조", law_name=written, article="17",
                           attributes=attributes)


def full_name_only(params):
    return [row()] if params.get("query") in (FULL, None) or params.get("LID") else []


def verify(adapter, citation):
    return LegalVerifier(SimpleNamespace(law=adapter)).verify_statute(
        citation, as_of="2026-01-01", current_date="2026-09-26")


def test_short_name_resolves_through_the_document_full_name(adapter, monkeypatch):
    queries = install(monkeypatch, adapter, full_name_only)
    verdict = verify(adapter, cite("시험폭력예방법", FULL))
    assert queries[:2] == ["시험폭력예방법", FULL]
    assert verdict.review["law_alias"] == {"written": "시험폭력예방법", "resolved": FULL,
                                           "basis": "DOCUMENT_FULL_NAME_PREFIX", "found": True}
    assert verdict.levels["existence"] == "VERIFIED"
    assert not any(f.type.value == "STATUTE_NONEXISTENT" for f in verdict.findings)


def test_without_alias_the_absence_is_still_reported(adapter, monkeypatch):
    install(monkeypatch, adapter, full_name_only)
    verdict = verify(adapter, cite("시험폭력예방법"))
    assert any(f.type.value == "STATUTE_NONEXISTENT" for f in verdict.findings)


def test_alias_that_is_also_absent_keeps_the_absence(adapter, monkeypatch):
    install(monkeypatch, adapter, lambda params: [])
    verdict = verify(adapter, cite("시험폭력예방법", FULL))
    assert verdict.review["law_alias"]["found"] is False
    assert any(f.type.value == "STATUTE_NONEXISTENT" for f in verdict.findings)


@pytest.mark.parametrize("abbreviation_field", ["법령약칭명", "abbreviation"])
def test_official_abbreviation_field_matches_exactly(adapter, monkeypatch, abbreviation_field):
    install(monkeypatch, adapter, lambda params: [row(**{abbreviation_field: "시험폭력예방법"})])
    verdict = verify(adapter, cite("시험폭력예방법"))
    assert verdict.levels["existence"] == "VERIFIED"


def test_official_abbreviation_is_not_a_partial_match(adapter, monkeypatch):
    install(monkeypatch, adapter, lambda params: [row(법령약칭명="시험폭력예방법시행령")])
    verdict = verify(adapter, cite("시험폭력예방법"))
    assert any(f.type.value == "STATUTE_NONEXISTENT" for f in verdict.findings)


def test_normalized_payload_carries_abbreviation():
    records = _normalize_law_payload({"LawSearch": {"law": [row(법령약칭명="시험폭력예방법")]}})
    assert records[0]["abbreviation"] == "시험폭력예방법"
    assert deepcopy(records)[0]["law_name"] == FULL
