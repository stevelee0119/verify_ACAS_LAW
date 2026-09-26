"""법령명 경계(서술어에 붙은 법령명)·공식 약칭·'동법 시행령' 해석. 문장은 시험용으로 새로 지었다."""
import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.citation_extractor import extract_citations
from packages.legal_engine.normalize import canonical_law_name


def laws(text):
    doc = NormalizedDocument("d", "d.pdf", "application/pdf", "0", pages=[Page(1, blocks=[Block("b0", text, 1)])])
    return [(c.law_name, c.article) for c in extract_citations(doc) if getattr(c, "law_name", None)]


@pytest.mark.parametrize("text, law", [
    ("피고는 원고를 기망한 형법 제347조의 사기죄를 범하였다.", "형법"),
    ("원고는 서류를 제출함으로써민법 제544조의 최고를 하였다.", "민법"),
    ("피고가 위반한 근로기준법 제23조에 따라 해고는 무효이다.", "근로기준법"),
    ("공사대금을 청구한바 민사소송법 제202조에 따라 판단한다.", "민사소송법"),
])
def test_predicate_before_law_name_is_not_part_of_it(text, law):
    assert (law, laws(text)[0][1]) == laws(text)[0]


@pytest.mark.parametrize("raw", ["대한민국헌법", "공공기관의 정보공개에 관한 법률", "성폭력범죄의 처벌 등에 관한 특례법",
                                 "학교폭력예방 및 대책에 관한 법률"])
def test_official_names_with_links_are_kept(raw):
    assert canonical_law_name(raw) == raw


@pytest.mark.parametrize("short, full", [
    ("국가계약법", "국가를 당사자로 하는 계약에 관한 법률"),
    ("공정거래법", "독점규제 및 공정거래에 관한 법률"),
    ("학교폭력예방법", "학교폭력예방 및 대책에 관한 법률"),
])
def test_official_abbreviations_resolve(short, full):
    assert canonical_law_name(short) == full
    assert laws(f"피고는 {short} 제3조를 위반하였다.")[0][0] == full


@pytest.mark.parametrize("text, expected", [
    ("근로기준법 제23조와 동법 시행령 제10조에 따른다.", ["근로기준법", "근로기준법 시행령"]),
    ("국가계약법 제27조 및 동법시행령 제76조에 의하면 입찰참가자격을 제한할 수 있다.",
     ["국가를 당사자로 하는 계약에 관한 법률", "국가를 당사자로 하는 계약에 관한 법률 시행령"]),
    ("건축법 제11조, 같은 법 시행규칙 제6조, 같은 법 제79조를 본다.", ["건축법", "건축법 시행규칙", "건축법"]),
])
def test_same_law_enforcement_decree_resolves_to_previous_law(text, expected):
    assert [name for name, _ in laws(text)] == expected
