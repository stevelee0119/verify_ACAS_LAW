"""Public boundary alternatives: provenance and metadata, never preferred verdicts."""
import json

import pytest

from packages.common.schemas import BBox, Block, NormalizedDocument, Page
from packages.document_engine import parse_document
from packages.document_engine.paragraph_reconstruction import reconstruct_page_blocks
from packages.document_engine.reading_text import build_reading_text


def _blocks(texts, endpoint=500):
    return [Block(f'line-{i}', text, 1, bbox=BBox(72, 80 + i * 15, endpoint if i < 2 else 250, 92 + i * 15))
            for i, text in enumerate(texts)]


@pytest.mark.parametrize('width', [420, 595, 720])
def test_unknown_selection_is_distinct_from_hypotheses(width):
    from packages.document_engine.boundary_candidates import project_boundary_candidate

    block = reconstruct_page_blocks(_blocks(['검토 내용 가', '나다 부분을', '정리하였다.']), page_width=width)[0]
    row = block.attributes['boundary_observations'][0]['decision']
    assert row['observed_state'] == 'UNKNOWN'
    assert row['selected_separator'] == ('' if width < 720 else ' ')
    assert row['selection_reason'] == ('LEGACY_FULLNESS_FRAGMENT' if width < 720 else 'LEGACY_DEFAULT_SPACE')
    assert row['legacy']['page_floor'] == 0.75 * width
    assert row['legacy']['floor_applied'] is (width == 720)
    assert [(choice['id'], choice['confirmation']) for choice in row['alternatives']] == [('JOIN', 'UNCONFIRMED'), ('SPACE', 'UNCONFIRMED')]
    assert project_boundary_candidate(block, 0, 'JOIN') == '검토 내용 가나다 부분을 정리하였다.'
    assert project_boundary_candidate(block, 0, 'SPACE') == '검토 내용 가 나다 부분을 정리하였다.'
    assert project_boundary_candidate(block) == block.text


@pytest.mark.parametrize('texts', [
    ['검토한 (새', '문서)이다.'], ['내용 가', '나다를 살폈다.'], ['항목 Ａ', 'Ｂ를 정리하였다.'],
    ['머리 ㍿', '확인하였다.', '끝이다.'], ['앞 ᄀ', 'ᅡ나다', '끝이다.'], ['  Ａ  ', '  Ｂ  ', 'Ｃ  '],
])
def test_projection_preserves_primary_and_maps_normalization_honestly(texts):
    from packages.document_engine.boundary_candidates import project_boundary_candidate

    block = reconstruct_page_blocks(_blocks(texts), page_width=595)[0]
    assert project_boundary_candidate(block) == block.text
    runs = block.attributes['boundary_source_runs']
    assert len(runs) == len(texts)
    assert [run['line_index'] for run in runs] == list(range(len(texts)))
    assert all(run['source_block_id'] == f'line-{i}' for i, run in enumerate(runs))
    for entry in block.attributes['boundary_observations']:
        decision = entry['decision']
        assert decision['version'] == 1
        assert decision['source']['left_line'] + 1 == decision['source']['right_line']
        assert decision['alignment']['precision'] in {'EXACT_TEXT', 'SOURCE_LINE_RANGE'}
        if decision['alignment']['precision'] == 'EXACT_TEXT':
            a, b = decision['alignment']['primary_span']
            assert block.text[a:b] == decision['selected_separator']
        else:
            assert decision['alignment']['primary_span'] is None
            assert decision['alignment']['reason']
    json.dumps(block.to_dict(), ensure_ascii=False)


def _pdf(path, width, size, extra, has_space, *, font='HYSMyeongJo-Medium', leading=False, left='자료는 (새', right='문서)로 정리된다.'):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont(font))
    page = canvas.Canvas(str(path), pagesize=(width, 842))
    page.setFont(font, size)
    page.drawString(72, 760, left + (' ' if has_space and not leading else ''))
    page.drawString(72, 760 - size * 1.5, (' ' if has_space and leading else '') + right)
    for i in range(extra):
        page.drawString(72, 550 - i * size * 1.5, '별도 문단에서 다른 내용을 살핀다.')
    page.save()


