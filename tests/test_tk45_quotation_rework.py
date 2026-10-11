"""Public opposing grammar controls, exercised through the actual TXT pipeline."""
import pytest

from tests.test_tk45_authored_predicate_scope import LIMIT, _pipeline_warnings


LEAD = "설령 계약이 인정되더라도, "
EMPHASIS = [
    ("“변제공탁”을 하지 않았으나", "“변제공탁”을 하였으므로", LIMIT),
    ("‘상계의 의사표시’를 하지 않았으나", "‘상계의 의사표시’가 도달하였으므로", LIMIT),
    ("전액을 지급하지 않았으나", "전액을 지급하였으므로", " 이 사건 채무에 관한 “책임을 질 수 없다”."),
]
PREDICATES = [
    ("상계의 의사표시가 도달하지 않았으나", "상계의 의사표시가 도달하였으므로"),
    ("변제공탁을 이행하지 않았으나", "변제공탁을 이행하였으므로"),
    ("변제공탁을 완료하지 않았으므로", "변제공탁을 완료하였으므로"),
    ("변제공탁을 마치지 않았으나", "변제공탁을 마쳤으므로"),
]


@pytest.mark.parametrize("denial,fulfilled,conclusion", EMPHASIS)
@pytest.mark.parametrize("denied", [True, False])
def test_actual_txt_author_emphasis_keeps_requirement_polarity(tmp_path, denial, fulfilled, conclusion, denied):
    findings = _pipeline_warnings(tmp_path, LEAD + (denial if denied else fulfilled) + conclusion)
    assert bool(findings) is denied
    if denied:
        assert all("요건 확인 요청" not in f.confidence_features["verdict"] for f in findings)
        assert any(row["state"] == "DENIED" for f in findings
                   for row in f.confidence_features["defense_scope"]["requirements"])
        assert any(row['role'] == 'AUTHORED' for f in findings
                   for row in f.confidence_features['defense_scope']['quotations'])


@pytest.mark.parametrize("denial,fulfilled", PREDICATES)
@pytest.mark.parametrize("denied", [True, False])
def test_actual_txt_generic_finite_governing_predicate(tmp_path, denial, fulfilled, denied):
    findings = _pipeline_warnings(tmp_path, LEAD + (denial if denied else fulfilled) + LIMIT)
    assert bool(findings) is denied
    if denied:
        assert all("요건 확인 요청" not in f.confidence_features["verdict"] for f in findings)
        assert any(row["state"] == "DENIED" for f in findings
                   for row in f.confidence_features["defense_scope"]["requirements"])
        for finding in findings:
            for row in finding.confidence_features['defense_scope']['requirements']:
                if row['state'] == 'DENIED':
                    assert row['governing_predicate_span'][0] >= row['span'][1]
                    assert row['negative_auxiliary_span'][0] >= row['governing_predicate_span'][1]


@pytest.mark.parametrize("requirement", ["변제공탁을 하지 않았으나", "전액을 지급하지 않았으나"])
@pytest.mark.parametrize("speaker", ["앞서 선고된 판결에서 법원은 ", "상대방은 "])
def test_actual_txt_reported_full_proposition_remains_excluded(tmp_path, requirement, speaker):
    report = "고 판시하였다." if "법원" in speaker else "고 주장하나, 그 주장은 이유 없다."
    text = speaker + "“" + LEAD + requirement + LIMIT[:-1] + "”" + report
    assert not _pipeline_warnings(tmp_path, text)


@pytest.mark.parametrize("denial,fulfilled", PREDICATES[:2])
@pytest.mark.parametrize("denied", [True, False])
def test_actual_txt_reported_quote_does_not_hide_own_rebuttal(tmp_path, denial, fulfilled, denied):
    report = "상대방은 “" + LEAD + denial + LIMIT[:-1] + "”고 주장하나; "
    findings = _pipeline_warnings(tmp_path, report + LEAD + (denial if denied else fulfilled) + LIMIT)
    assert bool(findings) is denied


@pytest.mark.parametrize("requirement", ["“변제공탁을 하지 않았다”고", "‘상계의 의사표시가 도달하였다’고"])
def test_actual_txt_unresolved_quotative_relation_requests_verification(tmp_path, requirement):
    findings = _pipeline_warnings(tmp_path, LEAD + requirement + LIMIT)
    assert findings
    assert all("요건 확인 요청" in f.confidence_features["verdict"] for f in findings)


@pytest.mark.parametrize("requirement", ["변제공탁을 늦추지 않게 준비하였으므로", "상계의 의사표시를 지연하지 않도록 하였으므로"])
def test_actual_txt_nonfinite_negative_attachment_is_uncertain(tmp_path, requirement):
    findings = _pipeline_warnings(tmp_path, LEAD + requirement + LIMIT)
    assert findings
    assert all("요건 확인 요청" in f.confidence_features["verdict"] for f in findings)


@pytest.mark.parametrize("requirement", ["변제공탁을 완료하였다고 하지 않았으나", "상계의 의사표시가 도달하였다고 하지 않았으나"])
def test_actual_txt_negated_report_of_a_predicate_is_uncertain(tmp_path, requirement):
    findings = _pipeline_warnings(tmp_path, LEAD + requirement + LIMIT)
    assert findings
    assert all("요건 확인 요청" in f.confidence_features["verdict"] for f in findings)
