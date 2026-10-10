"""TK-72 통합 시간 보완: 공개 문법으로 직접 만든 합성 입력만 사용한다."""
import random
import re
import time

import pytest

from packages.common.enums import CitationType
from packages.common.schemas import Block, Citation, NormalizedDocument, Page
from packages.document_engine.reading_text import (
    QUOTE_SPAN_RE, SENTENCE_END_RE, SPACE_MAP, _normalize_spaces, sentence_bounds,
)
from packages.legal_engine.citation_extractor import (
    BARE_PARAGRAPH_REF_RE, LAW_RE, SpanTracker, _law_matches, extract_citations, extract_from_text,
)


def _matches(matches):
    return [(m.span(), m.groupdict(), m.groups()) for m in matches]


@pytest.mark.parametrize("name", [
    "「민법」", "『합성거래법률』", "합성 시행령", "동법", "같은 법 시행규칙",
    "가" * 39 + "법률", "나" * 40 + "규칙", "「" + "다" * 41 + "조례」",
    "법", "제12조", "", "자료제목",
])
@pytest.mark.parametrize("bridge", [" ", "", "  부칙\t", "\n부칙\n", "\u3000", "!", "부칙 부칙"])
def test_anchored_law_search_preserves_public_match_contract(name, bridge):
    text = f"앞 문장이다. {name}{bridge}제 17 조의2 제3항 제4호의5 가목, 제18조. 뒤 문장이다."
    assert _matches(_law_matches(text)) == _matches(LAW_RE.finditer(text))


def test_anchored_law_search_preserves_order_across_overlapping_grammar():
    rng = random.Random(239)
    pieces = ["「", "』", "합성법", "부칙", "가" * 43 + "규칙", "제1조", "제 22 조",
              "제3항", "제4호", "의5", "다.", "법제1조", " ", "\n", "\t", "\u3000"]
    for _ in range(500):
        text = "".join(rng.choices(pieces, k=25))
        assert _matches(_law_matches(text)) == _matches(LAW_RE.finditer(text))


@pytest.mark.parametrize("space", [" ", "\n", "\t"])
def test_law_name_anchor_does_not_limit_intervening_whitespace(space):
    text = "「합성법률」" + space * 80000 + "부칙" + space * 80000 + "제17조 제3항"
    started = time.perf_counter()
    matches = list(_law_matches(text))
    elapsed = time.perf_counter() - started
    assert len(matches) == 1
    assert matches[0].span() == (0, len(text))
    assert matches[0].group("law", "article", "paragraph") == ("「합성법률」", "17", "3")
    assert elapsed < 1.0


@pytest.mark.parametrize("prefix", ["", " ", "다.", "조", "조 ", "조\t", "조  ", "1", "９", "가"])
def test_paragraph_anchor_preserves_negative_lookbehind(prefix):
    original = re.compile(r"(?<![\d조])(?<!조\s)제\s*(?P<paragraph>\d+)\s*항(?:\s*제\s*(?P<item>\d+)\s*호)?")
    text = prefix + "제 3 항 제4호. 제5항"
    assert _matches(BARE_PARAGRAPH_REF_RE.finditer(text)) == _matches(original.finditer(text))


def _original_bounds(text):
    masked = QUOTE_SPAN_RE.sub(lambda m: "“" + "x" * (len(m.group(0)) - 2) + "”", text)
    bounds, start = [], 0
    for m in SENTENCE_END_RE.finditer(masked):
        bounds.append((start, m.end()))
        start = m.end()
    if start < len(text):
        bounds.append((start, len(text)))
    return bounds


@pytest.mark.parametrize("text", [
    "진술이다. 다음 진술임. 확인됨. 끝이다.", "첫 줄\n다음 줄\n", "인용). 다음!? 끝",
    "2025. 3. 4. 날짜는 유지한다.", "다.붙임 임.붙임 ?붙임 !붙임", "짧은 말. 뒤",
    '“직접 인용이다. 계속되는 직접 인용문이다.”라고 진술한다. 끝',
    '"따옴표 속 합성 문장이다. 쟁점은 남아 있다."(자료). 다음',
    "", ").", ".", "\n" * 3000,
])
def test_sentence_boundaries_keep_dates_quotes_and_paragraphs(text):
    assert sentence_bounds(text) == _original_bounds(text)


@pytest.mark.parametrize("text", [
    "합성 자료이다.", "\u00a0「합성법」\u2007제3조\u202f제2항\u3000",
    "\u2007" * 80000, "일반 공백\t줄바꿈\n유지", "\u2001\u2009\r", "",
])
def test_reading_space_normalization_preserves_length_and_characters(text):
    assert _normalize_spaces(text) == text.translate(SPACE_MAP)
    assert len(_normalize_spaces(text)) == len(text)


def test_first_pattern_seal_keeps_endpoint_contract_after_more_patterns():
    tracker = SpanTracker()
    spans = [(2, 8), (4, 6), (10, 13), (14, 14)]
    for start, end in spans:
        tracker.add(start, end)
    tracker.seal_pattern()
    for span in [(1, 3), (7, 16), (0, 2)]:
        tracker.add(*span)
        spans.append(span)
    tracker.seal_pattern()
    for start in range(18):
        for end in range(start, 19):
            assert tracker.overlaps(start, end) == any(s <= start < e or s < end <= e for s, e in spans)