@pytest.mark.parametrize('width,size,extra,font', [
    (420, 10, 0, 'HYSMyeongJo-Medium'), (595, 12, 1, 'HYSMyeongJo-Medium'),
    (720, 14, 2, 'HYGothic-Medium'),
])
@pytest.mark.parametrize('has_space,leading', [(False, False), (True, False), (True, True)])
def test_actual_pdf_candidates_and_reading_associations(tmp_path, width, size, extra, font, has_space, leading):
    from packages.document_engine.boundary_candidates import project_boundary_candidate
    import pdfplumber

    path = tmp_path / 'alternatives.pdf'
    _pdf(path, width, size, extra, has_space, font=font, leading=leading)
    with pdfplumber.open(path) as source:
        chars = source.pages[0].chars
    doc = parse_document(str(path), document_id='synthetic', filename=path.name, mime_type='application/pdf', sha256='synthetic')
    assert not doc.parse_warnings
    block = next(b for b in doc.blocks if '자료는 (새' in b.text)
    observation = block.attributes['boundary_observations'][0]
    decision = observation['decision']
    assert decision['observed_state'] == ('SPACE_CONFIRMED' if has_space else 'UNKNOWN')
    assert project_boundary_candidate(block) == block.text
    assert len(decision['alternatives']) == (1 if has_space else 2)
    assert decision['legacy']['used_for_selection'] is (not has_space)
    if has_space:
        with pytest.raises(ValueError):
            project_boundary_candidate(block, 0, 'JOIN')
    else:
        assert project_boundary_candidate(block, 0, 'JOIN') == '자료는 (새문서)로 정리된다.'
        assert project_boundary_candidate(block, 0, 'SPACE') == '자료는 (새 문서)로 정리된다.'
    assert all(chars[i]['text'].isspace() for i in observation['space_glyph_indices'])
    for indices in (observation['previous_glyph_indices'], observation['following_glyph_indices']):
        assert indices and all(0 <= i < len(chars) for i in indices)
    reading = build_reading_text(doc)
    associations = [row for row in reading.boundary_associations if row['block_id'] == block.block_id]
    assert len(associations) == 1
    row = associations[0]
    assert row['precision'] == 'EXACT_TEXT'
    assert row['alternatives_checked'] is False
    a, b = row['reading_span']
    assert reading.text[a:b] == decision['selected_separator']
    assert row in reading.boundaries_between(a - 1, b + 1)


def test_lazy_representation_is_linear_and_rejects_unproven_selection():
    from packages.document_engine.boundary_candidates import project_boundary_candidate

    block = reconstruct_page_blocks(_blocks(['검토 가'] * 64), page_width=720)[0]
    rows = block.attributes['boundary_observations']
    assert len(rows) == 63
    assert sum(len(row['decision']['alternatives']) for row in rows) == 126
    assert all('text' not in choice for row in rows for choice in row['decision']['alternatives'])
    with pytest.raises(ValueError):
        project_boundary_candidate(block, 0, 'CONFIRMED_JOIN')


@pytest.mark.parametrize('has_space', [False, True])
def test_actual_pipeline_metadata_does_not_change_primary_findings_or_scores(tmp_path, monkeypatch, has_space):
    import packages.verification_engine.pipeline as pipeline_module
    from packages.audit_engine import AuditChain
    from packages.common.storage import sha256_file
    from packages.report_engine.serialize import to_jsonable
    from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline

    path = tmp_path / 'consumer.pdf'
    _pdf(path, 595, 12, 0, has_space)
    item = DocumentInput('synthetic', str(path), path.name, 'application/pdf', sha256_file(path))
    result = VerificationPipeline(audit=AuditChain()).run('candidate-' + tmp_path.name, ProjectContext('synthetic'), [item])
    assert not result.errors
    metadata = result.documents[0].engine_data['input_boundary_associations']
    assert metadata['version'] == 1 and metadata['alternatives_checked'] is False
    assert metadata['unknown_count'] == (0 if has_space else 1)
    assert metadata['boundaries'][0]['precision'] == 'BLOCK_ASSOCIATION'
    assert all('text' not in choice for row in metadata['boundaries'] for choice in row['alternatives'])
    json.dumps(to_jsonable(result), ensure_ascii=False)
    monkeypatch.setattr(pipeline_module, 'boundary_association_metadata', lambda doc: None)
    baseline = VerificationPipeline(audit=AuditChain()).run('baseline-' + tmp_path.name, ProjectContext('synthetic'), [item])
    assert not baseline.errors
    assert result.scores == baseline.scores
    assert result.verification_key == baseline.verification_key
    assert result.documents[0].engine_data['model_input'] == baseline.documents[0].engine_data['model_input']
    assert result.model_executions == baseline.model_executions
    assert result.documents[0].warnings == baseline.documents[0].warnings
    assert result.documents[0].unverified_items == baseline.documents[0].unverified_items
    assert [b.text for b in result.documents[0].normalized.blocks] == [b.text for b in baseline.documents[0].normalized.blocks]
    def finding_states(run):
        return sorted((tuple(f.tags), f.status.value, f.severity.value, f.evidence_grade.value)
                      for f in run.all_findings)
    assert finding_states(result) == finding_states(baseline)


