"""서면8(2026가합48192 지체상금 청구 답변서) 항목별 시험(평가 에이전트 소관, 보호 경로).

이 서면은 구현 에이전트가 한 번도 보지 못한 상태에서 **고친 뒤의 코드(main cf7c739)**로 잰 첫 점수가 있다
(docs/scorecards/first_touch_log.jsonl: 오프라인 PDF 17/22·텍스트 17/22, 사용자 온라인 보고서 14/19).
정답지 7대 영역 중 오프라인으로 재는 22개 항목(tests/fixtures/probes/case8_delay_penalty.json)을 항목마다 한 시험으로 돈다.

미해결은 strict xfail이다(10건은 de243cc에서 풀려 표시를 지웠다). 고치면 XPASS(strict)로 실패하므로 평가 에이전트가 표시를 지운다.
이 파일의 점수는 일반화 근거가 아니다(이제 구현 에이전트가 볼 수 있는 개발 자료다).
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
SPEC = ROOT / "tests" / "fixtures" / "probes" / "case8_delay_penalty.json"


def _load_spec():
    module_spec = importlib.util.spec_from_file_location("probe_document_case8", SCRIPT)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules.setdefault("probe_document_case8", module)
    module_spec.loader.exec_module(module)
    return module.load_spec(SPEC)


CHECKS = {c["id"]: c["label"] for c in _load_spec()["checks"]}

# 알려진 미해결. {입력 방식: {항목 id: 인계 티켓}}
# 2026-10-01 de243cc에서 PDF 22/22, 3차 구현 9933548에서 원문 텍스트 입력도 22/22가 되었다.
KNOWN_OPEN = {"pdf": {}, "text": {}}      # 9933548(3차 구현)에서 텍스트 입력 LEG-1도 해결


@functools.lru_cache(maxsize=None)
def results_for(mode: str) -> dict:
    args = [sys.executable, str(SCRIPT), "run", "--spec", str(SPEC), "--json"] + (["--text"] if mode == "text" else [])
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-400:]
    rows = json.loads(proc.stdout.strip().splitlines()[-1])["rows"]
    return {row["id"]: row["passed"] for row in rows}


def _case(mode: str, check_id: str):
    ticket = KNOWN_OPEN[mode].get(check_id)
    marks = [pytest.mark.xfail(strict=True, reason=f"{ticket}: de243cc에서 미해결")] if ticket else []
    return pytest.param(mode, check_id, marks=marks, id=f"{mode}-{check_id}")


@pytest.mark.parametrize("mode, check_id", [_case(m, c) for m in ("pdf", "text") for c in CHECKS])
def test_case8_check(mode, check_id):
    assert results_for(mode).get(check_id) is True, f"{check_id} {CHECKS[check_id]}"


def test_known_open_ids_are_real_checks():
    for mode, open_ids in KNOWN_OPEN.items():
        assert set(open_ids) <= set(CHECKS), (mode, set(open_ids) - set(CHECKS))
