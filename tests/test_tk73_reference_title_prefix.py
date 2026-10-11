"""Public source alignment at the exhibit-reference/title boundary."""
import time

import pytest

from packages.claim_engine.evidence_consistency import (
    _duplicate_mention_view, _numbering, check_exhibits, exhibit_rows,
)
from packages.document_engine.reading_text import build_reading_text
from packages.document_engine.registry import parse_document
from scripts.audit.corpus import build_pdf


def _parsed(tmp_path, extension, lines):
    path = tmp_path / f'public_reference_prefix.{extension}'
    if extension == 'pdf':
        build_pdf({'name': path.name, 'header': '공개 경계 합성', 'footer': '합성 출처',
                   'body': [('p', line) for line in lines]}, path)
    else:
        path.write_text('\n'.join(lines), encoding='utf-8')
    return parse_document(str(path), document_id='public_reference_prefix', filename=path.name,
                          mime_type='application/pdf' if extension == 'pdf' else 'text/plain',
                          sha256='0' * 64)


def _duplicates(doc):
    return [f for f in check_exhibits(doc)
            if f.confidence_features.get('rule_id') == 'EVI.EVIDENCE_NUMBER_DUPLICATE']


@pytest.mark.parametrize('extension', ['pdf', 'txt'])
@pytest.mark.parametrize('section', [False, True])
@pytest.mark.parametrize('prefix,title', [('각 ', '점검기록'), (') ', '배치대장'), ('. ', '보관표')])
def test_synthetic_reference_grammar_does_not_reenter_title(tmp_path, extension, section, prefix, title):
    doc = _parsed(tmp_path, extension, (['입증방법'] if section else []) + [
        f'갑 제1호증 {prefix}{title}', f'갑 제1호증 {title}: 순서를 설명한다.', '첨부서류'])
    rows = exhibit_rows(doc)
    assert len(rows) == 2 and rows[0]['name'] == title
    reading = build_reading_text(doc)
    for row in rows:
        view = _duplicate_mention_view(row)
        for origin in view['origins']:
            start, end = origin['reading_span']
            assert reading.text[start:end] == origin['text']
            left, right = origin['raw_span']
            assert view['raw_comparison_text'][left:right] == origin['text']
        assert row['date'] == row['author'] == row['purpose'] == ''
    assert not _duplicates(doc)


@pytest.mark.parametrize('extension', ['pdf', 'txt'])
@pytest.mark.parametrize('section', [False, True])
@pytest.mark.parametrize('prefix,title,other', [('각 ', '점검기록', '점검요약'),
                                              (') ', '배치대장', '배치보고'),
                                              ('. ', '보관표', '보관도면')])
def test_synthetic_reference_prefix_preserves_genuine_title_difference(tmp_path, extension, section,
                                                                      prefix, title, other):
    doc = _parsed(tmp_path, extension, (['입증방법'] if section else []) + [
        f'갑 제1호증 {prefix}{title}', f'갑 제1호증 {other}: 순서를 설명한다.', '첨부서류'])
    found = _duplicates(doc)
    assert len(found) == 1 and str(found[0].evidence_grade) == 'A'


@pytest.mark.parametrize('extension', ['pdf', 'txt'])
@pytest.mark.parametrize('title,other', [('각도표', '도표'), ('각서', '서'),
                                      ('「각 점검기록」', '「점검기록」'),
                                      ('「) 배치대장」', '「배치대장」'),
                                      ('「. 보관표」', '「보관표」')])
def test_synthetic_lexical_or_quoted_prefix_is_title_content(tmp_path, extension, title, other):
    doc = _parsed(tmp_path, extension, ['입증방법', f'갑 제1호증 {title}',
        f'갑 제1호증 {other}: 순서를 설명한다.', '첨부서류'])
    found = _duplicates(doc)
    assert len(found) == 1 and str(found[0].evidence_grade) == 'A'


@pytest.mark.parametrize('extension', ['pdf', 'txt'])
@pytest.mark.parametrize('literal', ['．', '）', '－', '각\u200d '])
def test_synthetic_normalization_does_not_create_reference_prefix_proof(tmp_path, extension, literal):
    doc = _parsed(tmp_path, extension, ['입증방법', f'갑 제1호증 {literal}점검기록',
        '갑 제1호증 점검기록: 순서를 설명한다.', '첨부서류'])
    rows = exhibit_rows(doc)
    first_source = rows[0]['duplicate_sources'][0]['text']
    # This font omits Cf. Without that glyph, the actual extracted `각 `
    # is a standalone quantifier; this does not claim original Cf survival.
    expected = 1
    if extension == 'txt':
        assert literal in first_source
    elif literal == '각\u200d ' and literal not in first_source:
        assert '각 ' in first_source
        expected = 0
    found = _duplicates(doc)
    assert len(found) == expected
    assert all(str(f.evidence_grade) == 'A' for f in found)


