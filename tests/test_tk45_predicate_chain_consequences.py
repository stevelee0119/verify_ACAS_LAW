"""Public finite-chain and bounded-consequence contrasts via real TXT inputs."""
import pytest

from tests.test_tk45_authored_predicate_scope import LIMIT, LIMIT_CONNECTIVE, _pipeline_warnings

LEAD = "설령 계약이 인정되더라도, "
FULFILLED = "변제공탁을 하였으므로"


@pytest.mark.parametrize("requirement", [
    "변제공탁을 지체하지 않고 완료하였으므로",
    "변제공탁을 주저하지 않고 이행하였으므로",
    "변제공탁을 지연하지 않고 마쳤으므로",
    "변제공탁을 지체하지 않고 중단하였으므로",
    "변제공탁을 주저하지 않고 유예하였으므로",
    "변제공탁을 지연하지 않고 포기하였으므로",
])
def test_actual_txt_unproven_chain_is_not_a_hard_denial_or_certified_fulfillment(tmp_path, requirement):
    findings = _pipeline_warnings(tmp_path, LEAD + requirement + LIMIT)
    assert findings
    assert all("요건 확인 요청" in f.confidence_features["verdict"] for f in findings)
    rows = [row for f in findings for row in f.confidence_features['defense_scope']['requirements']]
    assert rows and all(row['state'] == 'UNCERTAIN' for row in rows)
    assert any(row.get('predicate_chain') for row in rows)


@pytest.mark.parametrize("incidental,requirement", [
    ("지체하지 않고", "변제공탁을 하였으므로"),
    ("주저하지 않고", "전액을 지급하였으므로"),
    ("지연하지 않고", "상계의 의사표시가 도달하였으므로"),
])
def test_actual_txt_independently_asserted_requirement_remains_normal(tmp_path, incidental, requirement):
    assert not _pipeline_warnings(tmp_path, LEAD + incidental + " " + requirement + LIMIT)


@pytest.mark.parametrize("effect", [
    "형사처벌을 받지 않는다.", "징계처분을 받지 않는다.", "행정제재를 받지 않는다.",
])
@pytest.mark.parametrize("linked_sentence", [False, True])
def test_actual_txt_distinct_nonpast_negative_effect_is_reviewed(tmp_path, effect, linked_sentence):
    text = LEAD + FULFILLED + (LIMIT + " 따라서 " if linked_sentence else LIMIT_CONNECTIVE) + effect
    findings = _pipeline_warnings(tmp_path, text)
    assert findings
    assert any(row.get('candidate_kind') == 'FINITE_NEGATIVE' for f in findings
               for row in f.confidence_features['defense_scope']['conclusions'])
    assert all("요건 확인 요청" in f.confidence_features['verdict'] for f in findings)


@pytest.mark.parametrize("tail", [
    "따라서 이 사건 채무에 관한 책임을 질 수 없다.",
    "그러므로 해당 채무에 관한 책임이 없다.",
    "따라서 통지를 받지 않았다.",
    "그러므로 서류를 제출하지 않았다.",
    "형사책임은 성립할 수 없다.",  # No explicit sentence link.
    "따라서 별도의 당사자는 형사책임을 질 수 없다.",  # New subject.
    "그러므로 새 청구는 당연히 무효이다.",  # Independent subject.
])
def test_actual_txt_normal_restatement_fact_or_unlinked_independent_statement(tmp_path, tail):
    assert not _pipeline_warnings(tmp_path, LEAD + FULFILLED + LIMIT + " " + tail)


@pytest.mark.parametrize("tail", [
    "따라서 형사책임은 성립할 수 없다.",
    "그러므로 징계책임도 전면 면책된다.",
])
def test_actual_txt_explicit_immediate_author_link_keeps_known_extension(tmp_path, tail):
    assert _pipeline_warnings(tmp_path, LEAD + FULFILLED + LIMIT + " " + tail)


@pytest.mark.parametrize("effect", ["형사처벌을 받지 않는다", "징계처분을 받지 않는다"])
@pytest.mark.parametrize("speaker", ["상대방은 ", "앞서 선고된 판결에서 법원은 "])
def test_actual_txt_reported_context_cannot_supply_author_anchor(tmp_path, effect, speaker):
    ending = "고 주장하나, 그 주장은 이유 없다." if "상대방" in speaker else "고 판시하였다."
    report = speaker + '“' + LEAD + FULFILLED + LIMIT[:-1] + '”' + ending
    assert not _pipeline_warnings(tmp_path, report + " 따라서 " + effect + ".")


@pytest.mark.parametrize("effect", ["형사처벌을 받지 않는다", "징계처분을 받지 않는다"])
def test_actual_txt_reported_consequence_is_not_author_extension(tmp_path, effect):
    tail = ' 원고는 “' + effect + '”고 주장하나, 그 주장은 이유 없다.'
    assert not _pipeline_warnings(tmp_path, LEAD + FULFILLED + LIMIT_CONNECTIVE + tail)


@pytest.mark.parametrize("effect", ["형사처벌을 받지 않는다", "징계처분을 받지 않는다"])
def test_actual_txt_report_does_not_hide_new_author_consequence(tmp_path, effect):
    report = '상대방은 “' + LEAD + FULFILLED + LIMIT[:-1] + '”고 주장하나; '
    assert _pipeline_warnings(tmp_path, report + LEAD + FULFILLED + LIMIT_CONNECTIVE + effect + '.')


def test_actual_txt_prior_concession_does_not_leap_over_another_sentence(tmp_path):
    text = LEAD + FULFILLED + LIMIT + " 관련 서류는 다음에 제출한다. 따라서 형사책임은 성립할 수 없다."
    assert not _pipeline_warnings(tmp_path, text)


@pytest.mark.parametrize('requirement', [
    '변제공탁을 하지 않았으나', '전액을 지급하지 않았으나', '상계의 의사표시가 도달하지 않았으나',
])
def test_actual_txt_uncertain_effect_does_not_downgrade_established_requirement_denial(tmp_path, requirement):
    findings = _pipeline_warnings(tmp_path, LEAD + requirement + LIMIT_CONNECTIVE + '형사처벌을 받지 않는다.')
    assert findings
    assert all('요건 확인 요청' not in f.confidence_features['verdict'] for f in findings)
    assert any(row['state'] == 'DENIED' for f in findings
               for row in f.confidence_features['defense_scope']['requirements'])


@pytest.mark.parametrize('tail', ['따라서 형사책임은 성립할 수 없다.', '그러므로 행정제재를 받지 않는다.'])
def test_actual_txt_connection_evidence_is_local_to_retained_source_sentences(tmp_path, tail):
    prior = LEAD + FULFILLED + LIMIT
    findings = _pipeline_warnings(tmp_path, prior + ' ' + tail)
    assert findings
    for finding in findings:
        link = finding.confidence_features['defense_scope']['context_link']
        assert finding.confidence_features['claim'][slice(*link['prior_sentence_span'])] == prior
        assert finding.confidence_features['claim'][slice(*link['current_sentence_span'])] == tail
        assert finding.confidence_features['claim'][slice(*link['link_span'])].strip() in {'따라서', '그러므로'}
