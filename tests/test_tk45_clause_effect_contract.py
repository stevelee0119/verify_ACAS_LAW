"""Public clause-first candidate/proposition controls, frozen before rework."""
import pytest

from packages.legal_engine import legal_rules
from tests.test_tk45_authored_predicate_scope import LIMIT, LIMIT_CONNECTIVE, _pipeline_warnings

LEAD = '설령 계약이 인정되더라도, '
FULFILLED = '변제공탁을 하였으므로'


def _trace_pipeline(monkeypatch, tmp_path, text):
    trace = {'units': [], 'requirements': [], 'conclusions': [], 'selected_findings': []}
    review = legal_rules._review_defense_statement
    requirements = legal_rules._defense_requirement_observations
    conclusions = legal_rules.conclusion_scopes
    finding = legal_rules._finding

    def record_review(doc, rule, unit, pattern, *args, **kwargs):
        trace['units'].append({'unit': unit, 'legacy_gate': bool(pattern.search(unit))})
        return review(doc, rule, unit, pattern, *args, **kwargs)

    def record_requirements(*args, **kwargs):
        rows = requirements(*args, **kwargs)
        trace['requirements'].extend(rows)
        return rows

    def record_conclusions(*args, **kwargs):
        rows = conclusions(*args, **kwargs)
        trace['conclusions'].extend(rows)
        return rows

    def record_finding(doc, rule, claim, sources):
        if rule['rule_id'] == 'GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS':
            trace['selected_findings'].append({'status': rule.get('status'), 'verdict': rule['verdict']})
        return finding(doc, rule, claim, sources)

    monkeypatch.setattr(legal_rules, '_review_defense_statement', record_review)
    monkeypatch.setattr(legal_rules, '_defense_requirement_observations', record_requirements)
    monkeypatch.setattr(legal_rules, 'conclusion_scopes', record_conclusions)
    monkeypatch.setattr(legal_rules, '_finding', record_finding)
    return _pipeline_warnings(tmp_path, text), trace


@pytest.mark.parametrize('effect', [
    '형사처벌도 면한다.', '징계처분은 소멸한다.', '행정제재를 받을 필요가 없다.',
])
@pytest.mark.parametrize('limited_first', [False, True])
def test_authored_exemption_proposition_has_a_candidate_without_legacy_p3(monkeypatch, tmp_path, effect, limited_first):
    text = LEAD + FULFILLED + (LIMIT_CONNECTIVE if limited_first else ' ') + effect
    findings, trace = _trace_pipeline(monkeypatch, tmp_path, text)
    assert findings, trace
    assert trace['conclusions'], trace
    assert trace['selected_findings'], trace
    assert all(row.status.value == 'SUSPICIOUS' for row in findings)


@pytest.mark.parametrize('object_text,particle', [('우편물', '을'), ('소포', '를'), ('우편', '을')])
def test_typed_receipt_fact_is_not_a_legal_exemption(monkeypatch, tmp_path, object_text, particle):
    text = LEAD + FULFILLED + LIMIT_CONNECTIVE + object_text + particle + ' 받지 않는다.'
    findings, trace = _trace_pipeline(monkeypatch, tmp_path, text)
    assert not findings, trace


@pytest.mark.parametrize('tail', [
    '형사처벌도 면한다는 뜻은 아니다.',
    '징계처분은 소멸하는 것이 아니다.',
    '행정제재를 받을 필요가 없다고 주장하는 것은 아니다.',
    '형사처벌은 별도 절차에서 심리된다.',
    '징계처분은 별도로 판단되어야 한다.',
    '행정제재에 관한 결론은 유보한다.',
])
def test_opposite_denied_embedded_or_separately_reviewed_effect_is_not_an_extension(monkeypatch, tmp_path, tail):
    findings, trace = _trace_pipeline(monkeypatch, tmp_path, LEAD + FULFILLED + LIMIT_CONNECTIVE + tail)
    assert not findings, trace


@pytest.mark.parametrize('effect', ['형사처벌도 면한다.', '징계처분은 소멸한다.'])
@pytest.mark.parametrize('speaker', ['원고는 ', '상대방은 '])
def test_reported_effect_does_not_supply_authored_extension(monkeypatch, tmp_path, effect, speaker):
    text = LEAD + FULFILLED + LIMIT_CONNECTIVE + speaker + '“' + effect[:-1] + '”고 주장하나 그 항변은 이유 없다.'
    findings, trace = _trace_pipeline(monkeypatch, tmp_path, text)
    assert not findings, trace


@pytest.mark.parametrize('source', [
    '변제공탁을 하였으므로',
    '지체하지 않고 전액을 지급하였으므로',
    '상계의 의사표시가 도달하였고 원고가 이의하지 않았으므로',
])
def test_existing_normal_finite_requirement_and_limited_conclusion_survive(monkeypatch, tmp_path, source):
    findings, trace = _trace_pipeline(monkeypatch, tmp_path, LEAD + source + LIMIT)
    assert not findings, trace