@pytest.mark.parametrize('extension', ['pdf', 'txt'])
def test_synthetic_continuation_never_completes_standalone_prefix_token(tmp_path, extension):
    doc = _parsed(tmp_path, extension, ['입증방법', '갑 제1호증 각', '점검기록',
        '갑 제1호증 점검기록: 순서를 설명한다.', '첨부서류'])
    rows = exhibit_rows(doc)
    assert len(rows[0]['duplicate_sources']) == 2
    assert rows[0]['duplicate_sources'][0]['text'].rstrip().endswith('각')
    found = _duplicates(doc)
    assert len(found) == 1 and str(found[0].evidence_grade) == 'A'


@pytest.mark.parametrize('extension', ['pdf', 'txt'])
@pytest.mark.parametrize('prefix,title', [('각 ', '기록, 봄'), (') ', '기록: 동쪽'),
                                        ('. ', '관측 [2024. 1. 2.]')])
def test_synthetic_projected_title_spans_keep_subtitles_dates_and_source_offsets(tmp_path, extension,
                                                                              prefix, title):
    doc = _parsed(tmp_path, extension, ['입증방법', f'갑 제1호증 {prefix}{title}',
        f'갑 제1호증 {title}: 순서를 설명한다.', '첨부서류'])
    reading = build_reading_text(doc)
    rows = exhibit_rows(doc)
    first = _duplicate_mention_view(rows[0])
    second = _duplicate_mention_view(rows[1])
    projected = first['origins'][0]['reference_title_prefix']
    start, end = projected['reading_span']
    assert reading.text[start:end] == projected['text']
    left, right = projected['raw_span']
    assert first['raw_comparison_text'][left:right] == projected['text']
    assert projected['text'].endswith(prefix)
    assert first['fallback'] == ''.join(title.split())
    start, end = second['title_span']
    assert second['comparison_text'][start:end] == title
    for view in (first, second):
        for origin in view['origins']:
            a, b = origin['normalized_source_span']
            assert a <= b
            assert origin['normalization_precision'] == 'fragment'
    assert not _duplicates(doc)


@pytest.mark.parametrize('origin', ['item', 'continuation'])
def test_synthetic_unverified_or_continuation_prefix_keeps_prior_comparison(origin):
    row = {'name': ') 기록', 'from_lines': True, 'duplicate_sources': [
        {'text': ') 기록', 'origin': origin, 'reading_span': (10, 14), 'sources': []}]}
    if origin == 'item':
        row['duplicate_sources'][0]['reference_span'] = (0, 10)
    view = _duplicate_mention_view(row)
    assert view['fallback'] == ')기록'
    assert 'reference_title_prefix' not in view['origins'][0]


def test_synthetic_long_actual_prefix_and_shared_branches_stay_bounded(tmp_path):
    line = '갑 제1호증의 1~999 ' + '.' * 50000 + '점검기록'
    doc = _parsed(tmp_path, 'txt', ['입증방법', line,
        '갑 제1호증의 1~999 점검기록: 순서를 설명한다.', '첨부서류'])
    rows = exhibit_rows(doc)
    assert len(rows) == 2 and rows[0]['name'] == '점검기록'
    assert all(len(row['branches']) == 999 for row in rows)
    started = time.perf_counter()
    assert not _numbering(doc, rows)
    assert time.perf_counter() - started < 0.1


def test_synthetic_normalized_expansion_keeps_raw_and_normalized_prefix_bases(tmp_path):
    doc = _parsed(tmp_path, 'txt', ['입증방법', '갑 제1호증) ﬃ 기록',
        '갑 제1호증 ffi 기록: 순서를 설명한다.', '첨부서류'])
    rows = exhibit_rows(doc)
    first = _duplicate_mention_view(rows[0])
    origin = first['origins'][0]
    prefix = origin['reference_title_prefix']
    assert rows[0]['name'] == 'ﬃ 기록'
    assert first['comparison_text'] == 'ffi 기록'
    assert origin['normalized_source_span'][1] == len(origin['text']) + 2
    assert prefix['raw_span'][1] == prefix['normalized_span'][1]
    assert prefix['comparison_offset'] > prefix['prior_comparison_offset']
    assert origin['normalized_span'][1] == len(first['comparison_text'])
    assert not _duplicates(doc)


@pytest.mark.parametrize('extension', ['pdf', 'txt'])
@pytest.mark.parametrize('prefix', ['각 ', ') ', '. '])
def test_synthetic_title_locator_and_narrative_offsets_after_prefix_projection(tmp_path, extension, prefix):
    doc = _parsed(tmp_path, extension, ['입증방법',
        f'갑 제1호증 {prefix}점검기록, 부록7쪽 확인 부분.',
        '갑 제1호증 점검기록: 순서를 설명한다.', '첨부서류'])
    reading = build_reading_text(doc)
    rows = exhibit_rows(doc)
    first, second = [_duplicate_mention_view(row) for row in rows]
    assert first['kind'] == 'locator' and second['kind'] == 'prose'
    for view, span_name in ((first, 'title_span'), (first, 'location_span'), (second, 'narrative_span')):
        origin = view['origins'][0]
        prefix_data = origin['reference_title_prefix']
        offset = prefix_data['comparison_offset']
        start, end = view[span_name]
        absolute = origin['reading_span'][0] + offset
        assert reading.text[absolute + start:absolute + end] == view['comparison_text'][start:end]
    assert not _duplicates(doc)
