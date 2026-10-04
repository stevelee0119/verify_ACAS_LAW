"""서면9(2026가합61942 손해배상(국) 준비서면) 항목별 시험(평가 에이전트 소관, 보호 경로).

정답지 7대 영역 중 오프라인으로 재는 28개 항목(tests/fixtures/probes/case9_state_compensation.json)을 항목마다 한 시험으로 돈다.
구현 에이전트가 처음 보는 상태로 main 9933548(3차 구현 뒤)에서 잰 첫 점수는 docx 27/28·텍스트 27/28이다(docs/scorecards/first_touch_log.jsonl).
사용자 온라인 보고서(PDF 입력) 채점은 case9_state_compensation_online.json(18/23)이며 이 시험의 대상이 아니다.
이 파일의 점수는 일반화 근거가 아니다(이제 구현 에이전트가 볼 수 있는 개발 자료다).

두 번째 절은 **배치 불변** 시험이다. 같은 서면을 물리적 줄 길이만 바꿔 넣어도(PDF는 쪽 너비에 따라 줄이 달라진다) 결과가 같아야 한다(TK-22).
TK-22의 텍스트 입력 부분은 4차 구현(S2, e6b58fd)에서 해결되어 표시를 지웠다(2026-10-01). PDF 입력은 test_layout_invariance_pdf.py.
미해결은 strict xfail이다. 고치면 XPASS(strict)로 실패하므로 평가 에이전트가 표시를 지운다.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_document.py"
SPEC = ROOT / "tests" / "fixtures" / "probes" / "case9_state_compensation.json"
TEXT = ROOT / "tests" / "fixtures" / "probes" / "case9_state_compensation.txt"


def _probe():
    spec = importlib.util.spec_from_file_location("probe_document_case9", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document_case9", module)
    spec.loader.exec_module(module)
    return module


probe = _probe()
CHECKS = {c["id"]: c["label"] for c in probe.load_spec(SPEC)["checks"]}

# 알려진 미해결. {입력 방식: {항목 id: 인계 티켓}}
KNOWN_OPEN = {"docx": {"LEG-2": "TK-24"}, "text": {"LEG-2": "TK-24"}}


@functools.lru_cache(maxsize=None)
def results_for(mode: str) -> dict:
    args = [sys.executable, str(SCRIPT), "run", "--spec", str(SPEC), "--json"] + (["--text"] if mode == "text" else [])
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-400:]
    rows = json.loads(proc.stdout.strip().splitlines()[-1])["rows"]
    return {row["id"]: row["passed"] for row in rows}


def _case(mode: str, check_id: str):
    ticket = KNOWN_OPEN[mode].get(check_id)
    marks = [pytest.mark.xfail(strict=True, reason=f"{ticket}: 9933548에서 미해결")] if ticket else []
    return pytest.param(mode, check_id, marks=marks, id=f"{mode}-{check_id}")


@pytest.mark.parametrize("mode, check_id", [_case(m, c) for m in ("docx", "text") for c in CHECKS])
def test_case9_check(mode, check_id):
    assert results_for(mode).get(check_id) is True, f"{check_id} {CHECKS[check_id]}"


def test_known_open_ids_are_real_checks():
    for mode, open_ids in KNOWN_OPEN.items():
        assert set(open_ids) <= set(CHECKS), (mode, set(open_ids) - set(CHECKS))


# ------------------------------------------------------------------------------ 배치 불변(TK-22) ---
def _wrapped(width: int) -> str:
    lines = []
    for line in TEXT.read_text(encoding="utf-8").split("\n"):
        lines.extend([line] if len(line) <= width else
                     textwrap.wrap(line, width=width, break_long_words=False, break_on_hyphens=False))
    return "\n".join(lines) + "\n"


def _observe(text: str, tmp_path: Path):
    path = tmp_path / "wrapped.txt"
    path.write_text(text, encoding="utf-8")
    return probe.observe(ROOT, path, "text/plain")


WIDTHS = [
    pytest.param(36, id="w36"),            # 4차 구현(S2, e6b58fd)에서 텍스트 입력은 해결됨. PDF 입력은 test_layout_invariance_pdf.py
    pytest.param(40, id="w40"),
    pytest.param(56, id="w56"),            # 표지가 한 줄에 들어가는 너비(대조군)
]


@pytest.mark.parametrize("width", WIDTHS)
def test_injection_stamp_survives_line_wrapping(width, tmp_path):
    spec = probe.load_spec(SPEC)
    inj = {"id": "INJ-1", **{k: v for k, v in next(c for c in spec["checks"] if c["id"] == "INJ-1").items() if k != "id"}}
    rows = probe.evaluate({"checks": [inj]}, _observe(_wrapped(width), tmp_path))
    assert rows[0]["passed"] is True


CLAIM_WIDTHS = [
    pytest.param(36, id="w36"),
    pytest.param(44, id="w44"),
    pytest.param(56, id="w56"),            # 인용 문장이 한 줄에 들어가는 너비(대조군)
]


@pytest.mark.parametrize("width", CLAIM_WIDTHS)
def test_regulation_claim_is_not_split_by_line_wrapping(width, tmp_path):
    """육군 규정 인용 문장(규정명·조항·인용문·결론)이 하나의 주장으로 남아야 Drive 원문과 대조할 수 있다(사용자 보고서에서 주장 70개로 쪼개져 대조 누락)."""
    from packages.claim_engine.extractor import extract_claims
    from packages.document_engine.registry import parse_document

    path = tmp_path / "wrapped.txt"
    path.write_text(_wrapped(width), encoding="utf-8")
    doc = parse_document(str(path), document_id="x", filename=path.name, mime_type="text/plain", sha256="x")
    texts = [c.text for c in extract_claims(doc)]
    assert any("제22조" in t and "브리핑" in t for t in texts), "규정 조항과 인용문이 서로 다른 주장으로 갈라졌다"
