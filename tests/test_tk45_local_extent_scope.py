"""Public extent-attachment contract, fixed before its product correction."""
import pytest

from packages.legal_engine.legal_rules import _defense_requirement_observations
from tests.test_tk45_authored_predicate_scope import LIMIT, _pipeline_warnings

LEAD = '설령 계약이 인정되더라도, '


@pytest.mark.parametrize('source,qualifier', [
    ('일부 변제공탁을 지체하지 않고 완료하였으므로', '일부'),
    ('일부분만 변제공탁을 주저하지 않고 이행하였으므로', '일부분만'),
    ('변제공탁을 부분적으로 지체하지 않고 완료하였으므로', '부분적으로'),
    ('변제공탁을 조금 주저하지 않고 완수하였으므로', '조금'),
    ('변제공탁을 지체하지 않고 일부만 완료하였으므로', '일부만'),
])
def test_local_extent_blocks_new_whole_requirement_support_at_every_position(tmp_path, source, qualifier):
    rows = _defense_requirement_observations(source, ['변제공탁'], [], {})
    assert rows[0]['state'] == 'UNCERTAIN'
    evidence = rows[0]['predicate_semantics']
    assert not evidence['supports_asserted_fulfillment']
    assert not evidence['total_completion_asserted']
    extent = next(row for row in evidence['scope_limitations'] if source[slice(*row['span'])] == qualifier)
    assert extent['attachment'] == ('ARGUMENT_PREFIX' if source.startswith(qualifier) else 'PREDICATE_CHAIN')
    findings = _pipeline_warnings(tmp_path, LEAD + source + LIMIT)
    assert findings and all('요건 확인 요청' in row.confidence_features['verdict'] for row in findings)


@pytest.mark.parametrize('source', [
    '서류를 일부만 작성하였고 변제공탁을 지체하지 않고 완료하였으므로',
    '서류를 부분적으로 검토하였으나 변제공탁을 주저하지 않고 이행하였으므로',
    '일부 당사자는 서류를 검토하였고 변제공탁을 지체하지 않고 완료하였으므로',
    '변제공탁을 일부러 지체하지 않고 완료하였으므로',
    '일부러 변제공탁을 주저하지 않고 이행하였으므로',
    '변제공탁을 지체하지 않고 완료하였으므로',
])
def test_other_argument_independent_clause_and_other_lexeme_extent_do_not_transfer(tmp_path, source):
    rows = _defense_requirement_observations(source, ['변제공탁'], [], {})
    assert rows[0]['state'] == 'POSITIVE'
    assert rows[0]['predicate_semantics']['supports_asserted_fulfillment']
    assert not rows[0]['predicate_semantics'].get('scope_limitations')
    assert not _pipeline_warnings(tmp_path, LEAD + source + LIMIT)
