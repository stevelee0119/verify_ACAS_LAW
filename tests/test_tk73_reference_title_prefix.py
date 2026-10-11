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
