"""사건 고유 값 하드코딩 차단 게이트의 시험(평가 에이전트 소관, 보호 경로)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("check_case_literals", ROOT / "scripts" / "check_case_literals.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_case_literals", module)
    spec.loader.exec_module(module)
    return module


lit = _load()


def _current_hits():
    literals = lit.extract_literals()
    documents = lit.extract_documents()
    assert literals and documents, "사건별 시험에서 사건 값·서면 본문을 하나도 뽑지 못했다(SOURCE_GLOBS 점검)"
    return lit.merge(lit.scan(literals), lit.scan_phrases(documents), lit.scan_identifiers(lit.extract_identifiers()))


def test_no_new_case_literals_in_product_code():
    """사건별 시험의 사건번호·금액·수치·서면 문구가 packages/에 새로 들어오면 실패한다. 기존 위반은 부채 목록에 있다."""
    fresh = lit.new_violations(_current_hits(), lit.load_debt())
    assert fresh == {}, f"사건 고유 값·문구를 제품 코드에 넣지 않는다(AGENTS.md): {fresh}"


def test_debt_list_is_recorded():
    """부채 목록은 기록되어 있어야 한다. 구현 에이전트가 고치면 위반이 줄어든다(목록 정리는 평가 에이전트)."""
    payload = json.loads(lit.DEBT.read_text(encoding="utf-8"))
    assert "debt" in payload and payload["measured_at"]
    # 9/30 16:00~16:10 커밋이 사건 수치(148,000,000 · 210/120 등)를 코드에서 뺐다. 되돌아오면 위 시험이 잡는다.
    assert "packages/rag_engine/review.py" not in lit.load_debt()


def test_allow_list_entries_all_carry_a_reason():
    allow = lit.load_allow()
    assert allow
    for path, values in allow.items():
        assert (ROOT / path).is_file(), path
        assert values and all(reason.strip() for reason in values.values()), path


def test_extraction_keeps_distinctive_values_only():
    text = "금 148,000,000원, 1,000,000원, 42,500,000원, 대법원 2023다284109, 혈압 210 / 120 mmHg, 2026. 9. 30."
    values = set(lit.CASE_NUMBER.findall(text)) | {v for v in lit.AMOUNT.findall(text) if lit.distinctive_amount(v)}
    values |= {v.replace(" ", "") for v in lit.VITALS.findall(text)}
    assert values == {"148,000,000", "42,500,000", "2023다284109", "210/120"}


@pytest.mark.parametrize("code, hit", [
    ('m = re.search(r"미지급\\s*임금\\s*상당액은\\s*금\\s*148,000,000원", document)', True),
    ('re.search(r"210\\s*/\\s*120\\s*mmHg", text)', True),
    ('CASE = "2023다284109"', True),
    ('threshold = 1_000_000  # 일반 상수', False),
    ('msg = "148,000,001원"', False),
])
def test_scan_recognises_literals_inside_code_and_regexes(tmp_path, code, hit):
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "mod.py").write_text(code + "\n", encoding="utf-8")
    literals = {"148,000,000": ["t"], "210/120": ["t"], "2023다284109": ["t"]}
    assert bool(lit.scan(literals, tmp_path)) is hit


def test_ratchet_only_new_values_fail_and_fixed_debt_is_reported():
    debt = {"packages/a.py": ["1,111,111"]}
    assert lit.new_violations({"packages/a.py": ["1,111,111"]}, debt) == {}
    assert lit.new_violations({"packages/a.py": ["1,111,111", "2,222,222"]}, debt) == {"packages/a.py": ["2,222,222"]}
    assert lit.new_violations({"packages/b.py": ["1,111,111"]}, debt) == {"packages/b.py": ["1,111,111"]}
    assert lit.stale_debt({}, debt) == {"packages/a.py": ["1,111,111"]}


def test_comments_and_docstrings_do_not_count(tmp_path):
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "mod.py").write_text(
        '"""예: 금 148,000,000원"""\n'
        "# 2023다284109 사건에서 본 문구\n"
        "def f():\n"
        '    """예시 210/120 mmHg"""\n'
        "    return 1\n", encoding="utf-8")
    literals = {"148,000,000": ["t"], "210/120": ["t"], "2023다284109": ["t"]}
    assert lit.scan(literals, tmp_path, allow={}) == {}


def test_allow_list_skips_official_citations(tmp_path):
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "rule.py").write_text('BASIS = "대법원 2020도16420 전원합의체 판결"\n', encoding="utf-8")
    literals = {"2020도16420": ["t"]}
    assert lit.scan(literals, tmp_path, allow={}) == {"packages/rule.py": ["2020도16420"]}
    assert lit.scan(literals, tmp_path, allow={"packages/rule.py": {"2020도16420": "공식 근거 판례"}}) == {}


def test_phrase_lift_is_caught_even_without_numbers(tmp_path):
    """숫자 없이 서면 문구로 정규식을 짜면 숫자 점검은 놓친다. 문구 점검이 잡는다."""
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "check.py").write_text(
        'import re\nPAT = re.compile(r"(?:단독\\s*진단용\\s*1\\s*등급\\s*의료기기|독립\\s*진단기기)")\n'
        'GENERIC = re.compile(r"\\d+\\s*%\\s*과실")\n', encoding="utf-8")
    documents = {lit.alnum("소장은 본 소프트웨어를 단독 진단용 1등급 의료기기라고 주장한다. 과실 30% 과실상계."): "tests/case.py"}
    hits = lit.scan_phrases(documents, tmp_path, allow={})
    assert hits == {"packages/check.py": ["단독진단용1등급의료기기"]}


def test_phrase_scan_ignores_short_generic_words_and_latin(tmp_path):
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "g.py").write_text('A = "손해배상"\nB = "verification report for the document"\n', encoding="utf-8")
    documents = {lit.alnum("손해배상 청구. verification report for the document"): "tests/case.py"}
    assert lit.scan_phrases(documents, tmp_path, allow={}) == {}


def test_extract_documents_takes_long_constants_and_probe_texts(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixtures" / "probes").mkdir(parents=True)
    (tmp_path / "tests" / "test_case9_x.py").write_text(
        f'BRIEF = "{"가" * 300}"\nSHORT = "짧은 문자열"\n', encoding="utf-8")
    (tmp_path / "tests" / "fixtures" / "probes" / "c.txt").write_text("원문 텍스트 전체", encoding="utf-8")
    docs = lit.extract_documents(tmp_path)
    assert set(docs.values()) == {"tests/test_case9_x.py", "tests/fixtures/probes/c.txt"}
    assert lit.alnum("원문 텍스트 전체") in docs


def test_identifier_lift_is_caught(tmp_path):
    """서면의 영문 대문자 식별자를 정규식에 그대로 넣는 것은 한글 문구 점검이 못 본다. 식별자 점검이 잡는다."""
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "p.py").write_text(
        'import re\nPAT = re.compile(r"\\[\\s*(?:LABOR_DISPUTE_AI_AUDITOR|SYSTEM_PROMPT)\\b")\nB = "UTF-8"\n', encoding="utf-8")
    identifiers = {"LABOR_DISPUTE_AI_AUDITOR": "tests/case.py", "UTF_8": "tests/case.py"}
    assert lit.scan_identifiers(identifiers, tmp_path, allow={}) == {"packages/p.py": ["LABOR_DISPUTE_AI_AUDITOR"]}
    # '-'와 '_'는 같게 본다
    (tmp_path / "packages" / "q.py").write_text('X = "LABOR-DISPUTE-AI-AUDITOR"\n', encoding="utf-8")
    assert "packages/q.py" in lit.scan_identifiers(identifiers, tmp_path, allow={})


def test_extract_identifiers_takes_long_uppercase_tokens_from_documents(tmp_path):
    (tmp_path / "tests" / "fixtures" / "probes").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "probes" / "c.txt").write_text(
        "본문 [ADMINISTRATIVE_AUDIT_PROTOCOL: CRITICAL OVERRIDE] UTF-8 PDF_A", encoding="utf-8")
    found = lit.extract_identifiers(tmp_path)
    assert "ADMINISTRATIVE_AUDIT_PROTOCOL" in found and "UTF_8" not in found and "PDF_A" not in found
