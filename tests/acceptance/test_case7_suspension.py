"""서면7(2026구합10892 정직처분 취소청구 소장) 항목별 시험(평가 에이전트 소관, 보호 경로).

정답지 7대 영역 중 오프라인으로 재는 25개 항목(PII-11은 첫 점수를 기록한 뒤 사용자 결정으로 추가)(tests/fixtures/probes/case7_suspension.json)을 항목마다 한 시험으로 돈다.
수정 전 main(4ad64a7)의 첫 점수는 PDF 입력 10/24, 원문 텍스트 입력 16/24다(PII-11 추가 전 24개 항목 기준)(docs/scorecards/first_touch_log.jsonl).

알려진 미해결 항목은 strict xfail이다. 구현 에이전트가 고치면 XPASS(strict)가 되어 이 파일이 실패하므로,
평가 에이전트가 해당 xfail 표시를 지운다(고친 항목이 다시 깨지면 그때부터 일반 실패로 잡힌다). xfail 사유의 HO-nn은 docs/handoff/ 티켓이다.
이 파일의 점수는 일반화 근거가 아니다. 이 서면은 구현 에이전트가 볼 수 있는 개발 자료이므로, 처음 보는 서면에 대한 점수는 first_touch_log.jsonl이 답한다.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_document.py"
SPEC = ROOT / "tests" / "fixtures" / "probes" / "case7_suspension.json"


def _load_spec():
    module_spec = importlib.util.spec_from_file_location("probe_document_case7", SCRIPT)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules.setdefault("probe_document_case7", module)
    module_spec.loader.exec_module(module)
    return module.load_spec(SPEC)


CHECKS = {c["id"]: c["label"] for c in _load_spec()["checks"]}

# 알려진 미해결(수정 전 main 4ad64a7 기준). {입력 방식: {항목 id: 인계 티켓}}
KNOWN_OPEN = {
    "pdf": {
        "TEXT-1": "TK-01", "TEXT-2": "TK-01", "TEXT-3": "TK-01",
        "PII-2": "TK-01", "PII-7": "TK-01", "PII-9": "TK-01", "PII-10": "TK-01",
        "PII-5": "TK-02", "PII-6": "TK-02", "PII-11": "TK-02",
        "INJ-1": "TK-03", "TMP-1": "TK-04", "LEG-1": "TK-05", "LEG-2": "TK-05",
        "FA-1": "TK-06",
    },
    "text": {
        "PII-5": "TK-02", "PII-6": "TK-02", "PII-11": "TK-02",
        "INJ-1": "TK-03", "TMP-1": "TK-04", "LEG-1": "TK-05", "LEG-2": "TK-05",
        "CIT-3": "TK-07", "CIT-6": "TK-07",
    },
}


@functools.lru_cache(maxsize=None)
def results_for(mode: str) -> dict:
    """입력 방식(pdf | text)마다 점검을 한 번만 돌려 {항목 id: 통과 여부}를 돌려준다."""
    args = [sys.executable, str(SCRIPT), "run", "--spec", str(SPEC), "--json"] + (["--text"] if mode == "text" else [])
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-400:]
    rows = json.loads(proc.stdout.strip().splitlines()[-1])["rows"]
    return {row["id"]: row["passed"] for row in rows}


def _case(mode: str, check_id: str):
    ticket = KNOWN_OPEN[mode].get(check_id)
    marks = [pytest.mark.xfail(strict=True, reason=f"{ticket}: 수정 전 main에서 미해결")] if ticket else []
    return pytest.param(mode, check_id, marks=marks, id=f"{mode}-{check_id}")


@pytest.mark.parametrize("mode, check_id", [_case(m, c) for m in ("pdf", "text") for c in CHECKS])
def test_case7_check(mode, check_id):
    assert results_for(mode).get(check_id) is True, f"{check_id} {CHECKS[check_id]}"


def test_known_open_ids_are_real_checks():
    for mode, open_ids in KNOWN_OPEN.items():
        assert set(open_ids) <= set(CHECKS), (mode, set(open_ids) - set(CHECKS))
