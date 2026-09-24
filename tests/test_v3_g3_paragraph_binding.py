"""추가지시 G3: 조문의 항·호 단위 결합.

'같은 조 제N항'·'동조 제N항'·'위 조항'·조 없이 쓴 '제N항'을 앞 인용의 조로 풀고, 뒤따르는 수치를 가장 가까운
항 인용에 결합한다. 판정 근거에는 비교한 조문을 푼 이름으로 적는다. 분야를 바꾼 합성 문장으로 시험한다.
"""
from __future__ import annotations

import pytest

from packages.legal_engine.citation_extractor import extract_from_text
from packages.legal_engine.provision_content import compare_claim_to_provision
from packages.legal_engine.source_review import compared_label


def _by_paragraph(text):
    return {(c.article, c.paragraph): c for c in extract_from_text(text) if c.law_name}


def test_numbers_bind_to_the_nearest_paragraph_citation():
    """민사: '같은 조 제2항은 … 10년'의 10년은 제1항이 아니라 제2항과 비교한다."""
    cites = _by_paragraph("민법 제766조 제1항은 손해 및 가해자를 안 날로부터 3년, "
                          "같은 조 제2항은 불법행위를 한 날로부터 10년이라고 정한다.")
    first, second = cites[("766", "1")], cites[("766", "2")]
    assert "3년" in first.attributes["claim_text"] and "10년" not in first.attributes["claim_text"]
    assert "10년" in second.attributes["claim_text"] and "3년" not in second.attributes["claim_text"]
    assert second.attributes["resolved_label"] == "민법 제766조 제2항"


@pytest.mark.parametrize("text,law,article,paragraph,number", [
    ("행정소송법 제20조 제1항은 90일, 제2항은 1년의 제소기간을 정한다.", "행정소송법", "20", "2", "1년"),        # 행정
    ("국가배상법 제2조 제1항 본문은 배상책임을 정하고, 동조 제2항은 구상권을 정한다.", "국가배상법", "2", "2", "구상권"),  # 국가배상
    ("근로기준법 제26조 제1항은 30일 전 예고를, 같은 조 제2항은 예외를 정한다.", "근로기준법", "26", "2", "예외"),   # 노동
])
def test_same_article_references_across_fields(text, law, article, paragraph, number):
    cites = _by_paragraph(text)
    resolved = cites[(article, paragraph)]
    assert resolved.law_name == law and number in resolved.attributes["claim_text"]
    assert resolved.attributes["reference_to"].startswith(law)


def test_previous_reference_without_paragraph_keeps_the_same_provision():
    """형사: '위 조항'은 앞 인용과 같은 조항을 가리킨다."""
    [base, again] = extract_from_text("형사소송법 제309조는 임의성 없는 자백의 증거능력을 부정한다. "
                                      "위 조항은 고문으로 얻은 자백에도 적용된다.")
    assert (again.law_name, again.article, again.paragraph) == (base.law_name, base.article, base.paragraph)


@pytest.mark.parametrize("text", ["원고는 민법 제750조를 들며 같은 조건으로 계약하였다.",
                                  "민법 제750조에 따라 위조한 문서는 무효이다.",
                                  "형법 제231조와 관련해 피고는 동조하였다."])
def test_ordinary_words_are_not_references(text):
    assert len(extract_from_text(text)) == 1


def test_reference_far_from_the_previous_citation_is_not_bound():
    text = "민법 제750조는 불법행위를 정한다." + " 사실관계를 본다." * 40 + " 제2항은 별도로 본다."
    assert len(extract_from_text(text)) == 1


def test_comparison_uses_the_bound_paragraph_and_names_it():
    """수치 대조는 결합된 항의 원문과 하고, 근거에는 비교 대상 조문을 푼 이름으로 적는다."""
    cites = _by_paragraph("민법 제766조 제1항은 안 날로부터 3년, 같은 조 제2항은 불법행위를 한 날부터 10년을 "
                          "경과하면 소멸한다고 정한다.")
    second = cites[("766", "2")]
    paragraph_two = "② 불법행위를 한 날부터 10년을 경과한 때에도 전항과 같다."   # 합성 조문 문장
    paragraph_one = "① 손해 및 가해자를 안 날로부터 3년간 이를 행사하지 아니하면 시효로 인하여 소멸한다."
    assert compare_claim_to_provision(second.attributes["claim_text"], paragraph_two)["status"] != "CONTRADICTED"
    assert compare_claim_to_provision(second.attributes["claim_text"], paragraph_one)["status"] == "CONTRADICTED"
    assert compared_label(second) == "민법 제766조 제2항('같은 조 제2항')"