def test_legacy_floor_reason_uses_repeated_edge_not_longest_outlier():
    blocks = _blocks(['검토 가', '나다에 관한', '기록을 정리하였다.'])
    blocks[-1].bbox.x1 = 600
    block = reconstruct_page_blocks(blocks, page_width=720)[0]
    legacy = block.attributes['boundary_observations'][0]['decision']['legacy']
    assert block.attributes['paragraph_right_edge'] == 600
    assert legacy['content_edge'] == 500
    assert legacy['right_edge'] == 540
    assert legacy['floor_applied'] is True


def test_cross_run_composition_is_not_falsely_projected_as_exact():
    from packages.document_engine.boundary_candidates import project_boundary_candidate, project_boundary_view

    block = reconstruct_page_blocks(_blocks(['앞 (ᄀ', 'ᅡ나다 내용', '끝이다.']), page_width=595)[0]
    assert project_boundary_candidate(block) == block.text
    view = project_boundary_view(block, 0, 'JOIN')
    assert view['text'].startswith('앞 (가나다')
    assert view['boundaries'][0]['alignment']['precision'] == 'SOURCE_LINE_RANGE'
    # Project an alternative view only to check coarse reading associations;
    # no engine evaluates this hypothesis or changes the original primary block.
    alternate = Block('alternate-view', view['text'], 1, attributes={
        'boundary_observations': [{'decision': row} for row in view['boundaries']]})
    reading = build_reading_text(NormalizedDocument('synthetic', 'synthetic', 'application/pdf', 'synthetic', pages=[Page(1, blocks=[alternate])]))
    assert all(row['precision'] == 'BLOCK_ASSOCIATION' for row in reading.boundary_associations)


@pytest.mark.parametrize('choice', ['JOIN', 'SPACE'])
def test_alternative_view_has_its_own_source_alignment_without_mutation(choice):
    from packages.document_engine.boundary_candidates import project_boundary_view

    block = reconstruct_page_blocks(_blocks(['항목 Ａ (새', '문서)Ｂ를 살핀다.']), page_width=595)[0]
    original = json.dumps(block.to_dict(), ensure_ascii=False)
    view = project_boundary_view(block, 0, choice)
    span = view['boundaries'][0]['alignment']['primary_span']
    assert view['text'][span[0]:span[1]] == ('' if choice == 'JOIN' else ' ')
    assert all(run['normalization_changed'] and run['precision'] == 'SOURCE_LINE_RANGE' for run in view['source_runs'])
    assert view['source_runs'][1]['primary_span'][0] == span[1]
    assert json.dumps(block.to_dict(), ensure_ascii=False) == original


@pytest.mark.parametrize('choice', ['JOIN', 'SPACE'])
def test_lazy_projection_does_not_recover_original_after_primary_masking(choice):
    from packages.document_engine.boundary_candidates import project_boundary_view

    block = reconstruct_page_blocks(_blocks(['자료는 (새', '문서)이다.']), page_width=595)[0]
    block.text = '[가려진 본문]'
    with pytest.raises(ValueError, match='no longer match'):
        project_boundary_view(block, 0, choice)


@pytest.mark.parametrize('has_space', [False, True])
def test_actual_pdf_normalization_retains_original_source_range(tmp_path, has_space):
    from packages.document_engine.boundary_candidates import project_boundary_view

    path = tmp_path / 'normalized.pdf'
    _pdf(path, 595, 12, 0, has_space, left='항목 Ａ (새', right='문서)Ｂ를 살핀다.')
    doc = parse_document(str(path), document_id='synthetic', filename=path.name, mime_type='application/pdf', sha256='synthetic')
    block = next(b for b in doc.blocks if '항목 A (새' in b.text)
    view = project_boundary_view(block)
    assert view['text'] == block.text
    assert block.attributes['lines'][0]['text'] == '항목 Ａ (새'
    assert block.attributes['lines'][1]['text'] == '문서)Ｂ를 살핀다.'
    assert all(row['normalization_changed'] for row in view['source_runs'])
    assert all(row['glyph_mapping'] == 'LINE_ASSOCIATION' for row in view['source_runs'])
    row = view['boundaries'][0]
    a, b = row['alignment']['primary_span']
    assert view['text'][a:b] == (' ' if has_space else '')


