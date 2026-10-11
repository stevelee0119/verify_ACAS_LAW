"""Public generated document routes for explicit and inferred exhibit cell ownership."""
import pytest

from packages.claim_engine.evidence_consistency import check_exhibits, exhibit_rows
from packages.document_engine.registry import parse_document
from scripts.audit.corpus import build_pdf


def _pdf(tmp_path, body):
    path = tmp_path / 'public_table_ownership.pdf'
    build_pdf({'name': path.name, 'header': '공개 경로 합성', 'footer': '합성 출처',
               'body': [('h', '입증방법')] + body + [('h', '첨부서류')]}, path)
    return parse_document(str(path), document_id='public_table_ownership', filename=path.name,
                          mime_type='application/pdf', sha256='0' * 64)


def _duplicates(doc):
    return [f for f in check_exhibits(doc)
            if f.confidence_features.get('rule_id') == 'EVI.EVIDENCE_NUMBER_DUPLICATE']


@pytest.mark.parametrize('title', ['점검대장', '배치기록', '장비목록'])
def test_synthetic_inferred_mixed_cells_follow_same_identity_as_paragraphs(tmp_path, title):
    tails = [f'{title}, 부록7쪽 확인 부분.', f'{title}: 순서를 설명한다.']
    paragraph = _pdf(tmp_path, [('p', f'갑 제1호증 {tail}') for tail in tails])
    table = _pdf(tmp_path, [('table', [['갑 제1호증', tail] for tail in tails])])
    rows = exhibit_rows(table)
    assert len(rows) == 2 and all(not row['from_lines'] for row in rows)
    assert [row['name'] for row in rows] == tails
    assert all(row['party'] == '갑' and row['number'] == 1 and not any(key in row for key in ('date', 'author', 'purpose')) for row in rows)
    assert not _duplicates(paragraph)
    assert not _duplicates(table)


@pytest.mark.parametrize('title', ['점검대장', '배치기록', '장비목록'])
def test_synthetic_explicit_title_cells_repeat_with_different_purpose(tmp_path, title):
    doc = _pdf(tmp_path, [('table', [['호증', '서증명', '입증취지'],
        ['갑 제1호증', title, '부록7쪽 확인 부분.'],
        ['갑 제1호증', title, '순서를 설명한다.']])])
    rows = exhibit_rows(doc)
    assert len(rows) == 2 and [row['name'] for row in rows] == [title, title]
    assert not _duplicates(doc)


@pytest.mark.parametrize('title', ['점검대장', '배치기록', '장비목록'])
@pytest.mark.parametrize('explicit', [False, True])
def test_synthetic_genuine_subtitles_remain_distinct_in_each_table_route(tmp_path, title, explicit):
    cells = [['갑 제1호증', f'{title}: 동쪽'], ['갑 제1호증', f'{title}: 서쪽']]
    if explicit:
        cells = [['호증', '서증명', '작성일']] + [row + ['2025. 3. 4.'] for row in cells]
    doc = _pdf(tmp_path, [('table', cells)])
    found = _duplicates(doc)
    assert len(found) == 1 and str(found[0].evidence_grade) == 'A'


@pytest.mark.parametrize('title', ['점검대장', '배치기록', '장비목록'])
def test_synthetic_two_column_explicit_title_ownership_survives_inference_route(tmp_path, title):
    doc = _pdf(tmp_path, [('table', [['호증', '서증명'],
        ['갑 제1호증', f'{title}, 부록7쪽 확인 부분.'],
        ['갑 제1호증', f'{title}: 순서를 설명한다.']])])
    rows = exhibit_rows(doc)
    assert len(rows) == 2 and all(not row['from_lines'] for row in rows)
    found = _duplicates(doc)
    assert len(found) == 1 and str(found[0].evidence_grade) == 'A'
