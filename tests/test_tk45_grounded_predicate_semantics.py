"""Grounded aspect meaning, ordinary event objects, and real TXT controls."""
import json

import pytest

from packages.legal_engine.predicate_semantics import VERSION, assertion_extent_evidence, past_predicate_evidence, sense_evidence
from packages.legal_engine.legal_rules import _defense_requirement_observations, load_defense_groups
from tests.test_tk45_authored_predicate_scope import LIMIT, _pipeline_warnings

LEAD = '가사 약정이 유효하더라도, '


@pytest.mark.parametrize('token,positive', [
    ('완료하였다', True), ('완수했으므로', True), ('완결하였기에', True),
    ('끝마쳤다', True), ('마치었으므로', True), ('끝냈습니다', False),
    ('이행하였으므로', True), ('수행했기에', False), ('실행하였다', False),
    ('중단하였다', False), ('포기했으므로', False), ('그만뒀다', False),
    ('연기했으므로', False), ('유예하였다', False), ('계획하였다', False),
    ('준비했기에', False), ('착수하였다', False), ('시작하였으므로', False),
])
def test_general_predicate_categories_use_public_senses_without_legal_nouns(token, positive):
    evidence = past_predicate_evidence(token, event_object=True)
    assert evidence and evidence['supports_asserted_fulfillment'] is positive
    assert evidence['version'] == VERSION and evidence['tense'] == 'PAST'
    assert all(sense['source'].startswith('https://krdict.korean.go.kr/') for sense in evidence['senses'])
    assert not evidence['underlying_facts_verified'] and not evidence['legal_sufficiency_verified']
    json.dumps(evidence, ensure_ascii=False)


@pytest.mark.parametrize('token', ['이행하였으므로', '수행하였다', '실행하였다', '끝냈다'])
def test_unbound_homonyms_cannot_authenticate_an_event(token):
    evidence = past_predicate_evidence(token)
    assert evidence and not evidence['sense_resolved']
    assert not evidence['supports_asserted_fulfillment']


@pytest.mark.parametrize('token', ['완료', '완료할', '완료한다는', '완료하지', '미완료하였다', '준완료하였다', '계획완료하였다'])
def test_exact_finite_assertion_required_and_no_prefix_exemptions(token):
    assert past_predicate_evidence(token, event_object=True) is None


@pytest.mark.parametrize('object_name', ['작업', '연구', '훈련'])
@pytest.mark.parametrize('final_act', ['완료하였으므로', '완수하였으므로', '중단하였으므로', '계획하였으므로'])
def test_same_attachment_classifier_handles_nonlegal_event_objects(object_name, final_act):
    rows = _defense_requirement_observations(object_name + '을 지체하지 않고 ' + final_act,
                                           [object_name], [], {})
    assert len(rows) == 1
    expected = 'POSITIVE' if final_act.startswith(('완료', '완수')) else 'UNCERTAIN'
    assert rows[0]['state'] == expected
    assert rows[0]['predicate_semantics']['observed_direct_object']


@pytest.mark.parametrize('requirement', [
    '변제공탁을 주저하지 않고 완수하였으므로',
    '변제공탁을 지연하지 않고 완결하였으므로',
    '변제공탁을 서두르지 않고 끝마쳤으므로',
])
def test_actual_txt_different_completion_and_realization_senses_preserve_limited_defense(tmp_path, requirement):
    assert not _pipeline_warnings(tmp_path, LEAD + requirement + LIMIT)


@pytest.mark.parametrize('requirement', [
    '변제공탁을 지체하지 않고 연기하였으므로',
    '변제공탁을 망설이지 않고 수행하였으므로',
    '변제공탁을 주저하지 않고 실행하였으므로',
    '변제공탁을 지체하지 않고 끝냈으므로',
    '변제공탁을 주저하지 않고 그만두었으므로',
    '변제공탁을 지연하지 않고 계획하였으므로',
    '변제공탁을 서두르지 않고 준비하였으므로',
    '변제공탁을 망설이지 않고 착수하였으므로',
    '변제공탁을 시작하였으므로',
    '변제공탁을 지체하지 않고 일부 이행하였으므로',
    '변제공탁을 주저하지 않고 일부분만 완료하였으므로',
    '변제공탁을 지연하지 않고 절반만 완수하였으므로',
    '변제공탁을 서두르지 않고 부분적으로 완료하였으므로',
    '변제공탁을 조금 이행하였으므로',
    '변제공탁 완료하였으므로',
    '변제공탁 이행하였으므로',
    '변제공탁을 지체하지 않고 다른 단계로 이행하였으므로',
    '변제공탁을 다른 단계로 이행하였으므로',
    '변제공탁을 지체하지 않고 완료할 예정이므로',
    '변제공탁을 지체하지 않고 완료하지 않았으므로',
    '변제공탁을 일을 완료하였으므로',
    '변제공탁 계획을 완료하였으므로',
    '변제공탁을 중단하였으므로',
    '변제공탁을 유예하였으므로',
    '변제공탁 계획을 지체하지 않고 완료하였으므로',
    '변제공탁을 지체하지 않고 서류를 완료하였으므로',
    '변제공탁을 지체하지 않고 일을 완료하였으므로',
    '변제공탁을 지체하지 않고 완료할 계획을 마쳤으므로',
    '변제공탁을 완료하지 않고 완료하였으므로',
    '변제공탁을 하지 않고 완료하였으므로',
    '변제공탁을 공탁하지 않고 완료하였으므로',
    '변제공탁을 지체하지 않고 구상하였으므로',
])
def test_actual_txt_other_act_plan_conflict_or_unknown_is_explicit_review(tmp_path, requirement):
    findings = _pipeline_warnings(tmp_path, LEAD + requirement + LIMIT)
    assert findings
    assert all('요건 확인 요청' in f.confidence_features['verdict'] for f in findings)