def test_anchor_and_sentence_short_repetitions():
    text = "「합성법률」 부칙 제17조 제2항. 적용된다."
    expected = _original_bounds(text)
    started = time.perf_counter()
    for _ in range(2500):
        assert len(list(_law_matches(text))) == 1
        assert sentence_bounds(text) == expected
    assert time.perf_counter() - started < 0.1


@pytest.mark.parametrize("text", [
    "김가나, 「합성 논문 제목 첫째」, 학술원, 2024",
    "이다라·박마바, 「합성 논문 제목 둘째」, 학술원, 2023",
    "최사아, 「합성 논문 제목 셋째」, 학술원, 2022",
    "「합성법률」 제17조 및 제18조에 따른다.",
    "헌재 2024. 1. 2. 2023헌바100 결정에 따른다.",
    "대법원 2024. 1. 2. 선고 2023다100 판결에 따른다.",
])
def test_document_batch_returns_public_citations_and_independent_attributes(text):
    doc = NormalizedDocument("s", "s.txt", "text/plain", "s",
                             pages=[Page(1, blocks=[Block("a", text, 1), Block("b", text, 1)])])
    citations = extract_citations(doc)
    assert len(citations) >= 2
    assert {c.block_id for c in citations} == {"a", "b"}
    assert all(type(c) is Citation and c.citation_id.startswith("CIT_") for c in citations)
    assert all(c.to_dict()["raw_text"] == c.raw_text for c in citations)
    assert len({id(c.attributes) for c in citations}) == len(citations)
    citations[0].attributes["synthetic_mutation"] = True
    assert "synthetic_mutation" not in citations[1].attributes


@pytest.mark.parametrize("author", ["김가나", "이다라", "박마바"])
def test_academic_citation_still_bounds_a_statute_claim_in_mixed_text(author):
    text = f"「합성법률」 제17조에 따른 주장, {author}, 「합성 학술 논문 제목」, 학술원, 2024; 「합성법률」 제18조에 따른다."
    citations = extract_from_text(text)
    statutes = [c for c in citations if c.type == CitationType.STATUTE]
    academic = [c for c in citations if c.type == CitationType.ACADEMIC]
    assert len(statutes) == 2 and len(academic) == 1
    # 원래 학술 저자 문법은 두 글자 '주장'부터 쉼표 저자 목록으로 잡는다.
    assert statutes[0].attributes["claim_text"] == "에 따른"
    assert statutes[1].attributes["claim_text"] == "에 따른다."
    assert "claim_text" not in academic[0].attributes


def test_table_duplicate_keeps_first_cell_per_row_and_all_rows():
    text = "김가나, 「합성 학술 논문 제목」, 학술원, 2024"
    table = Block("t", text, 1, block_type="table",
                  attributes={"cells": [[text, text], [text]], "table_ref": "synthetic-table"})
    doc = NormalizedDocument("s", "s.txt", "text/plain", "s", pages=[Page(1, blocks=[table])])
    citations = extract_citations(doc)
    assert len(citations) == 2
    assert [c.attributes["table_cell"] for c in citations] == [
        {"table_ref": "synthetic-table", "row": 0, "column": 0},
        {"table_ref": "synthetic-table", "row": 1, "column": 0},
    ]
    assert all(type(c) is Citation for c in citations)


@pytest.mark.parametrize("head", [
    "「합성법률」 제17조", "『가상규칙』 제23조", "김가나, 「합성 학술 논문 제목」, 학술원, 2024",
])
def test_duplicate_quote_target_does_not_transfer_to_retained_citation(head):
    first = "첫 번째 합성 직접 인용문을 제시한다"
    second = "다른 두 번째 합성 직접 인용문을 제시한다"
    text = f'{head}는 "{first}"라고 한다. {head}는 "{second}"라고 한다.'
    direct = extract_from_text(text)
    doc = NormalizedDocument("s", "s.txt", "text/plain", "s",
                             pages=[Page(1, blocks=[Block("a", text, 1)])])
    actual = extract_citations(doc)
    assert len(direct) == 2 and len(actual) == 1
    assert [c.quoted_text for c in direct] == [first, second]
    assert actual[0].quoted_text == first
    assert "additional_quotes" not in actual[0].attributes


def test_duplicate_in_same_sentence_still_ends_first_claim():
    text = "「합성법률」 제17조에 따른 첫 주장, 「합성법률」 제17조에 따른 나중 주장."
    doc = NormalizedDocument("s", "s.txt", "text/plain", "s",
                             pages=[Page(1, blocks=[Block("a", text, 1)])])
    actual = extract_citations(doc)
    assert len(actual) == 1
    assert actual[0].attributes["claim_text"] == "에 따른 첫 주장,"


def test_continued_reference_keeps_discarded_occurrence_identity():
    text = "「합성법률」 제17조가 있다. 「합성법률」 제17조 및 제18조가 있다."
    doc = NormalizedDocument("s", "s.txt", "text/plain", "s",
                             pages=[Page(1, blocks=[Block("a", text, 1)])])
    actual = extract_citations(doc)
    assert [c.article for c in actual] == ["17", "18"]
    head = actual[1].attributes["continued_from"]
    assert head.startswith("CIT_") and head != actual[0].citation_id