def test_same_length_primary_edit_invalidates_exact_reading_alignment():
    block = reconstruct_page_blocks(_blocks(['자료의 내용', '문서를 정리한다.']), page_width=595)[0]
    span = block.attributes['boundary_observations'][0]['decision']['alignment']['primary_span']
    assert block.text[slice(*span)] == ' '
    block.text = block.text[:span[0]] + '_' + block.text[span[1]:]
    reading = build_reading_text(NormalizedDocument('synthetic', 'synthetic', 'application/pdf', 'synthetic', pages=[Page(1, blocks=[block])]))
    assert reading.boundary_associations[0]['precision'] == 'BLOCK_ASSOCIATION'


def test_hidden_blocks_are_not_associated_with_pipeline_body_metadata():
    from packages.document_engine.boundary_candidates import boundary_association_metadata

    block = reconstruct_page_blocks(_blocks(['자료는 (새', '문서)이다.']), page_width=595)[0]
    block.visible = False
    doc = NormalizedDocument('synthetic', 'synthetic', 'application/pdf', 'synthetic', pages=[Page(1, blocks=[block])])
    assert boundary_association_metadata(doc) is None
    assert build_reading_text(doc).boundary_associations == []


def test_legacy_cached_block_without_decisions_has_no_fabricated_alternatives():
    from packages.document_engine.boundary_candidates import project_boundary_candidate, boundary_association_metadata

    block = Block('old-source', '원래 본문', 1, attributes={'boundary_observations': [{'boundary_signal': 'UNKNOWN'}]})
    assert project_boundary_candidate(block) == block.text
    with pytest.raises(ValueError):
        project_boundary_candidate(block, 0, 'SPACE')
    doc = NormalizedDocument('synthetic', 'synthetic', 'application/pdf', 'synthetic', pages=[Page(1, blocks=[block])])
    assert boundary_association_metadata(doc) is None
    assert build_reading_text(doc).boundary_associations == []


def test_missing_geometry_does_not_claim_floor_or_glyph_evidence():
    blocks = _blocks(['자료의 내용', '문서를 정리한다.'])
    for block in blocks:
        block.bbox = None
    block = reconstruct_page_blocks(blocks, page_width=720)[0]
    decision = block.attributes['boundary_observations'][0]['decision']
    assert decision['observed_state'] == 'UNKNOWN'
    assert decision['legacy']['right_edge'] == 0
    assert decision['legacy']['floor_applied'] is False
    assert all(run['glyph_mapping'] == 'UNAVAILABLE' for run in block.attributes['boundary_source_runs'])


@pytest.mark.parametrize('width', [420, 595, 720])
@pytest.mark.parametrize('extra', [0, 1, 2])
@pytest.mark.parametrize('font,size', [('HYSMyeongJo-Medium', 10), ('HYGothic-Medium', 14)])
def test_actual_pdf_repeated_endpoint_primary_and_unknown_candidates(tmp_path, width, extra, font, size):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas
    from packages.document_engine.boundary_candidates import project_boundary_view

    pdfmetrics.registerFont(UnicodeCIDFont(font))
    path = tmp_path / 'repeated-endpoints.pdf'
    pdf = canvas.Canvas(str(path), pagesize=(width, 842))
    for i, (text, endpoint) in enumerate(zip(['기록을 확인할 수', '있다며 내용을', '정리하였다.'], [500, 500, 250])):
        obj = pdf.beginText(72, 760 - i * size * 1.5)
        obj.setFont(font, size)
        obj.setHorizScale(100 * (endpoint - 72) / pdfmetrics.stringWidth(text, font, size))
        obj.textOut(text)
        pdf.drawText(obj)
    for i in range(extra):
        pdf.setFont(font, size)
        pdf.drawString(72, 550 - i * size * 1.5, '다른 문단은 별도로 정리한다.')
    pdf.save()
    doc = parse_document(str(path), document_id='synthetic', filename=path.name, mime_type='application/pdf', sha256='synthetic')
    assert not doc.parse_warnings
    block = next(b for b in doc.blocks if '기록을 확인할 수' in b.text)
    rows = block.attributes['boundary_observations']
    assert all(row['boundary_signal'] == 'UNKNOWN' for row in rows)
    first = rows[0]['decision']
    assert first['selected_separator'] == ('' if width < 720 else ' ')
    assert first['selection_reason'] == ('LEGACY_FULLNESS_FRAGMENT' if width < 720 else 'LEGACY_DEFAULT_SPACE')
    assert first['legacy']['floor_applied'] is (width == 720)
    assert project_boundary_view(block)['text'] == block.text
    assert project_boundary_view(block, 0, 'JOIN')['text'] == '기록을 확인할 수있다며 내용을 정리하였다.'
    assert project_boundary_view(block, 0, 'SPACE')['text'] == '기록을 확인할 수 있다며 내용을 정리하였다.'
    assert all(choice['confirmation'] == 'UNCONFIRMED' for choice in first['alternatives'])