@pytest.mark.parametrize('requirement', ['변제공탁을 완료하지 않았으나', '변제공탁을 이행하지는 않았지만', '변제공탁을 완수하지 않았으므로'])
def test_actual_txt_negative_completion_is_still_denied(tmp_path, requirement):
    findings = _pipeline_warnings(tmp_path, LEAD + requirement + LIMIT)
    assert findings
    assert all('요건 확인 요청' not in f.confidence_features['verdict'] for f in findings)


@pytest.mark.parametrize('requirement', ['변제공탁을 완료하였으므로', '변제공탁을 이행하였으므로'])
def test_actual_txt_opponent_completion_cannot_supply_authored_fulfillment(tmp_path, requirement):
    text = '상대방은 “' + LEAD + requirement + LIMIT[:-1] + '”고 주장하나, 그 항변은 이유 없다.'
    assert not _pipeline_warnings(tmp_path, text)


@pytest.mark.parametrize('requirement', ['변제공탁을 완료하였으므로', '변제공탁을 완수하였으므로'])
def test_actual_txt_reported_completion_cannot_hide_own_denial(tmp_path, requirement):
    text = ('원고는 “' + requirement + '”고 주장하나; ' + LEAD
            + '변제공탁을 하지 않았으나' + LIMIT)
    assert _pipeline_warnings(tmp_path, text)


@pytest.mark.parametrize('requirement', ['변제공탁을 완료하였으므로', '변제공탁을 이행하였으므로'])
def test_actual_txt_quote_cannot_hide_authored_completion(tmp_path, requirement):
    text = '원고는 “변제공탁을 하지 않았다”고 주장하였으나; ' + LEAD + '지체하지 않고 ' + requirement + LIMIT
    assert not _pipeline_warnings(tmp_path, text)


def test_predicate_evidence_spans_refer_to_the_local_source():
    source = '변제공탁을 지체하지 않고 완료하였으므로'
    signals = load_defense_groups()['structural_signals']
    rows = _defense_requirement_observations(source, signals['stated_requirements'], [], signals['requirement_polarities'])
    row = next(row for row in rows if row['state'] == 'POSITIVE')
    evidence = row['predicate_semantics']
    assert source[slice(*evidence['span'])] == '완료하였으므로'
    assert source[slice(*evidence['argument_span'])] == '변제공탁'
    assert source[slice(*evidence['case_span'])] == '을'
    assert row['predicate_chain']['asserted_fulfillment_supported']
    assert not evidence['underlying_facts_verified']



@pytest.mark.parametrize('modifier', ['일부', '일부분만', '부분적으로', '절반만', '조금씩'])
def test_general_extent_is_separate_from_aspect_and_not_a_denial(modifier):
    evidence = assertion_extent_evidence(modifier)
    assert evidence and not evidence[0]['whole_requirement_supported']
    assert evidence[0]['source_senses']
    assert all(row['definition'] and row['retrieved_on'] == '2026-10-11'
               for row in evidence[0]['source_senses'])


@pytest.mark.parametrize('token', ['완료하였으므로', '이행하였으므로'])
def test_source_meaning_and_application_category_are_separate(token):
    evidence = past_predicate_evidence(token, event_object=True)
    assert evidence['mapping_authority'] == 'APPLICATION_NOT_NIKL_CLASSIFICATION'
    for sense in evidence['senses']:
        assert sense['source_sense_key'] and sense['definition']
        assert sense['homonym_number'] >= 0 and sense['sense_number'] >= 1
        assert sense['retrieved_on'] == '2026-10-11'
    assert evidence['total_completion_asserted'] is token.startswith('완료')



def test_legacy_single_finite_assertion_does_not_claim_a_resolved_completion_sense():
    source = '변제공탁을 끝냈고'
    rows = _defense_requirement_observations(source, ['변제공탁'], [], {})
    assert rows[0]['state'] == rows[0]['legacy_syntax_state'] == 'POSITIVE'
    assert rows[0]['reason'] == 'LEGACY_ASSERTED_PREDICATE_SENSE_UNRESOLVED'
    assert not rows[0]['predicate_semantics']['sense_resolved']
    assert not rows[0]['predicate_semantics']['supports_asserted_fulfillment']


def test_actual_txt_legacy_completion_and_later_other_object_denial_stay_separate(tmp_path):
    assert not _pipeline_warnings(tmp_path, LEAD + '변제공탁을 끝냈고 서류 사본은 받지 못하였으므로' + LIMIT)
